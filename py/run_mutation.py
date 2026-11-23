#!/usr/bin/env python3
"""Measure checker sensitivity with runtime faults in the real compiled DUT path.

The supplied fixed-RTL baseline must PASS and its compiled executable must match
the recorded SHA-256. Three tests run before injection, four faults run with
explicit activation markers, then the three clean controls run again. A crash,
timeout, fatal, unrelated failure or missing hook is never a detected mutation.
No RTL source is rewritten and no previous regression status is changed.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_regression as regression


CASES = (
    {"mutation": "tx_data_xor", "test": "uart_smoke_test", "expected_id": "TX_MISMATCH"},
    {"mutation": "rx_data_xor", "test": "uart_smoke_test", "expected_id": "RX_MISMATCH"},
    {"mutation": "parity_mask", "test": "uart_parity_requirement_test", "expected_id": "STATUS"},
    {"mutation": "irq_stuck_low", "test": "uart_irq_requirement_test", "expected_id": "IRQ"},
)
CONTROL_TESTS = tuple(dict.fromkeys(case["test"] for case in CASES))
ACTIVE = re.compile(r"^\s*(?:#\s*)?UVM_INFO\b[^\r\n]*\[MUTATION_ACTIVE\]([^\r\n]*)", re.MULTILINE)
FATAL_MESSAGE = re.compile(r"^\s*(?:#\s*)?(?:UVM_FATAL\b(?!\s*:)|%Fatal|Segmentation fault|terminate called|Aborting\b)", re.MULTILINE)


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def local_path(raw: str | Path, relative_to: Path) -> Path:
    value = str(raw)
    if os.name == "nt":
        match = re.match(r"^/mnt/([a-zA-Z])/(.*)$", value)
        if match:
            value = match[1].upper() + ":/" + match[2]
    else:
        match = re.match(r"^([a-zA-Z]):[\\/](.*)$", value)
        if match:
            value = "/mnt/" + match[1].lower() + "/" + match[2].replace("\\", "/")
    path = Path(value)
    return (relative_to / path).resolve() if not path.is_absolute() else path.resolve()


def validate_baseline(path: Path, selected_binary: Path | None, seed: int) -> tuple[dict, Path, dict]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("status") != "PASS" or report.get("rtl_variant") != "fixed" or report.get("simulator") != "verilator":
        raise ValueError("Mutation baseline must be an actual PASS report for fixed RTL using Verilator")
    if not report.get("build") or any(item.get("returncode") != 0 or item.get("timed_out") for item in report["build"]):
        raise ValueError("Baseline lacks a successful actual compiler process")
    recorded = report.get("compiled_binary") or {}
    binary = selected_binary.resolve() if selected_binary else local_path(recorded.get("path", ""), path.parent)
    if not binary.is_file() or not re.fullmatch(r"[0-9a-f]{64}", recorded.get("sha256", "")):
        raise ValueError("Baseline must record an existing compiled binary and a valid SHA-256")
    binary_hash = digest(binary)
    if binary_hash != recorded["sha256"] or binary.stat().st_size != recorded.get("bytes"):
        raise ValueError("The executable differs from the proven baseline binary; rerun the baseline first")
    snapshot = report.get("source_manifest") or {}
    stable = {key: snapshot.get(key) for key in ("project_files", "uvm_files", "rtl_variant")}
    expected = hashlib.sha256(json.dumps(stable, sort_keys=True).encode("utf-8")).hexdigest()
    if not snapshot.get("captured_before_compile") or not snapshot.get("project_files") or not snapshot.get("uvm_files") or snapshot.get("snapshot_sha256") != expected:
        raise ValueError("Baseline lacks a valid build-time source snapshot")
    evidence = []
    for test in CONTROL_TESTS:
        runs = [run for run in report.get("runs", []) if run.get("test") == test and run.get("seed") == seed]
        if len(runs) != 1 or runs[0].get("status") != "PASS":
            raise ValueError(f"Baseline must contain one PASS {test} at seed {seed}")
        run = runs[0]
        log = local_path(run.get("log", ""), path.parent)
        text = log.read_text(encoding="utf-8", errors="replace")
        outcome = regression.classify_log(text, run.get("returncode"), run.get("timed_out", False))
        if outcome.status != "PASS" or ACTIVE.search(text):
            raise ValueError(f"Baseline transcript is not a clean unmutated PASS: {test}")
        evidence.append({"test": test, "seed": seed, "log": str(log), "log_sha256": digest(log)})
    identity = {"report": str(path), "report_sha256": digest(path), "binary": str(binary),
                "binary_sha256": binary_hash, "binary_bytes": binary.stat().st_size,
                "source_snapshot_sha256": snapshot["snapshot_sha256"], "tool_version": report.get("tool_version"),
                "validated_baseline_tests": evidence}
    return report, binary, identity


def assess_control(text: str, returncode: int | None, timed_out: bool) -> dict:
    outcome = regression.classify_log(text, returncode, timed_out)
    if ACTIVE.search(text):
        return {**asdict(outcome), "raw_simulation_status": outcome.status, "status": "FAIL", "reason": "Mutation activation appeared in a clean control"}
    return {**asdict(outcome), "raw_simulation_status": outcome.status}


def assess_mutation(text: str, returncode: int | None, timed_out: bool, case: dict) -> dict:
    outcome = regression.classify_log(text, returncode, timed_out)
    result = {"status": "INVALID", "reason": "", "raw_simulation_status": outcome.status,
              "uvm_errors": outcome.uvm_errors, "uvm_fatals": outcome.uvm_fatals,
              "expected_error_id": case["expected_id"]}
    if timed_out or returncode != 0 or outcome.uvm_fatals != 0 or FATAL_MESSAGE.search(text) or regression.SIM_ERROR.search(text):
        result["reason"] = "A timeout, abnormal exit or UVM_FATAL cannot demonstrate functional checker sensitivity"
        return result
    active = ACTIVE.findall(text)
    if not any(re.search(rf"\b{re.escape(case['mutation'])}\b", message) for message in active):
        result["reason"] = "Missing exact MUTATION_ACTIVE marker for the requested runtime fault"
        return result
    if regression.PASS_MARKER.search(text):
        result.update(status="NOT_DETECTED", reason="A mutated run emitted the normal PASS completion marker")
        return result
    required_error = re.compile(
        rf"^\s*(?:#\s*)?UVM_ERROR\b[^\r\n]*\[{re.escape(case['expected_id'])}\]", re.MULTILINE
    )
    ids = re.findall(r"^\s*(?:#\s*)?UVM_ERROR\b[^\r\n]*?\[([^]\r\n]+)\]", text, re.MULTILINE)
    result["observed_error_ids"] = sorted(set(ids))
    if ids and set(ids) != {case["expected_id"]}:
        result.update(status="INVALID", reason="Unrelated UVM_ERROR IDs accompanied the isolated fault; only its intended checker is permitted")
        return result
    if outcome.status == "FAIL" and (outcome.uvm_errors or 0) > 0 and set(ids) == {case["expected_id"]} and required_error.search(text):
        result.update(status="DETECTED", reason="The activated fault reached its intended functional checker; normal exit and zero fatals")
    else:
        result.update(status="NOT_DETECTED", reason="The intended functional UVM error was not observed")
    return result


def write_report(output: Path, report: dict) -> None:
    (output / "mutation_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# UVM checker mutation sensitivity", "", f"Status: **{report['status']}**", "",
             "Runtime faults are injected between the testbench and the DUT. Vendored RTL is unchanged.",
             "A detected mutation requires its activation marker, the intended UVM_ERROR, normal exit, zero fatals, and no PASS marker.", ""]
    if report.get("reason"):
        lines.extend([report["reason"], ""])
    if report.get("metrics"):
        metrics = report["metrics"]
        lines.extend([f"Clean before/after controls: {metrics['clean_control_passes']}/{metrics['clean_control_total']}",
                      f"Functional mutations detected: {metrics['mutations_detected']}/{metrics['mutations_total']}",
                      f"Validated mutation score: {metrics['mutation_score_percent']}%", ""])
    lines.extend(["| Phase | Test | Mutation | Status | Intended checker | Log |", "| --- | --- | --- | --- | --- | --- |"])
    for item in report["runs"]:
        lines.append(f"| {item['phase']} | {item['test']} | {item.get('mutation') or 'none'} | {item['status']} | {item.get('expected_error_id') or ''} | {item.get('log') or ''} |")
    lines.extend(["", "An invalid or failed clean control invalidates the score; a crash or unrelated failure is not a detection.", ""])
    (output / "mutation_report.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--baseline-report", type=Path, required=True)
    parser.add_argument("--binary", type=Path, help="Override the recorded binary path; content must match its SHA-256")
    parser.add_argument("--out", type=Path, required=True, help="Fresh output directory for actual subprocess logs and JSON/Markdown")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=120)
    args = parser.parse_args(argv)
    if not 1 <= args.seed <= 2147483647 or args.timeout <= 0:
        parser.error("--seed must be in 1..2147483647 and --timeout must be positive")
    output = args.out.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error("--out must be a fresh or empty directory")
    output.mkdir(parents=True, exist_ok=True)
    report = {"status": "ERROR", "started_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "Actual same-binary runtime mutation controls; raw regression outcomes remain unchanged", "runs": []}
    try:
        baseline, binary, identity = validate_baseline(args.baseline_report.resolve(), args.binary, args.seed)
        report["baseline"] = identity
        has_coverage = any("--coverage" in item.get("command", []) for item in baseline["build"])
        plan = [("control_before", test, None) for test in CONTROL_TESTS]
        plan += [("mutation", case["test"], case) for case in CASES]
        plan += [("control_after", test, None) for test in CONTROL_TESTS]
        report["status"] = "RUNNING"
        for index, (phase, test, case) in enumerate(plan):
            directory = output / f"{index:02d}_{case['mutation'] if case else phase + '_' + test}"
            directory.mkdir()
            command = [str(binary), f"+UVM_TESTNAME={test}", f"+verilator+seed+{args.seed}", "+RTL_FIXED=1"]
            if has_coverage:
                command.append("+verilator+coverage+file+" + str(directory / "coverage.dat"))
            if case:
                command.append("+MUTATION=" + case["mutation"])
            process = regression.run_process(command, directory, directory / "simulation.log", args.timeout)
            text = regression.read_log(process.log)
            result = (assess_mutation(text, process.returncode, process.timed_out, case) if case else
                      assess_control(text, process.returncode, process.timed_out))
            record = {"phase": phase, "test": test, "seed": args.seed, "mutation": case["mutation"] if case else None,
                      **asdict(process), **result, "log_sha256": digest(Path(process.log))}
            report["runs"].append(record)
            write_report(output, report)
            print(f"{record['status']}: {phase} {test} {record.get('mutation') or ''}", flush=True)
        controls = [item for item in report["runs"] if item["phase"] != "mutation"]
        mutations = [item for item in report["runs"] if item["phase"] == "mutation"]
        controls_pass = all(item["status"] == "PASS" for item in controls)
        unchanged_binary = digest(binary) == identity["binary_sha256"]
        detected = sum(item["status"] == "DETECTED" for item in mutations)
        report["binary_unchanged_after_controls"] = unchanged_binary
        report["metrics"] = {"clean_control_passes": sum(item["status"] == "PASS" for item in controls),
                             "clean_control_total": len(controls), "mutations_detected": detected,
                             "mutations_total": len(mutations),
                             "mutation_score_percent": round(100 * detected / len(mutations), 2) if controls_pass and unchanged_binary else None}
        report["status"] = "PASS" if controls_pass and unchanged_binary and detected == len(CASES) else "FAIL"
    except (OSError, ValueError, TypeError, KeyError) as error:
        report["reason"] = str(error)
        write_report(output, report)
        print("MUTATION_ERROR: " + str(error), file=sys.stderr)
        return 2
    write_report(output, report)
    print(f"MUTATION_{report['status']}: {output / 'mutation_report.json'}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
