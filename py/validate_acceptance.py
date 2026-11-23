#!/usr/bin/env python3
"""Audit final APB UART regression evidence without changing raw outcomes.

Required evidence: the same 15 tests at seeds 1, 2, 3 for both RTL variants;
45 fixed PASS results and 33 upstream PASS / 12 genuine functional FAIL results;
matching source snapshots; measured coverage; and independently checked logs.
This script only reads existing evidence and writes the requested acceptance JSON.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
TESTS = (
    "uart_smoke_test", "uart_fifo_boundary_test", "uart_error_test", "uart_reset_test",
    "uart_tx_overflow_test", "uart_rx_retention_test", "uart_empty_read_test",
    "uart_address_mirror_test", "uart_parity_requirement_test",
    "uart_framing_requirement_test", "uart_error_association_test", "uart_irq_test",
    "uart_irq_requirement_test", "uart_random_stress_test", "uart_baud_sweep_test",
)
SEEDS = (1, 2, 3)
STRICT_TESTS = frozenset((
    "uart_parity_requirement_test", "uart_framing_requirement_test",
    "uart_error_association_test", "uart_irq_requirement_test",
))
PINNED_COMMIT = "dfad6e04d19cc9481d3cd2750b45b970dc61271b"
PINNED_BLOBS = {
    "rtl/apb_uart.sv": "3087b96eeea9099a830d44c5ba00e2227ceee2d0",
    "rtl/io_generic_fifo.sv": "5a1ab425eab3e0dc619a7c97f092f5b2ccb31229",
    "rtl/uart_interrupt.sv": "7cbd6344485738c644fce40715b74a5d073fd565",
    "rtl/uart_rx.sv": "b6f24e70e53102e8aadaf523bd884fcc34eed51a",
    "rtl/uart_tx.sv": "cd17340b9d29ad3ff94130f41ed67d4e3d025fce",
    "third_party/apb_uart_sv/LICENSE": "3a2b87e2d69e600999f1f648f751ea185e3ee06a",
    "third_party/apb_uart_sv/README.md": "266686071da0b61a975ce816f6702ff6c4883eab",
    "third_party/apb_uart_sv/src_files.yml": "2c55405beaaa9ab6be8e96178e802085935e9f4d",
}
PASS_MESSAGE = re.compile(
    r"^\s*(?:#\s*)?UVM_INFO\b[^\r\n]*\[UART_UVM_TEST_PASS\]\s+(\w+)\s+completed\b",
    re.MULTILINE,
)
UVM_ERROR_MESSAGE = re.compile(r"^\s*(?:#\s*)?UVM_ERROR\b(?!\s*:)", re.MULTILINE)
UVM_FATAL_MESSAGE = re.compile(r"^\s*(?:#\s*)?UVM_FATAL\b(?!\s*:)", re.MULTILINE)
RUNTIME_ERROR = re.compile(
    r"^\s*(?:#\s*)?(?:%Error|%Fatal|FATAL:|\*\*\s*(?:Error|Fatal)"
    r"|(?:Error|Fatal)-\[|Segmentation fault|terminate called|Aborting\b)", re.MULTILINE,
)
SB_COUNTS = re.compile(r"\[SB_COUNTS\]\s+TX=(\d+)\s+RX=(\d+)\s+resets=(\d+)\s+max_tx=(\d+)\s+max_rx=(\d+)")
STRESS_STATS = re.compile(
    r"\[STRESS_STATS\]\s+batches=(\d+)\s+TX=(\d+)\s+RX=(\d+)"
    r"\s+tx_hash=([0-9a-fA-F]{8})\s+rx_hash=([0-9a-fA-F]{8})\s+format_hash=([0-9a-fA-F]{8})"
)


class EvidenceError(ValueError):
    """Missing, inconsistent, or incomplete acceptance evidence."""


def local_path(value: str | Path, relative_to: Path | None = None) -> Path:
    """Translate saved /mnt/<drive>/ paths when auditing WSL runs on Windows."""
    value = str(value)
    if os.name == "nt":
        match = re.match(r"^/mnt/([a-zA-Z])/(.*)$", value)
        if match:
            value = f"{match[1].upper()}:/{match[2]}"
    else:
        match = re.match(r"^([a-zA-Z]):[\\/](.*)$", value)
        if match:
            value = f"/mnt/{match[1].lower()}/" + match[2].replace("\\", "/")
    path = Path(value)
    if not path.is_absolute() and relative_to is not None:
        path = relative_to / path
    return path.resolve()


def existing_file(value: Any, relative_to: Path | None = None) -> Path:
    if not isinstance(value, (str, Path)) or not str(value):
        raise EvidenceError("Missing artifact path")
    path = local_path(value, relative_to)
    if not path.is_file() or path.stat().st_size == 0:
        raise EvidenceError(f"Missing or empty evidence file: {path}")
    return path


def read_json(path: Path) -> dict:
    value = json.loads(existing_file(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EvidenceError(f"Expected a JSON object: {path}")
    return value


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise EvidenceError(message)


class Audit:
    def __init__(self) -> None:
        self.checks: list[dict] = []
        self.metrics: dict = {}
        self.expected_failures: list[dict] = []

    def check(self, name: str, function: Any) -> Any:
        try:
            actual = function()
        except (OSError, ValueError, TypeError, KeyError, AttributeError, ImportError) as error:
            self.checks.append({"check": name, "status": "FAIL", "reason": str(error)})
            return None
        self.checks.append({"check": name, "status": "PASS", "actual": actual})
        return actual


def severity_count(log: str, severity: str) -> int:
    matches = re.findall(rf"^\s*(?:#\s*)?UVM_{severity}\s*:\s*(\d+)\s*$", log, re.MULTILINE)
    require(bool(matches), f"Missing UVM_{severity} summary")
    return max(map(int, matches))


def check_build(report: dict, report_path: Path, variant: str) -> dict:
    require(report.get("rtl_variant") == variant, f"Expected RTL variant {variant}")
    require(report.get("status") == ("PASS" if variant == "fixed" else "FAIL"),
            "Raw report must be complete: fixed PASS, upstream FAIL with its expected failures retained")
    builds = report.get("build")
    require(isinstance(builds, list) and len(builds) > 0, "Missing actual compiler process evidence")
    for build in builds:
        require(build.get("returncode") == 0 and build.get("timed_out") is False,
                "Build timed out, crashed, or failed")
        log_path = existing_file(build.get("log"), report_path.parent)
        require(not RUNTIME_ERROR.search(log_path.read_text(encoding="utf-8", errors="replace")),
                f"Compiler error found in {log_path}")
    binary = report.get("compiled_binary", {})
    require(bool(re.fullmatch(r"[0-9a-f]{64}", binary.get("sha256", ""))) and binary.get("bytes", 0) > 0,
            "Missing compiled-binary hash/size provenance")
    return {"build_processes": len(builds), "raw_report_status": report["status"],
            "tool_version": report.get("tool_version"), "binary_sha256": binary["sha256"]}


def run_matrix(report: dict) -> dict[tuple[str, int], dict]:
    runs = report.get("runs")
    require(isinstance(runs, list), "Missing regression runs")
    pairs = [(item.get("test"), item.get("seed")) for item in runs]
    expected = {(test, seed) for test in TESTS for seed in SEEDS}
    require(len(pairs) == 45 and len(set(pairs)) == 45, f"Expected 45 unique runs; found {len(pairs)}")
    require(set(pairs) == expected, f"Test/seed matrix mismatch; missing={sorted(expected-set(pairs))}; extra={sorted(set(pairs)-expected)}")
    return dict(zip(pairs, runs))


def check_run(run: dict, report_path: Path, variant: str) -> dict:
    test, seed = run["test"], run["seed"]
    expected_failure = variant == "upstream" and test in STRICT_TESTS
    expected_status = "FAIL" if expected_failure else "PASS"
    require(run.get("status") == expected_status, f"Raw status {run.get('status')} does not match required {expected_status}")
    require(run.get("returncode") == 0 and run.get("timed_out") is False,
            "A timeout, abnormal exit, or simulator crash is not a functional expected failure")
    command = run.get("command", [])
    require(f"+UVM_TESTNAME={test}" in command, "Run command does not identify the requested test")
    require(any(value in command for value in (f"+verilator+seed+{seed}", f"+ntb_random_seed={seed}"))
            or any(command[index:index+2] == ["-sv_seed", str(seed)] for index in range(len(command)-1)),
            "Requested seed is absent from the actual simulator command")
    fixed_mode = any(str(value).split("=", 1)[0] == "+RTL_FIXED" for value in command)
    require(fixed_mode == (variant == "fixed"), "Runtime +RTL_FIXED mode does not match the RTL variant")
    path = existing_file(run.get("log"), report_path.parent)
    log = path.read_text(encoding="utf-8", errors="replace")
    errors, fatals = severity_count(log, "ERROR"), severity_count(log, "FATAL")
    require(run.get("uvm_errors") == errors and run.get("uvm_fatals") == fatals,
            "Report UVM counts disagree with the actual log summaries")
    require(fatals == 0 and not UVM_FATAL_MESSAGE.search(log) and not RUNTIME_ERROR.search(log),
            "Fatal or simulator error in log")
    markers = PASS_MESSAGE.findall(log)
    if expected_failure:
        require(errors > 0 and bool(UVM_ERROR_MESSAGE.search(log)), "Expected failure has no actual UVM_ERROR")
        require(not markers, "Expected functional failure emitted a completion PASS marker")
        require(run.get("reason") == "UVM reported an error or fatal", "Failure reason is not a functional UVM check failure")
    else:
        require(errors == 0 and not UVM_ERROR_MESSAGE.search(log), "PASS log has UVM errors")
        require(markers == [test], "PASS requires exactly one completion message for this test")
    counters = SB_COUNTS.findall(log)
    require(len(counters) == 1, "Expected one real scoreboard counter report")
    tx, rx, resets, max_tx, max_rx = map(int, counters[0])
    require(tx > 0 and rx > 0, "Both scoreboard directions must make actual comparisons")
    artifacts = {}
    for field in ("coverage_file", "waveform_file"):
        if run.get(field):
            artifacts[field] = str(existing_file(run[field], report_path.parent))
    result = {"test": test, "seed": seed, "raw_status": run["status"],
              "expected_behavior": "functional_failure" if expected_failure else "pass",
              "uvm_errors": errors, "uvm_fatals": fatals, "TX_checked": tx, "RX_checked": rx,
              "resets": resets, "max_tx_pending": max_tx, "max_rx_pending": max_rx,
              "log": str(path), "log_sha256": digest(path), "artifacts": artifacts}
    if test == "uart_random_stress_test":
        stress = STRESS_STATS.findall(log)
        require(len(stress) == 1, "Missing/duplicated stress checksum report")
        batches, stimulus_tx, stimulus_rx = map(int, stress[0][:3])
        require(batches == 16 and stimulus_tx == tx and stimulus_rx == rx and tx > 100 and rx > 100,
                "Stress stimulus counts must match >100 actual checks in each direction")
        result["stress"] = {"batches": batches, "TX": tx, "RX": rx,
                            "tx_hash": stress[0][3].lower(), "rx_hash": stress[0][4].lower(),
                            "format_hash": stress[0][5].lower()}
    return result


def check_stress(evidence: dict[str, list[dict]]) -> dict:
    output = {}
    for variant in ("fixed", "upstream"):
        runs = [run for run in evidence[variant] if run["test"] == "uart_random_stress_test"]
        require({run["seed"] for run in runs} == set(SEEDS), f"{variant}: missing stress seeds")
        for field in ("tx_hash", "rx_hash", "format_hash"):
            require(len({run["stress"][field] for run in runs}) == 3, f"{variant}: seeds did not produce three distinct {field} values")
        output[variant] = {str(run["seed"]): run["stress"] for run in runs}
    require(output["fixed"] == output["upstream"], "Identical stress seeds did not replay identical stimulus across RTL variants")
    return output


def checked_snapshot(report: dict, report_path: Path, variant: str) -> dict:
    snapshot_path = existing_file(report.get("source_manifest_file"), report_path.parent)
    snapshot = read_json(snapshot_path)
    require(snapshot == report.get("source_manifest"), "Saved and embedded source snapshots disagree")
    require(snapshot.get("captured_before_compile") is True and snapshot.get("algorithm") == "sha256"
            and snapshot.get("rtl_variant") == variant, "Source snapshot was not captured before this variant's compilation")
    stable = {"project_files": snapshot["project_files"], "uvm_files": snapshot["uvm_files"], "rtl_variant": variant}
    actual_snapshot_hash = hashlib.sha256(json.dumps(stable, sort_keys=True).encode("utf-8")).hexdigest()
    require(actual_snapshot_hash == snapshot.get("snapshot_sha256"), "Source snapshot digest is inconsistent")
    for item in snapshot["project_files"]:
        relative = Path(item["path"])
        require(not relative.is_absolute() and ".." not in relative.parts, "Unsafe snapshot source path")
        source = existing_file(ROOT / relative)
        require(digest(source) == item["sha256"] and source.stat().st_size == item["bytes"],
                f"Current source differs from the compiled snapshot: {relative}")
    require(len({item["path"] for item in snapshot["project_files"]}) == len(snapshot["project_files"]),
            "Duplicate source-file entries in the captured snapshot")
    return snapshot


def check_sources(reports: dict, paths: dict) -> dict:
    snapshots = {variant: checked_snapshot(reports[variant], paths[variant], variant) for variant in reports}
    maps = {}
    for variant, snapshot in snapshots.items():
        tb = {item["path"]: item["sha256"] for item in snapshot["project_files"] if item["path"].startswith("tb/")}
        actual_paths = {path.relative_to(ROOT).as_posix() for path in (ROOT / "tb").rglob("*")
                        if path.is_file() and path.suffix in (".sv", ".svh")}
        require(bool(tb) and set(tb) == actual_paths, f"{variant}: snapshot omits or duplicates testbench sources")
        maps[variant] = tb
    require(maps["fixed"] == maps["upstream"], "Fixed and upstream runs used different testbench file hashes")
    uvm_maps = [{item["path"]: item["sha256"] for item in snapshot["uvm_files"]} for snapshot in snapshots.values()]
    require(bool(uvm_maps[0]) and uvm_maps[0] == uvm_maps[1], "RTL variants used different or unrecorded UVM sources")
    manifest_path = ROOT / "third_party" / "apb_uart_sv" / "manifest.json"
    manifest = read_json(manifest_path)
    recorded_blobs = {item["path"]: item["git_blob_sha1"] for item in manifest["files"]}
    require(len(manifest["files"]) == 8 and recorded_blobs == PINNED_BLOBS and manifest["commit"] == PINNED_COMMIT,
            "Pinned upstream manifest differs from the verified eight-file import")
    for relative, expected in PINNED_BLOBS.items():
        content = existing_file(ROOT / relative).read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(content)).encode("ascii") + b"\0" + content).hexdigest()
        require(actual == expected, f"Pinned upstream file integrity mismatch: {relative}")
    for snapshot in snapshots.values():
        require(snapshot["upstream"].get("commit") == PINNED_COMMIT
                and snapshot["upstream"].get("manifest_sha256") == digest(manifest_path),
                "Compiled provenance does not identify the pinned upstream manifest")
    return {"identical_TB_files": len(maps["fixed"]), "identical_UVM_files": len(uvm_maps[0]),
            "pinned_files_verified": 8, "pinned_commit": PINNED_COMMIT,
            "snapshot_sha256": {variant: snapshot["snapshot_sha256"] for variant, snapshot in snapshots.items()}}


def check_coverage(report: dict, report_path: Path, run_evidence: list[dict]) -> dict:
    # These helpers parse the real native/LCOV files; no simulator API is called.
    from report_coverage import lcov_summary, native_summary, parse_records
    coverage = report.get("coverage", {})
    require(coverage.get("status") == "EXPORTED", "Fixed coverage export did not complete")
    exports = coverage.get("commands")
    require(isinstance(exports, list) and len(exports) > 0, "Missing actual coverage-export process evidence")
    for process in exports:
        require(process.get("returncode") == 0 and process.get("timed_out") is False,
                "Coverage export failed or timed out")
        log_path = existing_file(process.get("log"), report_path.parent)
        require(not RUNTIME_ERROR.search(log_path.read_text(encoding="utf-8", errors="replace")),
                f"Coverage-export error found in {log_path}")
    database = existing_file(coverage.get("merged_database"), report_path.parent)
    lcov = existing_file(coverage.get("lcov"), report_path.parent)
    summary_path = existing_file(coverage.get("native_summary"), report_path.parent)
    saved = read_json(summary_path)
    functional = native_summary(parse_records(database))["functional"]
    require(functional["status"] == "MEASURED", "No real functional-bin records in the merged database")
    for key in ("bins_hit", "bins_total", "bin_hit_percent"):
        require(functional[key] == saved["functional"][key], f"Coverage summary does not match native data: {key}")
    require(functional["bins_total"] == 277, "Expected the complete 277-bin coverage plan")
    require(100 * functional["bins_hit"] / functional["bins_total"] >= 95,
            f"Functional bin-hit ratio below 95%: {functional['bins_hit']}/{functional['bins_total']}")
    frame_bins = [item for item in functional["all_bins"] if "frame_cg.baud_format." in item["hierarchy"]]
    require(len(frame_bins) == 96 and all(item["covered"] for item in frame_bins),
            "The native baud/frame-format cross must contain and cover all 96 bins")
    require(len(functional["excluded_bins"]) == 2 and all(item.get("exclusion") == "default"
            and item["hierarchy"].endswith(("frame_cg.payload.other", "frame_cg.bit_period.other"))
            for item in functional["excluded_bins"]), "Unexpected functional coverage exclusions")
    lines = lcov_summary(lcov)["source_scopes"].get("rtl", {})
    require(lines.get("lines_total", 0) > 0 and 100 * lines.get("lines_hit", 0) / lines["lines_total"] >= 95,
            "Measured RTL LCOV line coverage is below 95%")
    require(lines == saved["lcov"]["source_scopes"]["rtl"], "Saved RTL line summary does not match the actual LCOV file")
    inputs = [str(existing_file(value, report_path.parent)) for value in coverage.get("inputs", [])]
    expected_inputs = [run["artifacts"].get("coverage_file") for run in run_evidence]
    require(len(inputs) == 45 and len(set(inputs)) == 45 and set(inputs) == set(expected_inputs),
            "Fixed merged coverage must include each of the 45 actual PASS databases exactly once")
    return {"functional_bins_hit": functional["bins_hit"], "functional_bins_total": functional["bins_total"],
            "functional_bin_hit_percent": functional["bin_hit_percent"],
            "baud_format_bins_hit": sum(item["covered"] for item in frame_bins), "baud_format_bins_total": 96,
            "RTL_lines_hit": lines["lines_hit"], "RTL_lines_total": lines["lines_total"],
            "RTL_line_percent": lines["line_percent"],
            "remaining_uncovered_bins": functional["uncovered_bins"],
            "database": str(database), "database_sha256": digest(database), "lcov": str(lcov)}


def validate(fixed: Path, upstream: Path) -> dict:
    audit = Audit()
    paths = {"fixed": fixed, "upstream": upstream}
    reports = {}
    for variant, path in paths.items():
        reports[variant] = audit.check(f"{variant}.report_readable", lambda path=path: read_json(path))
        if reports[variant] is not None:
            audit.checks[-1]["actual"] = {"path": str(path), "sha256": digest(path)}
    evidence: dict[str, list[dict]] = {"fixed": [], "upstream": []}
    for variant, report in reports.items():
        if report is None:
            continue
        audit.check(f"{variant}.completed_build", lambda report=report, variant=variant:
                    check_build(report, paths[variant], variant))
        matrix = audit.check(f"{variant}.exact_test_seed_matrix", lambda report=report: run_matrix(report))
        if matrix is None:
            continue
        # Store a compact matrix count rather than repeating its entire reports.
        audit.checks[-1]["actual"] = {"tests": 15, "seeds": list(SEEDS), "runs": len(matrix)}
        for (test, seed), run in sorted(matrix.items()):
            checked = audit.check(f"{variant}.{test}.seed_{seed}", lambda run=run, variant=variant:
                                  check_run(run, paths[variant], variant))
            if checked is not None:
                evidence[variant].append(checked)
                if checked["expected_behavior"] == "functional_failure":
                    audit.expected_failures.append(checked)
        counts = Counter(run["raw_status"] for run in evidence[variant])
        audit.metrics[variant] = {"raw_report_status": report.get("status"), "verified_runs": len(evidence[variant]),
                                  "raw_status_counts": dict(counts),
                                  "TX_compared_in_actual_PASS_runs": sum(run["TX_checked"] for run in evidence[variant] if run["raw_status"] == "PASS"),
                                  "RX_compared_in_actual_PASS_runs": sum(run["RX_checked"] for run in evidence[variant] if run["raw_status"] == "PASS")}
    audit.check("random_stimulus_seed_diversity_and_replay", lambda: check_stress(evidence))
    if all(report is not None for report in reports.values()):
        audit.check("source_and_pinned_integrity", lambda: check_sources(reports, paths))
    if reports["fixed"] is not None:
        measured = audit.check("fixed.native_coverage", lambda: check_coverage(reports["fixed"], fixed, evidence["fixed"]))
        if measured is not None:
            audit.metrics["coverage"] = measured
    def expected_failure_count() -> dict:
        require(len(audit.expected_failures) == 12, "All 12 upstream strict runs must fail for actual functional checks")
        return {"count": 12, "tests": sorted(STRICT_TESTS), "raw_status": "FAIL"}
    audit.check("upstream.expected_functional_failures_preserved", expected_failure_count)
    failures = [check for check in audit.checks if check["status"] != "PASS"]
    return {"status": "FAIL" if failures else "PASS", "checked_utc": datetime.now(timezone.utc).isoformat(),
            "scope": "Acceptance of recorded regression evidence; raw simulation statuses are never rewritten",
            "inputs": {variant: str(path) for variant, path in paths.items()},
            "requirements": {"tests": list(TESTS), "seeds": list(SEEDS), "fixed_PASS": 45,
                             "upstream_PASS": 33, "upstream_functional_FAIL": 12,
                             "minimum_functional_bin_hit_percent": 95, "minimum_RTL_line_percent": 95,
                             "baud_format_bins_required": 96},
            "metrics": audit.metrics, "checks": audit.checks, "failed_checks": len(failures),
            "expected_failures": audit.expected_failures}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fixed", required=True, help="Final fixed-RTL report.json")
    parser.add_argument("--upstream", required=True, help="Final upstream-RTL report.json")
    parser.add_argument("--out", required=True, help="New acceptance JSON; raw reports remain unchanged")
    args = parser.parse_args(argv)
    try:
        fixed, upstream, output = map(local_path, (args.fixed, args.upstream, args.out))
    except (OSError, ValueError) as error:
        parser.error(str(error))
    if output in (fixed, upstream):
        parser.error("--out must not overwrite an input regression report")
    result = validate(fixed, upstream)
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError as error:
        print(f"ACCEPTANCE_ERROR: Cannot write {output}: {error}")
        return 2
    print(f"ACCEPTANCE_{result['status']}: {len(result['checks'])} checks, {result['failed_checks']} failed; {output}")
    for check in result["checks"]:
        if check["status"] != "PASS":
            print(f"FAIL {check['check']}: {check['reason']}")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
