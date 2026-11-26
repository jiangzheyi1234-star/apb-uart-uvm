#!/usr/bin/env python3
"""Package and decode the measured controller-only synthesis/STA/scan evidence.

Regenerate from the repository root (fresh --out directory required):
  python py/frontend_evidence.py --report results/frontend_controller_final/report.json \
      --repeat results/frontend_controller_repeat/report.json --out docs/frontend
Validate an existing bundle:
  python py/frontend_evidence.py --check docs/frontend

No simulations are run. Original raw records and their status are retained.
The public dashboard API is frontend_data(base, root) -> checks, waves, inputs.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil

from waveform_data import apb_transactions, binary_value

ROOT = Path(__file__).resolve().parents[1]
SECTIONS = ("source_snapshot", "synthesis", "gate_simulation", "sta", "scan")
REPEAT_IDENTICAL = ("mapped.v", "scan_mapped.v", "scan_chain.json", "controller.sdc", "cells.v")
CURATED = (
    "synthesis.log", "synthesis_statistics.txt", "sta.log", "gate_simulation.log",
    "controller.sdc", "controller_sta.tcl", "scan_chain.json", "gate_smoke.vcd",
    "mapped.v", "scan_mapped.v", "cells.v", "NANGATE_LICENSE", "apb_ram_mbist.sv",
    "gate_smoke.sv", "scan_capture.vh", "run_flow.py", "toolchain.lock.json",
    "version_yosys.log", "version_opensta.log", "version_iverilog.log",
)
REPEAT_CURATED = ("synthesis.log", "synthesis_statistics.txt", "sta.log", "gate_simulation.log")
TOP_SIGNALS = {
    "CLK": ("apb.clk", "CLK"), "RSTN": ("apb.rst_n", "RSTN"),
    "PADDR": ("apb.paddr", "PADDR"), "PWDATA": ("apb.pwdata", "PWDATA"),
    "PWRITE": ("apb.pwrite", "PWRITE"), "PSEL": ("apb.psel", "PSEL"),
    "PENABLE": ("apb.penable", "PENABLE"), "q0": ("apb.prdata", "PRDATA · RTL"),
    "q1": ("gate.prdata", "PRDATA · mapped"), "q2": ("scan_gate.prdata", "PRDATA · scan"),
    "ready0": ("apb.pready", "PREADY"), "err0": ("apb.pslverr", "PSLVERR"),
    "en0": ("ram.en", "RAM_EN"), "we0": ("ram.we", "RAM_WE"),
    "a0": ("ram.addr", "RAM_ADDR"), "d0": ("ram.wdata", "RAM_WDATA"),
    "r0": ("ram.rdata", "RAM_RDATA"),
    "SCAN_EN": ("scan.en", "SCAN_EN"), "SCAN_IN": ("scan.in", "SCAN_IN"),
    "SCAN_OUT": ("scan.out", "SCAN_OUT"),
    "capture_checks": ("scan.capture_checks", "capture_checks"),
    "comparisons": ("metric.comparisons", "comparisons"),
    "transactions": ("metric.transactions", "transactions"),
    "scan_checks": ("metric.scan_checks", "scan_checks"),
    "native_ops": ("metric.native_ops", "native_ops"),
    "native_reads": ("metric.native_reads", "native_reads"),
    "native_writes": ("metric.native_writes", "native_writes"),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(part)
    return value.hexdigest()


def read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"Expected an evidence object: {path.name}")
    return value


def relative_file(base: Path, name: str) -> Path:
    require(isinstance(name, str) and name and "\\" not in name and ":" not in name,
            "Evidence paths must be relative POSIX paths")
    parts = name.split("/")
    require(not PurePosixPath(name).is_absolute() and all(part not in ("", ".", "..") for part in parts),
            "Unsafe frontend evidence path")
    target = (base / name).resolve()
    require(target.is_relative_to(base.resolve()) and target.is_file(), "Missing or escaping frontend evidence input")
    return target


def metadata(path: Path, relative: str) -> dict:
    return {"path": relative, "sha256": digest(path), "bytes": path.stat().st_size}


def public_text(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    # Source authors' public copyright/contact notices are retained. Local user
    # paths and token formats are not needed by any of these EDA artifacts.
    require(not re.search(r"(?i)(?:(?<![a-z0-9])[a-z]:[\\/]|/mnt/[a-z]/|/home/|/Users/|Bearer\s+[A-Za-z0-9]|gh[pousr]_[A-Za-z0-9]{15}|github_pat_[A-Za-z0-9])", text),
            f"Artifact contains a private path or credential pattern: {path.name}")


def primary_artifacts(report: dict) -> tuple[str, ...]:
    if any(source["path"] == "scripts/frontend/hold_repair.py" for source in report["source_snapshot"]):
        return (*CURATED, "hold_repair.py")
    return CURATED


def verify_run(path: Path, *, current_sources: bool) -> tuple[dict, dict]:
    report = read(path)
    require(report.get("status") == "TIMING_VIOLATION" and report.get("execution_status") == "PASS",
            "Expected measured execution with its original timing violation retained")
    require(report.get("top") == "apb_ram_mbist" and report.get("processes")
            and all(item.get("returncode") == 0 for item in report["processes"]), "A required real EDA process failed")
    artifacts = {}
    for item in report["artifacts"]:
        name = item.get("path")
        require(name not in artifacts, "Duplicate original artifact identity")
        artifact = relative_file(path.parent, name)
        require(digest(artifact) == item.get("sha256") and artifact.stat().st_size == item.get("bytes"),
                "Original frontend artifact changed: " + name)
        artifacts[name] = item
    require(all(name in artifacts for name in primary_artifacts(report)), "Original frontend evidence is incomplete")
    for source in report["source_snapshot"]:
        archived = relative_file(path.parent, Path(source["path"]).name)
        require(digest(archived) == source["sha256"] and archived.stat().st_size == source["bytes"],
                "Captured source differs from its build-time snapshot")
        if current_sources:
            current = relative_file(ROOT, source["path"])
            require(digest(current) == source["sha256"] and current.stat().st_size == source["bytes"],
                    "Current source/tool differs from measured source: " + source["path"])
    validate_measurements(report, path.parent)
    return report, artifacts


def validate_measurements(report: dict, directory: Path) -> None:
    """Recount source records, without accepting arbitrary report PASS fields."""
    synthesis = report["synthesis"]
    require(sum(synthesis["cells"].values()) == synthesis["cell_count"]
            and sum(value for key, value in synthesis["cells"].items() if key.startswith("DFF")) == synthesis["sequential_cells"],
            "Mapped cell counts are inconsistent")
    stats = (directory / "synthesis_statistics.txt").read_text()
    number = re.search(r"Number of cells:\s*(\d+)", stats)
    area = re.search(r"Chip area for module.*?:\s*([0-9.]+)", stats)
    require(number and int(number[1]) == synthesis["cell_count"] and area and float(area[1]) == synthesis["area_um2"],
            "Synthesis summary differs from its actual statistics")
    parsed_cells = Counter()
    for kind, count in re.findall(r"^\s+([A-Z][A-Z0-9_]+)\s+(\d+)\s*$", stats, re.MULTILINE):
        parsed_cells[kind] += int(count)
    require(dict(parsed_cells) == synthesis["cells"], "Per-cell statistics differ")
    gate_log = (directory / "gate_simulation.log").read_text()
    matches = re.findall(r"^FRONTEND_GATE_PASS comparisons=(\d+) apb_transactions=(\d+) scan_length=(\d+) scan_bits_checked=(\d+) capture_bits_checked=(\d+)$", gate_log, re.MULTILINE)
    require(len(matches) == 1 and not re.search(r"FATAL:|ERROR:", gate_log), "Missing or failed real gate completion")
    comparisons, transactions, length, shifted, captured = map(int, matches[0])
    gate, scan = report["gate_simulation"], report["scan"]
    require(gate.get("status") == scan.get("status") == "PASS"
            and (comparisons, transactions) == (gate["comparisons"], gate["apb_transactions"])
            and (length, shifted, captured) == (scan["length"], scan["bits_checked"], scan["capture_bits_checked"])
            and shifted == 4 * length and captured == 32, "Gate/scan evidence counts differ")
    require("GATE_CLEAN_MBIST native_ops=640 reads=320 writes=320" in gate_log
            and gate.get("clean_march_native_operations") == 640
            and "GATE_FAULT_MBIST addr=63 step=2 expected=ffffffff actual=fffffff7" in gate_log
            and "SCAN_CAPTURE_PASS checked_bits=32 independently_expected=fffffff7" in gate_log,
            "Clean/fault/capture observations are incomplete")
    chain = read(directory / "scan_chain.json")
    require(all(chain.get(key) == scan.get(key) for key in chain), "Scan chain differs from executed metadata")
    require(chain.get("chains") == 1 and chain.get("length") == len(chain.get("cells", [])) == synthesis["sequential_cells"],
            "The scan chain omits or duplicates mapped flops")
    require([entry.get("index") for entry in chain["cells"]] == list(range(length))
            and len({entry["instance"] for entry in chain["cells"]}) == length
            and all(entry["scan_cell"] == "S" + entry["original_cell"] for entry in chain["cells"]),
            "Scan order/cell replacement is inconsistent")
    timing = (directory / "sta.log").read_text()
    setup = re.findall(r"^worst slack max\s+(-?[0-9.]+)$", timing, re.MULTILINE)
    hold = re.findall(r"^worst slack min\s+(-?[0-9.]+)$", timing, re.MULTILINE)
    require(len(setup) == len(hold) == 1 and "FRONTEND_STA_COMPLETE" in timing
            and not re.search(r"^Error:", timing, re.MULTILINE), "STA did not complete normally")
    sta = report["sta"]
    require(sta["status"] == "VIOLATED" and float(setup[0]) == sta["setup_worst_slack_ns"]
            and float(hold[0]) == sta["hold_worst_slack_ns"] < 0, "The measured hold violation was altered")


def package(report_path: Path, repeat_path: Path, output: Path) -> None:
    require(not output.exists() or output.is_dir() and not any(output.iterdir()), "Output must be new or empty")
    original, identities = verify_run(report_path.resolve(), current_sources=True)
    repeated, repeated_identities = verify_run(repeat_path.resolve(), current_sources=True)
    require(all(original[key] == repeated[key] for key in SECTIONS), "Independent executions disagree")
    require(all(original[key] == repeated[key] for key in ("versions", "toolchain_lock", "sta_binary_sha256")),
            "Independent executions use different tool identities")
    equality = []
    for name in REPEAT_IDENTICAL:
        require(identities[name] == repeated_identities[name], "Repeated artifact identity differs: " + name)
        equality.append(identities[name])
    for path in (report_path, repeat_path):
        public_text(path)
    primary = primary_artifacts(original)
    for name in primary:
        public_text(report_path.parent / name)
    for name in REPEAT_CURATED:
        public_text(repeat_path.parent / name)
    output.mkdir(parents=True, exist_ok=True)
    inputs = []

    def copy(source, name):
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        require(digest(target) == digest(source), "Evidence copy changed bytes")
        inputs.append(metadata(target, name))

    for name in primary:
        copy(report_path.parent / name, "inputs/" + name)
    for name in REPEAT_CURATED:
        copy(repeat_path.parent / name, "repeat/" + name)
    copy(report_path, "inputs/original_report.json")
    copy(repeat_path, "repeat/original_report.json")
    normalized = {"schema_version": 1, "status": original["status"], "execution_status": original["execution_status"],
                  "generated_utc": datetime.now(timezone.utc).isoformat(), "top": original["top"], "scope": original["scope"],
                  "versions": original["versions"], "source_snapshot": original["source_snapshot"],
                  "toolchain_lock": original["toolchain_lock"], "sta_binary_sha256": original["sta_binary_sha256"],
                  **{key: original[key] for key in ("synthesis", "sta", "gate_simulation", "scan")},
                  "original_report": "inputs/original_report.json", "repeat_report": "repeat/original_report.json",
                  "repeat": {"status": "MATCH", "sections": list(SECTIONS), "byte_identical_artifacts": equality},
                  "limitations": [*original["limitations"], "External RAM accesses are inhibited by the bench during SCAN_EN; production RAM isolation is not qualified."],
                  "provenance": {"original_report_sha256": digest(report_path), "repeat_report_sha256": digest(repeat_path),
                                 "publisher": "py/frontend_evidence.py", "publisher_sha256": digest(Path(__file__))}}
    (output / "report.json").write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    inputs.append(metadata(output / "report.json", "report.json"))
    (output / "inputs.json").write_text(json.dumps(inputs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    # Validate the portable form immediately, including decoding the real VCD.
    frontend_data(output, output.parent)


def decode_vcd(path: Path) -> dict:
    """Select named top-level samples, preserve X/Z, normalize ps to real ns."""
    signals, selected, scope = {}, {}, []
    scale_text, in_scale, scale = "", False, None
    header, timestamp, last_tick = True, 0.0, 0
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if header:
            if line.startswith("$timescale"):
                in_scale, scale_text = True, line
            elif in_scale:
                scale_text += " " + line
            if in_scale and "$end" in scale_text:
                found = re.fullmatch(r"\$timescale\s+(\d+)\s*(s|ms|us|ns|ps|fs)\s+\$end", scale_text)
                require(found is not None, "Unsupported frontend VCD timescale")
                scale = int(found[1]) * {"s": 1e9, "ms": 1e6, "us": 1e3, "ns": 1, "ps": .001, "fs": .000001}[found[2]]
                in_scale = False
            if line.startswith("$scope"):
                scope.append(line.split()[2])
            elif line.startswith("$upscope"):
                require(bool(scope), "Unbalanced frontend VCD scope")
                scope.pop()
            elif line.startswith("$var"):
                fields = line.split()
                if scope == ["frontend_gate_smoke"] and fields[4] in TOP_SIGNALS:
                    name, label = TOP_SIGNALS[fields[4]]
                    require(name not in signals and 1 <= int(fields[2]) <= 64, "Duplicate or invalid frontend signal")
                    signals[name] = {"id": name, "label": label, "width": int(fields[2]), "events": [],
                                     "source_name": "frontend_gate_smoke." + fields[4]}
                    selected.setdefault(fields[3], []).append(name)
            elif line.startswith("$enddefinitions"):
                require(scale is not None and scale > 0, "Frontend VCD has no timescale")
                header = False
            continue
        if line.startswith("#"):
            tick = int(line[1:])
            require(tick >= last_tick, "Non-monotonic frontend VCD timestamp")
            last_tick, timestamp = tick, round(tick * scale, 9)
            continue
        if line.startswith(("b", "B")):
            fields = line[1:].split()
            if len(fields) != 2:
                continue
            value, code = fields
        elif line[:1].lower() in ("0", "1", "x", "z"):
            value, code = line[0], line[1:]
        else:
            continue
        for name in selected.get(code, []):
            signal = signals[name]
            normalized = binary_value(value, signal["width"])
            events = signal["events"]
            if events and events[-1][0] == timestamp:
                events[-1][1] = normalized
            elif not events or events[-1][1] != normalized:
                events.append([timestamp, normalized])
    require(not header and timestamp > 0 and all(name in signals for name in ("apb.clk", "apb.rst_n", "scan.en", "scan.in", "scan.out", "scan.capture_checks")),
            "Frontend waveform lacks actual APB/scan samples")
    require(sum(len(signal["events"]) for signal in signals.values()) <= 100_000, "Frontend trace exceeds its bounded sample size")
    return {"range": [0.0, timestamp], "signals": signals}


def _waveforms(base: Path, root: Path, report: dict) -> list[dict]:
    vcd = relative_file(base, "inputs/gate_smoke.vcd")
    decoded = decode_vcd(vcd)
    signals = decoded["signals"]
    metrics = {"metric.comparisons": report["gate_simulation"]["comparisons"],
               "metric.transactions": report["gate_simulation"]["apb_transactions"],
               "metric.scan_checks": report["scan"]["bits_checked"],
               "scan.capture_checks": report["scan"]["capture_bits_checked"],
               "metric.native_ops": 640, "metric.native_reads": 320, "metric.native_writes": 320}
    require(all(name in signals and signals[name]["events"] and int(signals[name]["events"][-1][1], 2) == value
                for name, value in metrics.items()), "VCD counters differ from the original simulator log")
    events = apb_transactions(signals)
    for event in events:
        event.pop("register", None)
    # The shared decoder is cycle based; keep any observed mismatch explicit.
    # Testbench task count remains independently recorded in the gate transcript.
    first = next((event for event in events if event.get("address") == "0x100"), None)
    require(first is not None, "No actual RAM APB transaction was decoded")
    require(len(events) == report["gate_simulation"]["apb_transactions"], "Decoded APB count differs from completed testbench accesses")
    gate_window = [max(0, first["start"] - 20), min(decoded["range"][1], first["end"] + 100)]
    source = {"url": vcd.relative_to(root).as_posix(), "sha256": digest(vcd),
              "note": "Actual top-level VCD samples from zero-delay RTL/mapped/scan differential smoke; X/Z preserved. Not SDF timing simulation."}
    gate_names = ["apb.rst_n", "apb.psel", "apb.penable", "apb.pready", "apb.pwrite", "apb.paddr",
                  "apb.pwdata", "apb.prdata", "gate.prdata", "scan_gate.prdata", "apb.pslverr",
                  "ram.en", "ram.we", "ram.addr", "ram.wdata", "ram.rdata"]
    gate = {"id": "frontend:gate-wave", "kind": "gate", "title": "控制器 RTL / mapped / scan 功能对照", "run_id": None,
            "unit": "ns", "range": decoded["range"], "default_window": gate_window,
            "signals": [signals[name] for name in gate_names], "apb_events": events, "source": source}
    enable_windows, opened = [], None
    for timestamp, value in signals["scan.en"]["events"]:
        if value == "1" and opened is None:
            opened = timestamp
        elif value == "0" and opened is not None:
            enable_windows.append([opened, timestamp])
            opened = None
    require(len(enable_windows) == 5 and opened is None, "VCD does not contain four shift patterns and the separate capture shift")
    captured = [(timestamp, int(value, 2)) for timestamp, value in signals["scan.capture_checks"]["events"]
                if set(value).issubset({"0", "1"}) and int(value, 2) > 0]
    require(len(captured) == 32 and [value for _, value in captured] == list(range(1, 33)), "Actual capture check progression differs")
    require(all(enable_windows[-1][0] <= timestamp <= enable_windows[-1][1] for timestamp, _ in captured),
            "Capture counter changed outside its actual shift interval")
    source_chain = read(base / "inputs/scan_chain.json")["cells"]
    captured_cells = [entry for entry in reversed(source_chain) if re.fullmatch(r"actual_q\[\d+\]", entry["q"])]
    require(len(captured_cells) == 32, "Capture scan chain does not contain all 32 response bits")
    output_events = signals["scan.out"]["events"]
    output_times = [timestamp for timestamp, _ in output_events]
    sample_checks = []
    for (timestamp, count), entry in zip(captured, captured_cells):
        index = bisect_right(output_times, timestamp) - 1
        require(index >= 0, "No actual scan output sample at a capture check")
        register_bit = int(re.fullmatch(r"actual_q\[(\d+)\]", entry["q"])[1])
        expected = str((0xfffffff7 >> register_bit) & 1)
        observed = output_events[index][1]
        require(observed == expected, "Real scan output differs from the independently expected captured response")
        sample_checks.append({"time": timestamp, "chain_index": entry["index"], "register_bit": register_bit,
                              "check_count": count, "expected": expected, "observed": observed})
    scan_clock = {**signals["apb.clk"], "id": "scan.clk", "label": "CLK"}
    scan_window = [max(enable_windows[-1][0], captured[0][0] - 15), min(decoded["range"][1], captured[-1][0] + 25)]
    scan = {"id": "frontend:scan-wave", "kind": "scan", "title": "58 位扫描链与故障响应移出", "run_id": None,
            "unit": "ns", "range": decoded["range"], "default_window": scan_window,
            "signals": [scan_clock, signals["apb.rst_n"], signals["scan.en"], signals["scan.in"], signals["scan.out"], signals["scan.capture_checks"]],
            "apb_events": [], "source": source, "scan_windows": enable_windows,
            "capture": {"shift_interval": enable_windows[-1], "checked_interval": [captured[0][0], captured[-1][0]],
                        "checked_bits": 32, "chain_length": report["scan"]["length"], "independent_expected": "0xfffffff7",
                        "sample_checks": sample_checks}}
    return [gate, scan]


def frontend_data(base: Path, root: Path) -> tuple[list[dict], list[dict], list[dict]]:
    """Strict optional reader; missing bundles return three empty lists."""
    base, root = base.resolve(), root.resolve()
    if not (base / "report.json").exists():
        return [], [], []
    require(base.is_relative_to(root), "Frontend bundle must be within the dashboard evidence root")
    manifest_path = relative_file(base, "inputs.json")
    manifest = json.loads(manifest_path.read_text())
    require(isinstance(manifest, list) and bool(manifest), "Frontend inputs manifest is empty")
    inputs, seen = [], set()
    for item in manifest:
        require(item.get("path") not in seen, "Duplicate public frontend input")
        seen.add(item["path"])
        path = relative_file(base, item["path"])
        require(digest(path) == item.get("sha256") and path.stat().st_size == item.get("bytes"), "Public frontend artifact changed")
        inputs.append(metadata(path, path.relative_to(root).as_posix()))
    inputs.append(metadata(manifest_path, manifest_path.relative_to(root).as_posix()))
    require("report.json" in seen, "Frontend normalized report is not hash-bound")
    report = read(base / "report.json")
    original = read(relative_file(base, report["original_report"]))
    repeated = read(relative_file(base, report["repeat_report"]))
    require(digest(relative_file(base, report["original_report"])) == report["provenance"]["original_report_sha256"]
            and digest(relative_file(base, report["repeat_report"])) == report["provenance"]["repeat_report_sha256"], "Original report provenance differs")
    require(report["status"] == original["status"] == repeated["status"] == "TIMING_VIOLATION"
            and report["execution_status"] == original["execution_status"] == repeated["execution_status"] == "PASS"
            and all(report[key] == original[key] == repeated[key] for key in SECTIONS), "Frontend repeat/status/source measurements differ")
    require(all(report[key] == original[key] == repeated[key] for key in ("versions", "toolchain_lock", "sta_binary_sha256")),
            "Published frontend tool identities differ from their original executions")
    for raw, directory in ((original, "inputs"), (repeated, "repeat")):
        require(all(process["returncode"] == 0 for process in raw["processes"]), "Original EDA execution has a failed process")
        records = {item["path"]: item for item in raw["artifacts"]}
        names = primary_artifacts(raw) if directory == "inputs" else REPEAT_CURATED
        for name in names:
            artifact = relative_file(base, directory + "/" + name)
            require(digest(artifact) == records[name]["sha256"] and artifact.stat().st_size == records[name]["bytes"], "Public artifact differs from its original execution")
    validate_measurements(original, base / "inputs")
    # Repeat logs/statistics are rechecked using the shared chain copy, whose
    # identical digest is independently recorded by both original executions.
    require(all(original["artifacts"] and next(item for item in original["artifacts"] if item["path"] == name)
                == next(item for item in repeated["artifacts"] if item["path"] == name) for name in REPEAT_IDENTICAL), "Repeat netlist/source hashes differ")
    require(report["repeat"]["status"] == "MATCH" and report["repeat"]["sections"] == list(SECTIONS)
            and report["repeat"]["byte_identical_artifacts"] == [next(item for item in original["artifacts"] if item["path"] == name) for name in REPEAT_IDENTICAL],
            "Normalized repeat provenance differs from original identities")
    # Re-read repeated numeric observations from its own independent logs.
    for name, expression in (
        ("gate_simulation.log", r"^(?:GATE_CLEAN_MBIST|GATE_FAULT_MBIST|SCAN_CAPTURE_PASS|FRONTEND_GATE_PASS).*$"),
        ("sta.log", r"^worst slack (?:max|min)\s+-?[0-9.]+$"),
        ("synthesis_statistics.txt", r"^.*(?:Number of cells:|Chip area for module).*$"),
    ):
        first = re.findall(expression, (base / "inputs" / name).read_text(), re.MULTILINE)
        second = re.findall(expression, (base / "repeat" / name).read_text(), re.MULTILINE)
        require(first and first == second, "Independent repeated log observations differ")
    for source in original["source_snapshot"]:
        path = relative_file(base / "inputs", Path(source["path"]).name)
        require(digest(path) == source["sha256"] and path.stat().st_size == source["bytes"], "Bundled frontend source identity differs")
    def url(name):
        return relative_file(base, name).relative_to(root).as_posix()
    def link(label, name):
        return {"label": label, "url": url(name)}
    synthesis, sta, gate, scan = (report[key] for key in ("synthesis", "sta", "gate_simulation", "scan"))
    checks = [
        {"id": "frontend:synthesis", "title": "控制器标准单元综合", "status": "PASS",
         "summary": f"{synthesis['cell_count']} 个单元、{synthesis['sequential_cells']} 个触发器；面积 {synthesis['area_um2']:.3f} µm²。外部 64×32 RAM 不计入面积。",
         "artifacts": [link("综合统计", "inputs/synthesis_statistics.txt"), link("完整综合日志", "inputs/synthesis.log"), link("映射网表", "inputs/mapped.v")]},
        {"id": "frontend:sta", "title": "控制器静态时序", "status": "TIMING_VIOLATION",
         "summary": f"Setup {sta['setup_worst_slack_ns']:+.5f} ns；hold {sta['hold_worst_slack_ns']:+.5f} ns。10 ns 时钟，保留 hold 违例；单典型角、布局前、外部 RAM 时序预算。",
         "artifacts": [link("完整 max/min 路径", "inputs/sta.log"), link("实际 SDC 约束", "inputs/controller.sdc"), link("实测报告", "report.json")]},
        {"id": "frontend:gate", "title": "RTL 与门级功能对照", "status": "PASS",
         "summary": f"{gate['comparisons']:,} 个周期、{gate['apb_transactions']} 次 APB 事务匹配；干净 March 为 640 次操作。零延时功能比较，不是 SDF 时序仿真。",
         "artifacts": [link("真实仿真日志", "inputs/gate_simulation.log"), link("原始 VCD", "inputs/gate_smoke.vcd")], "waveform_id": "frontend:gate-wave"},
        {"id": "frontend:scan", "title": "标准单元扫描链", "status": "PASS",
         "summary": f"1 条 {scan['length']} 位链；4 个模式检查 {scan['bits_checked']} 位；另将 {scan['capture_bits_checked']} 个实际捕获位与 0xfffffff7 对照。没有 ATPG 或故障覆盖率结论。",
         "artifacts": [link("真实链顺序", "inputs/scan_chain.json"), link("扫描网表", "inputs/scan_mapped.v"), link("capture / shift 日志", "inputs/gate_simulation.log")], "waveform_id": "frontend:scan-wave"},
    ]
    return checks, _waveforms(base, root, report), inputs


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--report", type=Path)
    p.add_argument("--repeat", type=Path)
    p.add_argument("--out", type=Path)
    p.add_argument("--check", type=Path)
    a = p.parse_args()
    if a.check:
        checks, waves, inputs = frontend_data(a.check, a.check.parent)
        require(bool(checks), "No frontend bundle exists")
        print(json.dumps({"checks": len(checks), "waves": len(waves), "inputs": len(inputs),
                          "bytes": sum(item["bytes"] for item in inputs)}, ensure_ascii=False))
        return
    require(a.report is not None and a.repeat is not None and a.out is not None, "--report, --repeat and --out are required")
    package(a.report, a.repeat, a.out)
    print("PACKAGED", a.out)


if __name__ == "__main__":
    main()
