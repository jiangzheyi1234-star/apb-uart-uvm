#!/usr/bin/env python3
"""Reproduce the six archived failures whose original VCDs were not retained.

This runs existing, independently recorded Verilator executables; it never
compiles or changes a source file. New runs remain separate from their archived
FAIL records. A PASS here means six audited reproductions, not six DUT passes.
Use --plan-only to validate provenance and write commands without executing.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import sys
import tempfile

import run_mutation as mutation
import run_protocol_checks as protocol
import run_regression as regression
from waveform_data import waveform
from reproduced_waveforms import normalized_build_command, staged_project_root

ROOT = Path(__file__).resolve().parents[1]
STABLE_KEYS = ("project_files", "uvm_files", "rtl_variant")


def require(condition: object, message: str) -> None:
    if not condition:
        raise ValueError(message)


def digest(path: Path) -> str:
    return regression.file_digest(path)


def load(path: Path) -> dict:
    result = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(result, dict), f"Expected a JSON object: {path}")
    return result


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # A sibling file and replace keep the durable index complete after each run.
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def inside(root: Path, relative: str) -> Path:
    posix, windows = PurePosixPath(relative), PureWindowsPath(relative)
    require(bool(relative) and not posix.is_absolute() and not windows.drive
            and ".." not in posix.parts and ".." not in windows.parts
            and "\\" not in relative, f"Unsafe relative evidence path: {relative!r}")
    target = (root / relative).resolve()
    require(target.is_relative_to(root.resolve()), "Evidence path escapes its root")
    return target


def stable_snapshot(snapshot: dict) -> str:
    stable = {key: snapshot.get(key) for key in STABLE_KEYS}
    computed = hashlib.sha256(json.dumps(stable, sort_keys=True).encode("utf-8")).hexdigest()
    require(snapshot.get("captured_before_compile") is True
            and bool(snapshot.get("project_files")) and bool(snapshot.get("uvm_files"))
            and snapshot.get("snapshot_sha256") == computed,
            "Invalid build-time source snapshot")
    return computed


class Archive:
    """Read only paths explicitly sealed in an existing portable input map."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.summary = load(self.root / "summary.json")
        self.manifest_path = self.root / "inputs.json"
        entries = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        require(isinstance(entries, list), "Expected an archived inputs list")
        self.inputs = {}
        for item in entries:
            name = item.get("bundled_path")
            if name:
                require(name not in self.inputs, f"Duplicate archived input: {name}")
                self.inputs[name] = item

    def checked(self, relative: str, expected_sha256: str | None = None) -> Path:
        require(relative in self.inputs, f"Unsealed archived input: {relative}")
        path, item = inside(self.root, relative), self.inputs[relative]
        require(path.is_file() and path.stat().st_size == item.get("bytes")
                and digest(path) == item.get("sha256"), f"Archived input changed: {relative}")
        require(expected_sha256 is None or item["sha256"] == expected_sha256,
                f"Archive summary/input SHA mismatch: {relative}")
        return path


def assessment(case: dict, text: str, returncode: int | None, timed_out: bool) -> dict:
    if case["suite_id"] == "fault_control":
        result = mutation.assess_mutation(text, returncode, timed_out,
                                          {"mutation": case["mutation"], "test": case["test"],
                                           "expected_id": case["expected_error_id"]})
        return {**result, "raw_status": result["raw_simulation_status"], "classification": result["status"]}
    return protocol.assess_run(text, returncode, timed_out, case["test"], negative=True)


def validate_original_command(case: dict, command: list[str], binary_path: str) -> None:
    require(bool(command) and command[0] == binary_path, "Original command binary does not match its build identity")
    require(command.count(f"+UVM_TESTNAME={case['test']}") == 1
            and command.count(f"+verilator+seed+{case['seed']}") == 1,
            "Original command test/seed identity changed")
    require(len([arg for arg in command if arg.startswith("+UVM_TESTNAME=")]) == 1
            and len([arg for arg in command if arg.startswith("+verilator+seed+")]) == 1,
            "Ambiguous original test/seed arguments")
    faults = [arg for arg in command if arg.startswith("+MUTATION=")]
    require(faults == ([f"+MUTATION={case['mutation']}"] if case["mutation"] else []),
            "Original command mutation identity changed")
    require(("+RTL_FIXED=1" in command) == (case["suite_id"] == "fault_control"),
            "Original RTL selection does not match the suite")


def archived_cases(features: Path, protocols: Path) -> tuple[list[dict], dict]:
    """Bind the six exact archived rows, not similarly named clean controls."""
    fa, pa = Archive(features), Archive(protocols)
    fs = fa.summary["checker_sensitivity"]
    fault_report_path = fa.checked(fs["raw_report"], fs["raw_report_sha256"])
    fault_report = load(fault_report_path)
    fault_build_path = fa.checked(fs["baseline_raw_report"], fs["baseline_raw_report_sha256"])
    fault_build = load(fault_build_path)
    fault_snapshot_path = fa.checked(fs["baseline_provenance"]["snapshot_input"])
    pp = [item for item in pa.summary["provenance"] if item["phase"] == "negative"]
    require(len(pp) == 1, "Ambiguous original protocol negative profile")
    protocol_report_path = pa.checked(pp[0]["raw_report"])
    protocol_report = load(protocol_report_path)
    protocol_snapshot_path = pa.checked(pp[0]["snapshot_input"])
    profiles = {
        "uart": {"archive": fa, "build": fault_build, "build_path": fault_build_path,
                 "snapshot_path": fault_snapshot_path},
        "apb_protocol": {"archive": pa, "build": protocol_report, "build_path": protocol_report_path,
                         "snapshot_path": protocol_snapshot_path},
    }
    for name, profile in profiles.items():
        snapshot = load(profile["snapshot_path"])
        build = profile["build"]
        require(build.get("simulator") == "verilator" and build.get("suite") == name,
                "Original build suite is inconsistent")
        require(build.get("source_manifest") == snapshot, "Archived source sidecar differs from its original report")
        stable_snapshot(snapshot)
        normalized_build_command(build)
        profile["snapshot"] = snapshot
    baseline = fault_report.get("baseline", {})
    require(baseline.get("report_sha256") == digest(fault_build_path)
            and baseline.get("binary_sha256") == fault_build["compiled_binary"]["sha256"]
            and baseline.get("source_snapshot_sha256") == fault_build["source_manifest"]["snapshot_sha256"],
            "Mutation original report/build/source linkage changed")
    cases = []
    for fault in mutation.CASES:
        rows = [row for row in fault_report["runs"] if row.get("phase") == "mutation"
                and row.get("test") == fault["test"] and row.get("seed") == 1
                and row.get("mutation") == fault["mutation"]]
        summaries = [row for row in fs["runs"] if row.get("phase") == "mutation"
                     and row.get("test") == fault["test"] and row.get("seed") == 1
                     and row.get("mutation") == fault["mutation"]]
        require(len(rows) == len(summaries) == 1, "Missing or ambiguous archived mutation row")
        row, summary = rows[0], summaries[0]
        require(row.get("raw_simulation_status") == "FAIL" and row.get("status") == "DETECTED"
                and summary.get("classification") == "DETECTED", "Original mutation is not a detected raw FAIL")
        log = fa.checked(summary["transcript"], row["log_sha256"])
        require(summary.get("transcript_sha256") == digest(log), "Mutation summary log hash mismatch")
        case = {"suite_id": "fault_control", "profile": "uart", "variant": "fixed", "phase": "mutation",
                "mutation": fault["mutation"], "test": fault["test"], "seed": 1,
                "expected_error_id": fault["expected_id"], "original_report": fault_report_path,
                "original_log": log, "original_row": row}
        case["original_run_id"] = f"fault_control:mutation:{fault['test']}:{fault['mutation']}:1"
        cases.append(case)
    for seed in (2, 3):
        rows = [row for row in protocol_report["runs"] if row.get("test") == "apb_timeout_requirement_test"
                and row.get("seed") == seed]
        summaries = [row for row in pa.summary["runs"] if row.get("phase") == "negative"
                     and row.get("test") == "apb_timeout_requirement_test" and row.get("seed") == seed]
        require(len(rows) == len(summaries) == 1, "Missing or ambiguous archived protocol row")
        row, summary = rows[0], summaries[0]
        require(row.get("status") == summary.get("raw_status") == "FAIL"
                and summary.get("classification") == "DETECTED" and row.get("command") == summary.get("command"),
                "Original protocol identity/status is inconsistent")
        log = pa.checked(summary["log"], summary["log_sha256"])
        case = {"suite_id": "apb_protocol", "profile": "apb_protocol", "variant": "agent", "phase": "negative",
                "mutation": None, "test": "apb_timeout_requirement_test", "seed": seed,
                "expected_error_id": "APB_TIMEOUT", "original_report": protocol_report_path,
                "original_log": log, "original_row": row,
                "original_run_id": f"apb_protocol:negative:apb_timeout_requirement_test:{seed}"}
        cases.append(case)
    for case in cases:
        build = profiles[case["profile"]]["build"]
        validate_original_command(case, case["original_row"]["command"], build["compiled_binary"]["path"])
        result = assessment(case, regression.read_log(case["original_log"]),
                            case["original_row"].get("returncode"), case["original_row"].get("timed_out", False))
        require(result.get("raw_status") == "FAIL" and result.get("classification") == "DETECTED",
                f"Original transcript no longer validates: {case['original_run_id']}")
    return cases, profiles


def verify_sources(snapshot: dict, source_root: Path, uvm_root: Path) -> None:
    stable_snapshot(snapshot)
    for key, root in (("project_files", source_root), ("uvm_files", uvm_root)):
        paths = set()
        for entry in snapshot[key]:
            require(entry["path"] not in paths, "Duplicate source snapshot path")
            paths.add(entry["path"])
            path = inside(root, entry["path"])
            require(path.is_file() and path.stat().st_size == entry.get("bytes")
                    and digest(path) == entry.get("sha256"), f"Source bytes differ: {path}")


def select_build(original: dict, report_path: Path | None, binary_override: Path | None,
                 source_root: Path | None, uvm_root: Path | None) -> dict:
    path = report_path.resolve() if report_path else original["build_path"]
    report = load(path)
    previous = original["build"]
    require(report.get("simulator") == "verilator" and report.get("suite") == previous.get("suite")
            and report.get("rtl_variant") == previous.get("rtl_variant"), "Selected build has a different suite or RTL variant")
    require(report.get("tool_version") == previous.get("tool_version"), "Simulator version differs from the archived run")
    require(normalized_build_command(report) == normalized_build_command(previous),
            "Selected compiler arguments differ from the archived configuration")
    snapshot = report.get("source_manifest") or {}
    require(stable_snapshot(snapshot) == stable_snapshot(original["snapshot"])
            and all(snapshot.get(key) == original["snapshot"].get(key) for key in STABLE_KEYS),
            "Selected build sources differ from the original source snapshot")
    binary_record = report.get("compiled_binary") or {}
    binary = binary_override.resolve() if binary_override else protocol.local_path(binary_record.get("path", ""), path.parent)
    require(binary.is_file() and binary.stat().st_size == binary_record.get("bytes")
            and digest(binary) == binary_record.get("sha256"), "Selected binary differs from its recorded build identity")
    # The optional local report is a genuine completed build plus positive controls.
    # The archived negative protocol report remains allowed for byte-identical reuse.
    local_sidecars = []
    if report_path:
        require(report.get("status") == "PASS" and bool(report.get("runs")), "A rebuilt executable requires an actual PASS preflight report")
        for run in report["runs"]:
            require(run.get("status") == "PASS", "A rebuilt executable lacks clean preflight controls")
            log = protocol.local_path(run.get("log", ""), path.parent)
            text = regression.read_log(log)
            if report["suite"] == "uart":
                outcome = mutation.assess_control(text, run.get("returncode"), run.get("timed_out", False))
                require(outcome.get("status") == "PASS", "UART preflight control transcript failed validation")
            else:
                outcome = protocol.assess_run(text, run.get("returncode"), run.get("timed_out", False), run["test"], negative=False)
                require(outcome.get("classification") == "PASS", "Protocol preflight control transcript failed validation")
            require(run.get("command", [None])[0] == binary_record.get("path"), "Preflight command/build binary identity differs")
            local_sidecars.append(log)
        for process in report["build"]:
            log = protocol.local_path(process.get("log", ""), path.parent)
            require(log.is_file() and not regression.SIM_ERROR.search(regression.read_log(log)), "Missing or failed selected build transcript")
            local_sidecars.append(log)
        source_sidecar = protocol.local_path(report.get("source_manifest_file", ""), path.parent)
        require(source_sidecar.is_file() and load(source_sidecar) == snapshot, "Selected build source sidecar differs from its report")
        version_log = protocol.local_path(report.get("tool_version_log", ""), path.parent)
        require(version_log.is_file() and report["tool_version"] in regression.read_log(version_log), "Selected simulator version transcript missing")
        local_sidecars.append(version_log)
    else:
        source_sidecar = original["snapshot_path"]
    source = source_root.resolve() if source_root else protocol.local_path(staged_project_root(report), path.parent)
    uvm = uvm_root.resolve() if uvm_root else protocol.local_path(snapshot["uvm_source_root"], path.parent)
    verify_sources(snapshot, source, uvm)
    return {"report": report, "report_path": path, "snapshot": snapshot, "snapshot_path": source_sidecar,
            "source_root": source, "uvm_root": uvm, "binary": binary,
            "binary_sha256": digest(binary), "binary_bytes": binary.stat().st_size,
            "binary_matches_original": digest(binary) == previous["compiled_binary"]["sha256"],
            "sidecars": local_sidecars}


def reproduction_command(original: list[str], binary: Path, vcd: Path, coverage: Path) -> list[str]:
    """Change only binary relocation, TRACE and output paths in original argv."""
    require(bool(original), "Missing original runtime argv")
    result = [str(binary)]
    for arg in original[1:]:
        if arg.startswith("+VCD_FILE="):
            result.append(f"+VCD_FILE={vcd}")
        elif arg.startswith("+verilator+coverage+file+"):
            result.append(f"+verilator+coverage+file+{coverage}")
        else:
            result.append(arg)
    require(result.count("+TRACE") <= 1 and len([a for a in result if a.startswith("+VCD_FILE=")]) <= 1,
            "Original runtime has ambiguous trace options")
    if "+TRACE" not in result:
        result.append("+TRACE")
    if not any(arg.startswith("+VCD_FILE=") for arg in result):
        result.append(f"+VCD_FILE={vcd}")
    return result


class Bundle:
    def __init__(self, output: Path):
        self.root = output

    def copy(self, path: Path, directory: str) -> str:
        relative = f"{directory}/{digest(path)[:16]}_{path.name}"
        destination = inside(self.root, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(path, destination)
        require(digest(destination) == digest(path), "Evidence copy did not preserve bytes")
        return relative


def initial_entry(case: dict, original: dict, selected: dict, bundle: Bundle, session: str) -> dict:
    entry = {key: case[key] for key in ("original_run_id", "suite_id", "test", "seed", "variant", "phase", "mutation", "expected_error_id")}
    entry.update(reproduction_id=f"reproduction:{session}:{case['original_run_id']}",
                 original_command=case["original_row"]["command"],
                 original_source_snapshot_sha256=original["snapshot"]["snapshot_sha256"],
                 original_binary_sha256=original["build"]["compiled_binary"]["sha256"],
                 source_snapshot_sha256=selected["snapshot"]["snapshot_sha256"],
                 binary_sha256=selected["binary_sha256"], binary_bytes=selected["binary_bytes"],
                 binary_matches_original=selected["binary_matches_original"],
                 source_root_at_execution=str(selected["source_root"]), uvm_root_at_execution=str(selected["uvm_root"]),
                 binary_at_execution=str(selected["binary"]))
    for key, path, directory in (
        ("original_report", case["original_report"], "originals"),
        ("original_log", case["original_log"], "originals"),
        ("original_source_snapshot", original["snapshot_path"], "originals"),
        ("original_build_report", original["build_path"], "originals"),
        ("source_snapshot", selected["snapshot_path"], "builds"),
        ("build_report", selected["report_path"], "builds"),
    ):
        entry[key + "_path"] = bundle.copy(path, directory)
        entry[key + ("_file_sha256" if key.endswith("snapshot") else "_sha256")] = digest(path)
    entry["build_evidence"] = [{"path": bundle.copy(path, "builds"), "sha256": digest(path), "bytes": path.stat().st_size}
                               for path in selected["sidecars"]]
    return entry


def write_index(output: Path, report: dict) -> None:
    write_json(output / "index.json", report)
    lines = ["# Failure waveform reproductions", "", f"Reproduction audit: **{report['status']}**", "",
             "Original archived FAIL records remain unchanged. These are new executions with tracing enabled.",
             "DETECTED records the expected checker firing. The simulator result stays FAIL.", "",
             "| Original run | Raw status | Classification | Binary SHA-256 matches original | Log | VCD |", "| --- | --- | --- | --- | --- | --- |"]
    for entry in report["entries"]:
        lines.append(f"| {entry['original_run_id']} | {entry.get('raw_status', 'not executed')} | {entry.get('classification', 'PLANNED')} | {entry['binary_matches_original']} | {entry.get('raw_log_path', '')} | {entry.get('waveform_path', '')} |")
    if report.get("reason"):
        lines.extend(("", report["reason"]))
    (output / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--features", type=Path, default=ROOT / "docs/features")
    parser.add_argument("--protocol", type=Path, default=ROOT / "docs/protocol")
    parser.add_argument("--uart-build-report", type=Path)
    parser.add_argument("--protocol-build-report", type=Path)
    parser.add_argument("--uart-binary", type=Path)
    parser.add_argument("--protocol-binary", type=Path)
    parser.add_argument("--source-root", type=Path, help="Optional common source root, verified against both original snapshots")
    parser.add_argument("--uvm-root", type=Path, help="Optional UVM src root, verified byte-for-byte")
    parser.add_argument("--out", type=Path, required=True, help="New or empty durable evidence directory")
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--plan-only", action="store_true", help="Validate and record commands without running; never PASS")
    args = parser.parse_args(argv)
    output = args.out.resolve()
    report = None
    try:
        require(math.isfinite(args.timeout) and args.timeout > 0, "Timeout must be finite and positive")
        require(not output.exists() or (output.is_dir() and not any(output.iterdir())), "Output must be new or empty; no evidence is overwritten")
        cases, profiles = archived_cases(args.features, args.protocol)
        selected = {}
        for name, report_path, binary in (("uart", args.uart_build_report, args.uart_binary),
                                          ("apb_protocol", args.protocol_build_report, args.protocol_binary)):
            selected[name] = select_build(profiles[name], report_path, binary, args.source_root, args.uvm_root)
        # Complete all source/binary/build preflight before the first process.
        output.mkdir(parents=True, exist_ok=True)
        bundle = Bundle(output)
        now = datetime.now(timezone.utc)
        session = now.strftime("%Y%m%dT%H%M%S%fZ")
        report = {"schema_version": 1, "session": session, "status": "PLANNED" if args.plan_only else "RUNNING",
                  "started_utc": now.isoformat(), "scope": "Six new same-config failure reproductions; original archived results remain separate",
                  "entries": [], "limitations": ["Rebuilt executables can differ from original CI binaries; source/configuration equality and both binary hashes are recorded.",
                                                  "Only runtime tracing and output destinations change; these runs do not extend original regression or coverage totals."]}
        for index, case in enumerate(cases):
            entry = initial_entry(case, profiles[case["profile"]], selected[case["profile"]], bundle, session)
            tag = case["mutation"] or case["test"]
            relative = f"runs/{index:02d}_{tag}_seed_{case['seed']}"
            entry["raw_log_path"] = f"{relative}/simulation.log"
            entry["raw_report_path"] = f"{relative}/report.json"
            entry["waveform_path"] = f"{relative}/waves.vcd"
            entry["command"] = reproduction_command(entry["original_command"], selected[case["profile"]]["binary"],
                                                       inside(output, entry["waveform_path"]), Path("<SCRATCH>") / "coverage.dat")
            report["entries"].append(entry)
        write_index(output, report)
        if args.plan_only:
            print(f"PLANNED: no simulator executed; {output / 'index.json'}")
            return 0
        for case, entry in zip(cases, report["entries"]):
            chosen = selected[case["profile"]]
            require(digest(chosen["binary"]) == entry["binary_sha256"], "Binary changed after preflight")
            with tempfile.TemporaryDirectory(prefix="uart-reproduction-coverage-") as scratch:
                entry["command"] = reproduction_command(entry["original_command"], chosen["binary"],
                                                           inside(output, entry["waveform_path"]), Path(scratch) / "coverage.dat")
                process = regression.run_process(entry["command"], output, inside(output, entry["raw_log_path"]), args.timeout)
            raw = assessment(case, regression.read_log(inside(output, entry["raw_log_path"])), process.returncode, process.timed_out)
            entry.update({key: raw.get(key) for key in ("raw_status", "classification", "uvm_errors", "uvm_fatals")})
            entry["raw_log_sha256"] = digest(inside(output, entry["raw_log_path"]))
            entry["raw_log_bytes"] = inside(output, entry["raw_log_path"]).stat().st_size
            vcd = inside(output, entry["waveform_path"])
            valid_wave, wave_error = False, None
            if vcd.is_file() and vcd.stat().st_size:
                try:
                    decoded = waveform(vcd, id=entry["reproduction_id"], title=case["test"], run_id=entry["original_run_id"],
                                       url=entry["waveform_path"], uart_registers=case["suite_id"] == "fault_control")
                    valid_wave = bool(decoded.get("signals")) and decoded["range"][1] > decoded["range"][0]
                except (ValueError, KeyError, TypeError) as error:
                    wave_error = str(error)
                entry.update(waveform_sha256=digest(vcd), waveform_bytes=vcd.stat().st_size)
            record = {**asdict(process), **raw, "log": entry["raw_log_path"], "test": case["test"], "seed": case["seed"],
                      "suite_id": case["suite_id"], "variant": case["variant"], "phase": case["phase"], "mutation": case["mutation"],
                      "original_run_id": entry["original_run_id"], "reproduction_id": entry["reproduction_id"],
                      "binary_sha256": entry["binary_sha256"], "source_snapshot_sha256": entry["source_snapshot_sha256"],
                      "waveform_path": entry["waveform_path"], "waveform_sha256": entry.get("waveform_sha256"),
                      "waveform_bytes": entry.get("waveform_bytes"), "waveform_valid": valid_wave,
                      "waveform_error": wave_error}
            write_json(inside(output, entry["raw_report_path"]), record)
            entry["raw_report_sha256"] = digest(inside(output, entry["raw_report_path"]))
            entry["audit_status"] = "PASS" if raw.get("raw_status") == "FAIL" and raw.get("classification") == "DETECTED" and valid_wave else "FAIL"
            write_index(output, report)
            print(f"{entry['audit_status']}: {entry['original_run_id']} raw={entry['raw_status']} {entry['classification']}")
        for chosen in selected.values():
            verify_sources(chosen["snapshot"], chosen["source_root"], chosen["uvm_root"])
            require(digest(chosen["binary"]) == chosen["binary_sha256"], "Binary changed during reproduction")
        report["status"] = "PASS" if all(entry["audit_status"] == "PASS" for entry in report["entries"]) else "FAIL"
        report["completed_utc"] = datetime.now(timezone.utc).isoformat()
        report["metrics"] = {"reproductions": len(report["entries"]),
                             "detected_raw_failures": sum(entry.get("audit_status") == "PASS" for entry in report["entries"])}
        write_index(output, report)
        return 0 if report["status"] == "PASS" else 1
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        if report is not None:
            report.update(status="ERROR", reason=str(error), completed_utc=datetime.now(timezone.utc).isoformat())
            write_index(output, report)
        print(f"ERROR: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
