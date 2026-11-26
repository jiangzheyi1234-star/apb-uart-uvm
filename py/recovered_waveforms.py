"""Validate supplemental VCD copies against sealed UART execution records.

The supplement restores bytes identified by the original release manifest. It
does not replace raw reports, identify a new execution, or reconstruct a VCD
from a different seed. Missing supplements remain compatible with older bundles.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


TESTS = {
    "uart_parity_requirement_test", "uart_framing_requirement_test",
    "uart_error_association_test", "uart_irq_requirement_test",
}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _inside(base: Path, relative: str) -> Path:
    _require(isinstance(relative, str) and bool(relative), "Missing supplemental evidence path")
    _require("\\" not in relative and ":" not in relative and not relative.startswith("/"),
             "Supplemental evidence paths must be relative POSIX paths")
    _require(all(part not in ("", ".", "..") for part in relative.split("/")),
             "Supplemental evidence path contains an unsafe component")
    path = (base / relative).resolve()
    _require(path.is_relative_to(base) and path.is_file(), "Supplemental evidence path is missing or escapes its bundle")
    return path


def _verified_file(base: Path, relative: str, entry: dict) -> Path:
    path = _inside(base, relative)
    _require(path.stat().st_size == entry.get("bytes") and _digest(path) == entry.get("sha256"),
             "Supplemental evidence digest or byte count differs from its original manifest")
    return path


def recovered_wave_links(base: Path, root: Path) -> dict[str, dict]:
    """Return verified download links keyed by complete UART run identity.

    ``base`` is the release evidence directory; ``root`` is the directory from
    which dashboard URLs resolve (normally ``docs``). Index paths are relative
    to ``base``. ``original_manifest_path`` identifies exactly one
    ``inputs.json[*].original_path`` value, not a local recovery-source path.
    Every entry must name an unbundled failed upstream run in both the sealed
    release summary and its byte-verified raw report. No simulation is run.

    An absent index returns an empty mapping. A present but inconsistent index
    raises ``ValueError`` rather than offering an unrelated waveform.
    """
    base, root = base.resolve(), root.resolve()
    _require(base.is_relative_to(root), "Release evidence must be inside the dashboard URL root")
    index = base / "recovered-vcd" / "index.json"
    if not index.exists():
        return {}
    _require(index.resolve().is_relative_to(base) and index.is_file(), "Invalid supplemental index path")
    data = _read(index)
    _require(isinstance(data, dict) and isinstance(data.get("entries"), list) and bool(data["entries"]),
             "Supplemental index must contain a nonempty entries list")
    manifest = _read(base / "inputs.json")
    _require(isinstance(manifest, list), "Release inputs must be a list manifest")
    _require(all(isinstance(item, dict) for item in manifest), "Malformed release manifest entry")
    by_original: dict[str, list[dict]] = {}
    by_bundled: dict[str, list[dict]] = {}
    for item in manifest:
        by_original.setdefault(item.get("original_path"), []).append(item)
        if item.get("bundled_path"):
            by_bundled.setdefault(item["bundled_path"], []).append(item)
    summary = _read(base / "summary.json")
    reports = [report for report in summary.get("reports", []) if report.get("rtl_variant") == "upstream"]
    _require(len(reports) == 1, "Supplement requires one unambiguous upstream release report")
    report = reports[0]
    report_entries = by_bundled.get(report.get("report_input"), [])
    _require(len(report_entries) == 1 and report_entries[0].get("role") == "regression_report",
             "Raw upstream report is not uniquely identified by the original manifest")
    raw_path = _verified_file(base, report["report_input"], report_entries[0])
    _require(report.get("report_sha256") == report_entries[0].get("sha256"),
             "Release summary differs from its raw report identity")
    raw = _read(raw_path)
    _require(raw.get("suite") == "uart" and raw.get("rtl_variant") == "upstream"
             and raw.get("simulator") == "verilator", "Supplement targets a different execution suite or RTL variant")
    _require(raw.get("compiled_binary") == report.get("compiled_binary"),
             "Release binary execution identity differs from its raw report")
    snapshot_record = report.get("build_source_snapshot", {})
    snapshot_entries = by_bundled.get(snapshot_record.get("manifest_input"), [])
    _require(len(snapshot_entries) == 1 and snapshot_entries[0].get("role") == "build_time_source_manifest"
             and snapshot_entries[0].get("original_path") == raw.get("source_manifest_file"),
             "Supplement source snapshot is absent from the original manifest")
    snapshot_path = _verified_file(base, snapshot_record["manifest_input"], snapshot_entries[0])
    snapshot = _read(snapshot_path)
    _require(snapshot == raw.get("source_manifest") and snapshot.get("captured_before_compile"),
             "Supplement source snapshot differs from the recorded build")
    stable = {key: snapshot.get(key) for key in ("project_files", "uvm_files", "rtl_variant")}
    snapshot_digest = hashlib.sha256(json.dumps(stable, sort_keys=True).encode("utf-8")).hexdigest()
    _require(snapshot.get("snapshot_sha256") == snapshot_record.get("snapshot_sha256") == snapshot_digest,
             "Supplement build source snapshot digest is inconsistent")
    raw_rows = {(row.get("test"), row.get("seed")): row for row in raw.get("runs", [])}
    saved_rows = {(row.get("test"), row.get("seed")): row for row in report.get("runs", [])}
    _require(len(raw_rows) == len(raw.get("runs", [])) and len(saved_rows) == len(report.get("runs", []))
             and set(raw_rows) == set(saved_rows), "Ambiguous or inconsistent upstream run identities")
    result = {}
    seen_files = set()
    for entry in data["entries"]:
        _require(isinstance(entry, dict), "Malformed supplemental waveform entry")
        test, seed = entry.get("test"), entry.get("seed")
        _require(isinstance(test, str) and test in TESTS and type(seed) is int and 1 <= seed <= 2147483647
                 and entry.get("variant") == "upstream", "Supplement targets an unsupported run")
        run_id = f"uart_core:upstream:{test}:{seed}"
        _require(entry.get("run_id") == run_id and run_id not in result, "Duplicate or incorrect supplemental run identity")
        relative = entry.get("bundled_path")
        _require(isinstance(relative, str) and bool(re.fullmatch(r"recovered-vcd/[A-Za-z0-9_.-]+\.vcd", relative))
                 and relative not in seen_files, "Supplemental VCD path is invalid or reused")
        seen_files.add(relative)
        _require(isinstance(entry.get("sha256"), str) and bool(re.fullmatch(r"[a-f0-9]{64}", entry["sha256"]))
                 and type(entry.get("bytes")) is int and entry["bytes"] > 0, "Malformed supplemental digest or byte count")
        matches = by_original.get(entry.get("original_manifest_path"), [])
        _require(len(matches) == 1 and matches[0].get("role") == "vcd_waveform"
                 and matches[0].get("bundled_path") is None, "Supplement does not identify one originally unbundled VCD")
        original = matches[0]
        _require(all(entry[key] == original.get(key) for key in ("sha256", "bytes")),
                 "Supplement metadata differs from the original VCD manifest")
        key = (test, seed)
        _require(key in raw_rows and key in saved_rows, "Supplemental run is absent from the sealed report")
        actual, saved = raw_rows[key], saved_rows[key]
        original_path = original["original_path"]
        _require(actual.get("status") == saved.get("status") == "FAIL" and saved.get("waveform") is None
                 and actual.get("waveform_file") == saved.get("waveform_original_path") == original_path
                 and saved.get("waveform_sha256") == entry["sha256"], "Supplement differs from the failed run's recorded waveform")
        command = actual.get("command") or []
        _require(command and command[0] == raw.get("compiled_binary", {}).get("path")
                 and command.count(f"+UVM_TESTNAME={test}") == 1
                 and command.count(f"+verilator+seed+{seed}") == 1 and command.count("+TRACE") == 1
                 and command.count("+VCD_FILE=" + original_path) == 1,
                 "Recorded execution command does not match the supplemental run")
        log_entries = by_bundled.get(saved.get("transcript"), [])
        _require(len(log_entries) == 1 and log_entries[0].get("role") == "simulation_log"
                 and log_entries[0].get("original_path") == actual.get("log"),
                 "Supplemental run transcript identity differs from the original manifest")
        _verified_file(base, saved["transcript"], log_entries[0])
        path = _verified_file(base, relative, original)
        result[run_id] = {"url": path.relative_to(root).as_posix(), "sha256": entry["sha256"], "bytes": entry["bytes"]}
    return result
