#!/usr/bin/env python3
"""Run and audit independent APB-agent protocol checks with real Verilator.

Nine positive runs, three expected timeout FAIL runs and three clean recovery
controls use one recorded binary/source identity. Raw report statuses remain
unchanged. PASS here describes the audit, not an all-PASS raw regression.
Invoke with Linux/WSL Python. There is deliberately no dry-run PASS mode.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_regression as regression


ROOT = Path(__file__).resolve().parents[1]
POSITIVE_TESTS = regression.DEFAULT_PROTOCOL_TESTS
NEGATIVE_TEST = "apb_timeout_requirement_test"
STATS_KEYS = ("completed", "reads", "writes", "wait0", "wait1", "wait3", "wait7",
              "max_wait", "reset_aborts", "timeout_aborts")
ERROR_IDS = re.compile(r"^\s*(?:#\s*)?UVM_ERROR\b(?!\s*:)[^\r\n]*?\[([^]\r\n]+)\]", re.MULTILINE)
FATAL_MESSAGE = re.compile(r"^\s*(?:#\s*)?(?:UVM_FATAL\b(?!\s*:)|%Fatal|Segmentation fault|terminate called|Aborting\b)", re.MULTILINE)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def marker(name: str) -> re.Pattern:
    return re.compile(r"^\s*(?:#\s*)?UVM_INFO\b[^\r\n]*?\[" + re.escape(name) + r"\]([^\r\n]*)", re.MULTILINE)


def parse_stats(text: str, test: str) -> dict:
    messages = marker("APB_AGENT_STATS").findall(text)
    require(len(messages) == 1, "Expected exactly one APB_AGENT_STATS message")
    pairs = re.findall(r"\b([a-zA-Z_][a-zA-Z_0-9]*)=([^\s]+)", messages[0])
    require(len(pairs) == len(dict(pairs)), "Duplicate APB_AGENT_STATS keys")
    values = dict(pairs)
    require(set(values) == {"test", *STATS_KEYS}, "APB_AGENT_STATS fields are missing or unexpected")
    require(values["test"] == test, "APB_AGENT_STATS test does not match the requested class")
    require(all(re.fullmatch(r"[0-9]+", values[key]) for key in STATS_KEYS), "Protocol statistics must be nonnegative integers")
    stats = {"test": test, **{key: int(values[key]) for key in STATS_KEYS}}
    require(stats["completed"] == stats["reads"] + stats["writes"], "Completed count differs from reads plus writes")
    require(stats["completed"] == sum(stats[f"wait{wait}"] for wait in (0, 1, 3, 7)), "Wait histogram differs from completed transfers")
    observed_waits = [wait for wait in (0, 1, 3, 7) if stats[f"wait{wait}"]]
    require(stats["max_wait"] == max(observed_waits, default=0), "max_wait differs from the completed-transfer histogram")
    return stats


def check_statistics(stats: dict, negative: bool) -> None:
    test = stats["test"]
    minimum = {
        "apb_wait_state_test": (11, 6, 5),
        "apb_reset_abort_test": (4, 2, 2),
        "apb_timeout_control_test": (2, 1, 1),
        NEGATIVE_TEST: (3, 2, 1),
    }
    require(test in minimum and negative == (test == NEGATIVE_TEST), "Unexpected protocol test/phase")
    require(all(stats[key] >= value for key, value in zip(("completed", "reads", "writes"), minimum[test])), "Missing completed read/write recovery traffic")
    require(stats["timeout_aborts"] == int(negative), "Unexpected timeout-abort count")
    require(stats["reset_aborts"] == int(test == "apb_reset_abort_test"), "Unexpected reset-abort count")
    if test == "apb_wait_state_test":
        require(all(stats[f"wait{wait}"] > 0 for wait in (0, 1, 3, 7)) and stats["max_wait"] == 7, "Wait-state coverage must include 0, 1, 3 and 7 cycles")
    elif test == "apb_timeout_control_test":
        require(stats["wait7"] >= 2 and stats["max_wait"] == 7, "Timeout control must complete two seven-wait transfers")
    elif test == "apb_reset_abort_test":
        require(stats["max_wait"] == 7, "Reset test must recover with seven-wait traffic")
    else:
        require(stats["max_wait"] <= 3, "Timeout recovery must use completed short-wait traffic")


def assess_run(text: str, returncode: int | None, timed_out: bool, test: str, negative: bool = False) -> dict:
    """Reclassify raw logs without changing the raw simulator result."""
    outcome = regression.classify_log(text, returncode, timed_out, "APB_AGENT_TEST_PASS")
    ids = ERROR_IDS.findall(text)
    result = {"raw_status": outcome.status, "classification": "INVALID", "reason": "",
              "uvm_errors": outcome.uvm_errors, "uvm_fatals": outcome.uvm_fatals,
              "error_ids": ids, "stats": None}
    try:
        require(not timed_out and returncode == 0, "A timeout or abnormal exit is not a protocol-check detection")
        require(not regression.SIM_ERROR.search(text) and not FATAL_MESSAGE.search(text), "Simulator errors or fatal messages invalidate protocol evidence")
        require(outcome.uvm_fatals == 0, "A complete zero-fatal UVM summary is required")
        stats = parse_stats(text, test)
        result["stats"] = stats
        check_statistics(stats, negative)
        armed = list(marker("APB_TIMEOUT_ARMED").finditer(text))
        complete = list(marker("APB_TIMEOUT_SCENARIO_COMPLETE").finditer(text))
        if negative:
            error_messages = re.findall(r"^\s*(?:#\s*)?UVM_ERROR\b(?!\s*:)", text, re.MULTILINE)
            require(outcome.status == "FAIL" and outcome.uvm_errors == 1 and ids == ["APB_TIMEOUT"] and len(error_messages) == 1,
                    "Expected exactly one APB_TIMEOUT UVM_ERROR and raw FAIL")
            summaries = re.findall(r"^\s*(?:#\s*)?UVM_ERROR\s*:\s*(\d+)\s*$", text, re.MULTILINE)
            require(summaries and all(int(value) == 1 for value in summaries), "Every negative severity summary must record exactly one error")
            require(not marker("APB_AGENT_TEST_PASS").search(text) and not regression.PASS_MARKER.search(text), "A negative timeout run must not emit any normal PASS marker")
            require(len(armed) == 1 and len(complete) == 1, "Timeout activation and scenario-complete markers must each appear once")
            error = ERROR_IDS.search(text)
            require(armed[0].start() < error.start() < complete[0].start(), "Timeout must occur between activation and completed recovery")
            recovery_pairs = re.findall(r"\b(timeout_wait_cycles|recovery_completed)=([0-9]+)\b", complete[0].group(1))
            recovery_fields = dict(recovery_pairs)
            require(len(recovery_pairs) == 2 and set(recovery_fields) == {"timeout_wait_cycles", "recovery_completed"}, "Scenario completion lacks unique timeout/recovery counts")
            require(int(recovery_fields["timeout_wait_cycles"]) == 8, "Negative case must reach its eight-cycle timeout limit")
            require(3 <= int(recovery_fields["recovery_completed"]) <= stats["completed"], "Negative case lacks at least three completed post-timeout recovery transfers")
            result.update(classification="DETECTED", reason="One armed APB_TIMEOUT was reported; the scenario recovered and completed normally")
        else:
            require(outcome.status == "PASS" and not ids and outcome.uvm_errors == 0, "Positive/recovery controls require a clean protocol PASS")
            require(len(marker("APB_AGENT_TEST_PASS").findall(text)) == 1, "A clean run must have exactly one protocol completion marker")
            require(not armed and not complete and not regression.PASS_MARKER.search(text), "Unexpected negative-case or UART completion marker in a clean protocol run")
            result.update(classification="PASS", reason="Protocol statistics and clean completion verified")
    except ValueError as error:
        result["reason"] = str(error)
    return result


def local_path(raw: str | Path, base: Path) -> Path:
    value = str(raw)
    if os.name == "nt":
        match = re.match(r"^/mnt/([a-zA-Z])/(.*)$", value)
        if match:
            value = match[1].upper() + ":/" + match[2]
    path = Path(value)
    return (base / path).resolve() if not path.is_absolute() else path.resolve()


def relative_source(root: Path, raw: str) -> Path:
    posix, windows = PurePosixPath(raw), PureWindowsPath(raw)
    require(not posix.is_absolute() and not windows.drive and ".." not in posix.parts and ".." not in windows.parts,
            "Unsafe source snapshot path")
    target = (root / raw).resolve()
    require(target.is_relative_to(root.resolve()), "Source snapshot escapes its root")
    return target


def validate_identity(report: dict, report_path: Path, source_root: Path) -> dict:
    require(report.get("suite") == "apb_protocol" and report.get("rtl_variant") is None and report.get("simulator") == "verilator", "Expected an independent Verilator APB protocol report")
    require(report.get("completion_marker") == "APB_AGENT_TEST_PASS", "Protocol report has the wrong completion-marker contract")
    builds = report.get("build") or []
    require(bool(builds), "Protocol evidence requires an actual successful compiler process")
    for build in builds:
        require(build.get("returncode") == 0 and not build.get("timed_out"), "Compiler process did not complete normally")
        log = local_path(build.get("log", ""), report_path.parent)
        require(log.is_file() and not regression.SIM_ERROR.search(regression.read_log(log)), "Missing or failed build transcript")
    binary_commands = [build.get("command", []) for build in builds if "--binary" in build.get("command", [])]
    require(len(binary_commands) == 1, "Expected one actual Verilator binary build command")
    compile_command = binary_commands[0]
    require("--top-module" in compile_command and compile_command[compile_command.index("--top-module") + 1:][:1] == ["tb_top"],
            "Protocol compiler command must select tb_top")
    require("-f" in compile_command and compile_command[compile_command.index("-f") + 1:]
            and Path(compile_command[compile_command.index("-f") + 1]).name == "files_protocol.f",
            "Protocol compiler command must select files_protocol.f")
    require("--coverage" not in compile_command, "Protocol compiler must not use the UART coverage pipeline")
    recorded = report.get("compiled_binary") or {}
    binary = local_path(recorded.get("path", ""), report_path.parent)
    require(binary.is_file() and recorded.get("sha256") == regression.file_digest(binary) and recorded.get("bytes") == binary.stat().st_size,
            "Recorded executable is missing or its bytes changed")
    snapshot = report.get("source_manifest") or {}
    stable = {key: snapshot.get(key) for key in ("project_files", "uvm_files", "rtl_variant")}
    snapshot_hash = hashlib.sha256(json.dumps(stable, sort_keys=True).encode("utf-8")).hexdigest()
    require(snapshot.get("captured_before_compile") and snapshot.get("suite") == "apb_protocol" and snapshot.get("rtl_variant") is None,
            "Missing protocol build-time source snapshot")
    require(snapshot.get("snapshot_sha256") == snapshot_hash and snapshot.get("project_files") and snapshot.get("uvm_files"), "Source snapshot is empty or its digest is invalid")
    sidecar = local_path(report.get("source_manifest_file", ""), report_path.parent)
    require(sidecar.is_file() and json.loads(regression.read_log(sidecar)) == snapshot, "Build-time source snapshot file differs from the report")
    paths = [entry["path"] for entry in snapshot["project_files"]]
    require(len(paths) == len(set(paths)) and "sim/files_protocol.f" in paths and not any(path.startswith(("rtl/", "rtl_fixed/")) for path in paths),
            "Protocol snapshot must select its own filelist without UART RTL")
    for entry in snapshot["project_files"]:
        path = relative_source(source_root, entry["path"])
        require(path.is_file() and regression.file_digest(path) == entry["sha256"] and path.stat().st_size == entry["bytes"], "Current project source differs from the compiled snapshot: " + entry["path"])
    uvm_root = Path(snapshot["uvm_source_root"])
    for entry in snapshot["uvm_files"]:
        path = relative_source(uvm_root, entry["path"])
        require(path.is_file() and regression.file_digest(path) == entry["sha256"] and path.stat().st_size == entry["bytes"], "UVM source differs from the compiled snapshot: " + entry["path"])
    return {"binary": str(binary), "binary_sha256": recorded["sha256"], "binary_bytes": recorded["bytes"],
            "source_snapshot_sha256": snapshot_hash, "source_snapshot_file": str(sidecar),
            "current_project_sources_match": True, "current_uvm_sources_match": True}


def audit_profile(path: Path, phase: str, seeds: list[int], source_root: Path = ROOT) -> tuple[dict, list[dict]]:
    report = json.loads(regression.read_log(path))
    tests = POSITIVE_TESTS if phase == "positive" else (NEGATIVE_TEST,) if phase == "negative" else (POSITIVE_TESTS[0],)
    require(phase in ("positive", "negative", "recovery"), "Unknown protocol audit phase")
    require(report.get("status") == ("FAIL" if phase == "negative" else "PASS"), "Raw profile status does not match the required phase")
    identity = validate_identity(report, path, source_root)
    runs = report.get("runs") or []
    actual = [(item.get("test"), item.get("seed")) for item in runs]
    expected = {(test, seed) for test in tests for seed in seeds}
    require(len(actual) == len(expected) and set(actual) == expected, "Protocol test/seed matrix is incomplete or duplicated")
    audited = []
    for run in runs:
        command = run.get("command", [])
        require(command and local_path(command[0], path.parent) == Path(identity["binary"]), "A run used a different executable")
        require(f"+UVM_TESTNAME={run['test']}" in command and f"+verilator+seed+{run['seed']}" in command, "Run command does not match its test/seed")
        require(not any(part.startswith(("+RTL_FIXED", "+verilator+coverage")) for part in command) and not run.get("coverage_file"), "UART runtime flags/coverage must not leak into protocol runs")
        log = local_path(run.get("log", ""), path.parent)
        result = assess_run(regression.read_log(log), run.get("returncode"), run.get("timed_out", False), run["test"], phase == "negative")
        require(run.get("status") == result["raw_status"] and run.get("uvm_errors") == result["uvm_errors"] and run.get("uvm_fatals") == result["uvm_fatals"], "Raw report disagrees with independently read protocol transcript")
        audited.append({"phase": phase, "test": run["test"], "seed": run["seed"], **result,
                        "command": command, "returncode": run.get("returncode"), "timed_out": run.get("timed_out", False),
                        "log": str(log), "log_sha256": regression.file_digest(log), "waveform_file": run.get("waveform_file")})
    return identity, audited


def write_report(output: Path, report: dict) -> None:
    (output / "protocol_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# APB agent protocol audit", "", f"Audit status: **{report['status']}**", "",
             "The audit matrix separates positive runs, expected raw timeout FAIL runs, and clean recovery controls.",
             "Audit PASS requires exact timeout/error markers, completed recovery, and unchanged binary/current-source identity.", ""]
    if report.get("reason"):
        lines.extend([report["reason"], ""])
    lines.extend(["| Phase | Test | Seed | Raw status | Audit classification | Log |", "| --- | --- | --- | --- | --- | --- |"])
    for run in report["runs"]:
        lines.append(f"| {run['phase']} | {run['test']} | {run['seed']} | {run['raw_status']} | {run['classification']} | {run['log']} |")
    (output / "protocol_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    parser.add_argument("--stage-dir", type=Path)
    parser.add_argument("--build-dir", type=Path)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--build-timeout", type=float, default=900)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--trace", action="store_true")
    args = parser.parse_args(argv)
    if os.name == "nt":
        parser.error("Invoke with Linux/WSL python3")
    if not args.seeds or len(set(args.seeds)) != len(args.seeds) or any(not 1 <= seed <= 2147483647 for seed in args.seeds):
        parser.error("--seeds must contain distinct integers in 1..2147483647")
    if args.timeout <= 0 or args.build_timeout <= 0 or args.jobs < 1:
        parser.error("timeouts and --jobs must be positive")
    output = args.out.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error("--out must be a new or empty directory")
    output.mkdir(parents=True, exist_ok=True)
    report = {"status": "RUNNING", "suite": "apb_protocol", "rtl_variant": None,
              "started_utc": datetime.now(timezone.utc).isoformat(), "seeds": args.seeds,
              "scope": "Independent APB-agent protocol audit; expected raw FAIL is preserved separately from detection",
              "audit_tool_sha256": regression.file_digest(Path(__file__)), "raw_reports": [], "runs": []}
    try:
        identities = []
        for phase, tests in (("positive", POSITIVE_TESTS), ("negative", (NEGATIVE_TEST,)), ("recovery", (POSITIVE_TESTS[0],))):
            command = [sys.executable, str(ROOT / "py" / "run_linux_regression.py"), "--suite", "apb_protocol",
                       "--out", str(output / phase), "--seeds", *map(str, args.seeds),
                       "--timeout", str(args.timeout), "--build-timeout", str(args.build_timeout), "--jobs", str(args.jobs)]
            for test in tests:
                command.extend(["--test", test])
            for name in ("stage_dir", "build_dir"):
                if getattr(args, name) is not None:
                    command.extend(["--" + name.replace("_", "-"), str(getattr(args, name))])
            if args.trace:
                command.append("--trace")
            print(f"PROTOCOL_PHASE: {phase} ({len(tests) * len(args.seeds)} raw runs)", flush=True)
            process = regression.run_process(command, ROOT, output / f"{phase}_runner.log",
                                             args.build_timeout + len(tests) * len(args.seeds) * args.timeout + 120)
            require(not process.timed_out and process.returncode == (1 if phase == "negative" else 0), "Protocol wrapper did not return the required raw phase status")
            raw = output / phase / "report.json"
            identity, runs = audit_profile(raw, phase, args.seeds, ROOT)
            identities.append(identity)
            require(all(identity[key] == identities[0][key] for key in ("binary", "binary_sha256", "binary_bytes", "source_snapshot_sha256")), "Compiler cache/profile changed the shared binary or source identity")
            report["raw_reports"].append({"phase": phase, "path": str(raw), "sha256": regression.file_digest(raw),
                                          "raw_status": "FAIL" if phase == "negative" else "PASS",
                                          "source_identity": identity, "runner_process": asdict(process)})
            report["runs"].extend(runs)
            write_report(output, report)
            expected_classification = "DETECTED" if phase == "negative" else "PASS"
            require(all(run["classification"] == expected_classification for run in runs), f"Invalid {phase} evidence: " + "; ".join(run["reason"] for run in runs if run["classification"] != expected_classification))
        first = identities[0]
        require(regression.file_digest(Path(first["binary"])) == first["binary_sha256"], "Executable changed after recovery controls")
        # Recheck current sources and all raw logs after the final compiler call.
        for saved in report["raw_reports"]:
            raw = Path(saved["path"])
            require(regression.file_digest(raw) == saved["sha256"], "A raw report changed during the audit")
            _, reruns = audit_profile(raw, saved["phase"], args.seeds, ROOT)
            expected = [run for run in report["runs"] if run["phase"] == saved["phase"]]
            require(reruns == expected, "A raw transcript changed during the audit")
        report["identity"] = {**first, "binary_unchanged_after_controls": True, "same_binary_all_profiles": True,
                              "same_source_snapshot_all_profiles": True}
        report["metrics"] = {
            "positive_passes": sum(run["phase"] == "positive" and run["classification"] == "PASS" for run in report["runs"]),
            "positive_total": len(POSITIVE_TESTS) * len(args.seeds),
            "timeouts_detected": sum(run["classification"] == "DETECTED" for run in report["runs"]),
            "negative_total": len(args.seeds),
            "recovery_passes": sum(run["phase"] == "recovery" and run["classification"] == "PASS" for run in report["runs"]),
            "recovery_total": len(args.seeds), "raw_simulations": len(report["runs"])}
        report["status"] = "PASS"
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        report["status"] = "FAIL" if isinstance(error, ValueError) else "ERROR"
        report["reason"] = str(error)
        write_report(output, report)
        print("PROTOCOL_" + report["status"] + ": " + str(error), file=sys.stderr)
        return 1 if report["status"] == "FAIL" else 2
    write_report(output, report)
    print("PROTOCOL_AUDIT_PASS: " + str(output / "protocol_report.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
