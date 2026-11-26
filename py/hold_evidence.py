#!/usr/bin/env python3
"""Publish and audit a measured single-buffer hold ECO against a sealed baseline.

No EDA process is executed. This reader keeps the original timing violation,
verifies same-run pre/post netlists and constraints, and reuses frontend_evidence
for baseline validation and gate/scan VCD decoding.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import re
import shutil

import frontend_evidence as frontend

ROOT = Path(__file__).resolve().parents[1]
EXTRA = ("baseline_mapped.v", "baseline_sta.log", "baseline_synthesis_statistics.txt", "hold_eco.json",
         "timing_paths.json", "baseline_min_path.txt", "baseline_max_path.txt", "fixed_min_path.txt",
         "fixed_max_path.txt", "fixed_target_min_path.txt", "hold_eco_check.log", "hold_eco_check.ys")
SHARED_SOURCE = ("rtl_subsystem/apb_ram_mbist.sv", "flow/frontend/controller.sdc", "flow/frontend/toolchain.lock.json")
MEASUREMENTS = ("synthesis", "sta", "gate_simulation", "scan", "hold_eco", "baseline")
REPEATED_FILES = ("sta.log", "baseline_sta.log", "gate_simulation.log", "hold_eco.json", "timing_paths.json")
IDENTICAL_FILES = ("mapped.v", "scan_mapped.v", "scan_chain.json", "controller.sdc", "cells.v", "hold_eco.json", "timing_paths.json")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sta_paths(text: str) -> list[dict]:
    result = []
    for block in re.split(r"(?m)(?=^Startpoint:)", text):
        if not block.startswith("Startpoint:") or "Path Type: min" not in block:
            continue
        start = re.search(r"(?m)^Startpoint:\s+(\S+)", block)
        end = re.search(r"(?m)^Endpoint:\s+(\S+)", block)
        slack = re.search(r"(?m)^\s*(-?[0-9.]+)\s+slack \((MET|VIOLATED)\)", block)
        arrival = re.search(r"(?m)^\s*(-?[0-9.]+)\s+data arrival time\s*$", block)
        required = re.search(r"(?m)^\s*(-?[0-9.]+)\s+data required time\s*$", block)
        if start and end and slack and arrival and required:
            # Do not append a later global summary to the final individual path.
            block = block.split("\n===", 1)[0].rstrip() + "\n"
            result.append({"startpoint": start[1], "endpoint": end[1], "slack_ns": float(slack[1]), "status": slack[2],
                           "arrival_ns": float(arrival[1]), "required_ns": float(required[1]), "text": block})
    require(bool(result), "Actual min-path details are missing")
    return sorted(result, key=lambda item: item["slack_ns"])


def timing(report: dict, text: str) -> list[dict]:
    setup = re.findall(r"(?m)^worst slack max\s+(-?[0-9.]+)$", text)
    hold = re.findall(r"(?m)^worst slack min\s+(-?[0-9.]+)$", text)
    require(len(setup) == len(hold) == 1 and "FRONTEND_STA_COMPLETE" in text
            and not re.search(r"(?m)^Error:", text), "STA did not complete normally")
    require(float(setup[0]) == report["setup_worst_slack_ns"] and float(hold[0]) == report["hold_worst_slack_ns"],
            "STA summary disagrees with its actual transcript")
    paths = sta_paths(text)
    require(abs(paths[0]["slack_ns"] - float(hold[0])) < 0.000011, "Reported worst min path differs from its global slack")
    return paths


def cells(path: Path, allowed: set[str]) -> dict:
    text = re.sub(r"//[^\n]*", "", path.read_text(encoding="utf-8"))
    found = {}
    for kind, instance, body in re.findall(r"(?ms)^\s*([A-Za-z_]\w*)\s+([A-Za-z_]\w*)\s*\((.*?)\);", text):
        if kind not in allowed:
            continue
        require(instance not in found, "Duplicate mapped instance")
        pairs = re.findall(r"\.(\w+)\s*\(\s*([^)]+?)\s*\)", body)
        require(pairs and len(pairs) == len(dict(pairs)), "Malformed mapped cell ports")
        found[instance] = {"type": kind, "ports": {pin: re.sub(r"\s+", "", net) for pin, net in pairs}}
    return found


def validate_eco(report: dict, directory: Path, original: dict, baseline: Path) -> tuple[dict, dict]:
    eco = frontend.read(directory / "hold_eco.json")
    require(report.get("hold_eco") == eco or all(report.get("hold_eco", {}).get(key) == value for key, value in eco.items()),
            "ECO manifest differs from its runner record")
    before_path, after_path = directory / "baseline_mapped.v", directory / "mapped.v"
    require(frontend.digest(before_path) == frontend.digest(baseline / "inputs/mapped.v"),
            "Fresh pre-ECO mapped logic differs from the sealed baseline")
    require(report["baseline"].get("netlist_sha256") == frontend.digest(before_path), "Fresh baseline netlist identity is inconsistent")
    require(eco.get("pre_netlist_sha256") == frontend.digest(before_path) and eco.get("post_netlist_sha256") == frontend.digest(after_path)
            and eco.get("rtl_sha256") == frontend.digest(directory / "apb_ram_mbist.sv")
            and eco.get("sdc_sha256") == frontend.digest(directory / "controller.sdc")
            and eco.get("liberty_sha256") == report["library"]["sha256"]
            and eco.get("constraints_unchanged") is True and eco.get("baseline_matches_archived") is True,
            "ECO hashes or unchanged-constraint claims differ from actual evidence")
    keys = ("target_instance", "target_pin", "logical_q", "old_net", "new_net", "buffer_instance", "buffer_cell")
    require(all(isinstance(eco.get(key), str) and re.fullmatch(r"[A-Za-z_]\w*", eco[key]) for key in keys), "ECO topology identifiers are invalid")
    require(eco["target_pin"] == "D" and eco["logical_q"] == "apb_read_pending_q" and eco["buffer_cell"] == "BUF_X1",
            "ECO does not repair the measured APB read-pending D path")
    allowed = set(original["synthesis"]["cells"]) | set(report["synthesis"]["cells"])
    before, after = cells(before_path, allowed), cells(after_path, allowed)
    target, inserted = eco["target_instance"], eco["buffer_instance"]
    require(target in before and target in after and inserted not in before and set(after) == set(before) | {inserted},
            "ECO changed more than one mapped instance")
    require(before[target]["ports"].get("Q") == eco["logical_q"] and before[target]["ports"].get("D") == eco["old_net"]
            and after[target]["ports"].get("D") == eco["new_net"], "ECO is not connected to the actual target flop")
    expected_target = {"type": before[target]["type"], "ports": {**before[target]["ports"], "D": eco["new_net"]}}
    require(after[target] == expected_target and after[inserted] == {"type": "BUF_X1", "ports": {"A": eco["old_net"], "Z": eco["new_net"]}}
            and all(after[name] == value for name, value in before.items() if name != target), "Mapped connectivity differs from the declared single-buffer repair")
    def assignments(path):
        text = re.sub(r"//[^\n]*", "", path.read_text(encoding="utf-8"))
        return sorted(re.sub(r"\s+", "", value) for value in re.findall(r"\bassign\s+([^;]+);", text))
    require(assignments(before_path) == assignments(after_path), "ECO changed mapped continuous logic")
    require(Counter(cell["type"] for cell in before.values()) == Counter(original["synthesis"]["cells"])
            and Counter(cell["type"] for cell in after.values()) == Counter(report["synthesis"]["cells"]), "Mapped instance counts disagree with synthesis measurements")
    require(report["synthesis"]["cell_count"] == original["synthesis"]["cell_count"] + 1
            and report["synthesis"]["sequential_cells"] == original["synthesis"]["sequential_cells"], "Repair cell/flip-flop deltas are inconsistent")
    return eco, {"before": frontend.digest(before_path), "after": frontend.digest(after_path)}


def validate_fixed(report: dict, directory: Path, baseline: Path) -> dict:
    baseline_report = frontend.read(baseline / "report.json")
    original = frontend.read(baseline / baseline_report["original_report"])
    require(report.get("implementation") == "hold_repair" and report.get("status") == "PASS"
            and report.get("execution_status") == "PASS" and report.get("top") == "apb_ram_mbist"
            and bool(report.get("processes")) and all(process.get("returncode") == 0 for process in report["processes"]),
            "Expected a completed, measured hold-repair execution")
    for key in ("versions", "toolchain_lock", "sta_binary_sha256", "library"):
        require(report.get(key) == original.get(key), "Hold experiment changed its pinned tool/library identity: " + key)
    old_sources = {entry["path"]: entry for entry in original["source_snapshot"]}
    new_sources = {entry["path"]: entry for entry in report["source_snapshot"]}
    for name in SHARED_SOURCE:
        require(new_sources.get(name) == old_sources.get(name), "Hold repair changed RTL, SDC or pinned library configuration")
        require(frontend.digest(directory / Path(name).name) == old_sources[name]["sha256"], "Shared captured source has changed")
    require((directory / "controller.sdc").read_bytes() == (baseline / "inputs/controller.sdc").read_bytes(), "Hold repair relaxed the original SDC")
    require(report["sta"]["clock_period_ns"] == original["sta"]["clock_period_ns"] == 10,
            "Hold comparison does not use the original 10 ns clock")
    for key in ("input_delay_max_ns", "input_delay_min_ns", "output_delay_max_ns", "output_delay_min_ns", "load_pf", "clock_uncertainty_ns", "scope"):
        require(report["sta"].get(key) == original["sta"].get(key), "Hold comparison changed physical/I-O assumptions")
    require(report["baseline"]["synthesis"] == original["synthesis"], "Fresh pre-ECO synthesis differs from the original baseline")
    before_paths = timing(report["baseline"]["sta"], (directory / "baseline_sta.log").read_text())
    require(report["baseline"]["sta"] == original["sta"] and before_paths[0]["slack_ns"] < 0,
            "Fresh baseline did not reproduce the original hold violation")
    after_paths = timing(report["sta"], (directory / "sta.log").read_text())
    require(report["sta"]["setup_worst_slack_ns"] >= 0 and report["sta"]["hold_worst_slack_ns"] >= 0,
            "Hold repair still violates a measured setup/hold check")
    eco, netlists = validate_eco(report, directory, original, baseline)
    require(before_paths[0]["endpoint"] == eco["target_instance"], "ECO does not target the actual worst min-path endpoint")
    path_records = frontend.read(directory / "timing_paths.json")
    for section, names, log_name in (("baseline", ("min",), "baseline_sta.log"),
                                     ("fixed", ("min", "target_min"), "sta.log")):
        log = (directory / log_name).read_text()
        for name in names:
            record = path_records[section][name]
            require(isinstance(record.get("text"), str) and record["text"].strip() in log,
                    "Structured min path is absent from the actual STA transcript")
            measured = sta_paths(record["text"])[0]
            require(all(measured[key] == record[key] for key in ("startpoint", "endpoint", "slack_ns", "arrival_ns", "required_ns", "status")),
                    "Structured min-path numbers differ from its recorded path")
            points = [{"delay_ns": float(delay), "time_ns": float(time), "edge": edge, "pin": pin, "cell": cell}
                      for delay, time, edge, pin, cell in re.findall(
                          r"(?m)^\s*(-?[0-9.]+)\s+(-?[0-9.]+)\s+([\^v])\s+(\S+)\s+\(([^)]+)\)\s*$", record["text"])]
            require(points == record.get("points"), "Structured path pins/delays differ from the actual STA rows")
    target_path = path_records["fixed"]["target_min"]
    for section, measured in (("baseline", before_paths[0]), ("fixed", after_paths[0])):
        require(all(path_records[section]["min"][key] == measured[key]
                    for key in ("startpoint", "endpoint", "slack_ns", "arrival_ns", "required_ns", "status")),
                "Structured global min path is not the actual worst path from its STA log")
    require(eco.get("baseline_target_path") == path_records["baseline"]["min"] and eco.get("target_path_after") == target_path
            and target_path["endpoint"] == eco["target_instance"]
            and eco.get("target_slack_after_ns") == target_path["slack_ns"]
            and eco.get("global_min_endpoint_after") == after_paths[0]["endpoint"], "ECO target and actual reported paths disagree")
    buffer_rows = [point for point in target_path["points"] if point["pin"] == eco["buffer_instance"] + "/Z" and point["cell"] == "BUF_X1"]
    require(len(buffer_rows) == 1 and buffer_rows[0]["delay_ns"] == eco.get("buffer_delay_ns"), "Inserted buffer has no matching measured delay")
    for section, name, filename in (("baseline", "min", "baseline_min_path.txt"), ("baseline", "max", "baseline_max_path.txt"),
                                    ("fixed", "min", "fixed_min_path.txt"), ("fixed", "max", "fixed_max_path.txt"),
                                    ("fixed", "target_min", "fixed_target_min_path.txt")):
        require((directory / filename).read_text().strip() == path_records[section][name]["text"].strip(), "Curated path text differs from its structured STA record")
    check_log = (directory / "hold_eco_check.log").read_text()
    require("Found and reported 0 problems" in check_log and not re.search(r"(?m)^ERROR:", check_log), "Repaired netlist failed actual Yosys checking")
    stats = (directory / "synthesis_statistics.txt").read_text()
    count = re.search(r"Number of cells:\s*(\d+)", stats)
    area = re.search(r"Chip area for module.*?:\s*([0-9.]+)", stats)
    require(count and int(count[1]) == report["synthesis"]["cell_count"] and area and float(area[1]) == report["synthesis"]["area_um2"],
            "Post-ECO synthesis statistics differ from the report")
    gate = (directory / "gate_simulation.log").read_text()
    matches = re.findall(r"(?m)^FRONTEND_GATE_PASS comparisons=(\d+) apb_transactions=(\d+) scan_length=(\d+) scan_bits_checked=(\d+) capture_bits_checked=(\d+)$", gate)
    require(len(matches) == 1 and not re.search(r"FATAL:|ERROR:", gate), "Post-ECO gate/scan test did not complete normally")
    comparisons, transactions, length, shifted, captured = map(int, matches[0])
    require(report["gate_simulation"]["status"] == report["scan"]["status"] == "PASS"
            and (comparisons, transactions) == (report["gate_simulation"]["comparisons"], report["gate_simulation"]["apb_transactions"])
            and (length, shifted, captured) == (report["scan"]["length"], report["scan"]["bits_checked"], report["scan"]["capture_bits_checked"])
            and shifted == 4 * length and captured == 32, "Post-ECO gate/scan counters disagree")
    require("GATE_CLEAN_MBIST native_ops=640 reads=320 writes=320" in gate
            and "GATE_FAULT_MBIST addr=63 step=2 expected=ffffffff actual=fffffff7" in gate
            and "SCAN_CAPTURE_PASS checked_bits=32 independently_expected=fffffff7" in gate,
            "Post-ECO functional or capture observations are incomplete")
    chain = frontend.read(directory / "scan_chain.json")
    require(all(chain.get(key) == report["scan"].get(key) for key in chain)
            and chain["length"] == report["synthesis"]["sequential_cells"], "Post-ECO scan chain differs from the executed chain")
    return {"before_path": before_paths[0], "after_path": after_paths[0], "target_path": target_path,
            "timing_paths": path_records, "netlists": netlists, "eco": eco}


def manifest_inputs(base: Path, root: Path) -> list[dict]:
    path = frontend.relative_file(base, "inputs.json")
    entries = json.loads(path.read_text())
    require(isinstance(entries, list) and entries, "Hold input manifest is empty")
    result, seen = [], set()
    for entry in entries:
        require(entry.get("path") not in seen, "Duplicate hold evidence input")
        seen.add(entry["path"])
        source = frontend.relative_file(base, entry["path"])
        require(frontend.digest(source) == entry.get("sha256") and source.stat().st_size == entry.get("bytes"), "Hold evidence input was changed")
        result.append(frontend.metadata(source, source.relative_to(root).as_posix()))
    require("report.json" in seen and "inputs/original_report.json" in seen, "Hold reports are not hash-bound")
    result.append(frontend.metadata(path, path.relative_to(root).as_posix()))
    return result


def hold_data(base: Path, root: Path, baseline: Path) -> tuple[dict, list[dict], list[dict]]:
    """Optional audited comparison; no bundle returns ({}, [], [])."""
    base, root, baseline = base.resolve(), root.resolve(), baseline.resolve()
    if not (base / "report.json").exists():
        return {}, [], []
    require(base.is_relative_to(root) and baseline.is_relative_to(root), "Hold comparison evidence escapes its URL root")
    frontend.frontend_data(baseline, root)
    inputs = manifest_inputs(base, root)
    report = frontend.read(base / "report.json")
    original_path = frontend.relative_file(base, report["original_report"])
    raw = frontend.read(original_path)
    require(frontend.digest(original_path) == report["provenance"]["raw_report_sha256"]
            and frontend.digest(baseline / "report.json") == report["provenance"]["baseline_report_sha256"], "Hold report provenance differs")
    for key in ("status", "execution_status", "implementation", *MEASUREMENTS):
        require(report.get(key) == raw.get(key), "Published hold result differs from its raw execution record")
    records = {item["path"]: item for item in raw["artifacts"]}
    manifest = json.loads((base / "inputs.json").read_text())
    names = {entry["path"] for entry in manifest}
    curated = set(frontend.CURATED) | set(EXTRA) | {Path(source["path"]).name for source in raw["source_snapshot"]}
    require({"inputs/" + name for name in curated} | {"before_min_path.txt", "after_min_path.txt"} <= names,
            "Required hold artifacts are not all bound by the public manifest")
    require(len(records) == len(raw["artifacts"]), "Duplicate raw hold artifact")
    for entry in manifest:
        name = entry["path"]
        frontend.public_text(frontend.relative_file(base, name))
        if name.startswith("inputs/") and name != "inputs/original_report.json":
            relative = name[len("inputs/"):]
            require(relative in records and all(entry[key] == records[relative][key] for key in ("sha256", "bytes")), "Published hold artifact differs from the same execution")
    for source in raw["source_snapshot"]:
        path = frontend.relative_file(base, "inputs/" + Path(source["path"]).name)
        require(frontend.digest(path) == source["sha256"] and path.stat().st_size == source["bytes"], "Captured hold source differs from the executed snapshot")
    if report.get("repeat"):
        repeat = report["repeat"]
        path = frontend.relative_file(base, "repeat/original_report.json")
        repeated = frontend.read(path)
        require(repeat.get("status") == "MATCH" and frontend.digest(path) == repeat.get("raw_report_sha256")
                and all(repeated.get(key) == raw.get(key) for key in (*MEASUREMENTS, "status", "execution_status", "implementation", "versions", "toolchain_lock", "sta_binary_sha256", "source_snapshot")),
                "Independent fixed execution disagrees with its published comparison")
        repeat_records = {entry["path"]: entry for entry in repeated["artifacts"]}
        require(repeat.get("byte_identical_artifacts") == [records[name] for name in IDENTICAL_FILES]
                and all(records[name] == repeat_records[name] for name in IDENTICAL_FILES), "Fixed repeat netlist/source identities differ")
        for name in REPEATED_FILES:
            relative = "repeat/" + name
            require(relative in names, "Independent fixed evidence is not hash-bound")
            path = frontend.relative_file(base, relative)
            require(frontend.digest(path) == repeat_records[name]["sha256"] and path.stat().st_size == repeat_records[name]["bytes"], "Fixed repeat artifact differs from its execution")
        timing(repeated["sta"], (base / "repeat/sta.log").read_text())
        timing(repeated["baseline"]["sta"], (base / "repeat/baseline_sta.log").read_text())
        require(frontend.read(base / "repeat/hold_eco.json") == repeated["hold_eco"], "Repeated ECO manifest differs")
        expression = r"(?m)^(?:GATE_CLEAN_MBIST|GATE_FAULT_MBIST|SCAN_CAPTURE_PASS|FRONTEND_GATE_PASS).*$"
        require(re.findall(expression, (base / "repeat/gate_simulation.log").read_text()) == re.findall(expression, (base / "inputs/gate_simulation.log").read_text()),
                "Independent fixed gate observations differ")
    if report.get("fresh_baseline"):
        fresh = report["fresh_baseline"]
        path = frontend.relative_file(base, "fresh_baseline/original_report.json")
        measured = frontend.read(path)
        old = frontend.read(baseline / "report.json")
        require(frontend.digest(path) == fresh.get("raw_report_sha256") and measured.get("status") == "TIMING_VIOLATION"
                and measured.get("execution_status") == "PASS"
                and all(measured.get(key) == old.get(key) for key in ("synthesis", "sta", "gate_simulation", "scan", "versions", "toolchain_lock", "sta_binary_sha256")),
                "Fresh unmodified baseline does not reproduce the original measurement")
        fresh_records = {entry["path"]: entry for entry in measured["artifacts"]}
        require(fresh.get("mapped_sha256") == fresh_records["mapped.v"]["sha256"] == records["baseline_mapped.v"]["sha256"], "Fresh baseline mapping differs from the same-run pre-ECO mapping")
        for name in ("sta.log", "gate_simulation.log", "synthesis_statistics.txt"):
            path = frontend.relative_file(base, "fresh_baseline/" + name)
            require("fresh_baseline/" + name in names and frontend.digest(path) == fresh_records[name]["sha256"], "Fresh baseline artifact differs from its execution")
        timing(measured["sta"], (base / "fresh_baseline/sta.log").read_text())
    details = validate_fixed(raw, base / "inputs", baseline)
    for side in ("before", "after"):
        require((base / f"{side}_min_path.txt").read_text() == details[side + "_path"]["text"], "Derived precise min path differs from its actual STA log")
    waves = frontend._waveforms(base, root, raw)
    for wave in waves:
        wave["id"] = wave["id"].replace("frontend:", "frontend-hold:", 1)
        wave["title"] = "Hold ECO 后 · " + wave["title"]
        wave["implementation"] = "hold_repair"
    old = frontend.read(baseline / "report.json")

    def link(label, path):
        return {"label": label, "url": path.relative_to(root).as_posix()}
    def new(label, name):
        return link(label, frontend.relative_file(base, name))
    def previous(label, name):
        return link(label, frontend.relative_file(baseline, name))
    metrics = []
    for label, before, after, precision, unit in (
        ("Setup 最差余量", old["sta"]["setup_worst_slack_ns"], raw["sta"]["setup_worst_slack_ns"], 5, "ns"),
        ("Hold 最差余量", old["sta"]["hold_worst_slack_ns"], raw["sta"]["hold_worst_slack_ns"], 5, "ns"),
        ("映射单元数", old["synthesis"]["cell_count"], raw["synthesis"]["cell_count"], 0, "个"),
        ("控制器单元面积", old["synthesis"]["area_um2"], raw["synthesis"]["area_um2"], 3, "µm²"),
    ):
        signed = "余量" in label
        def formatted(value, sign=False):
            return format(value, ("+" if sign else "") + "." + str(precision) + "f") + " " + unit
        metrics.append({"label": label, "before": formatted(before, signed), "after": formatted(after, signed), "delta": formatted(after - before, True)})
    before_path, after_path, eco = details["before_path"], details["after_path"], details["eco"]
    timing_paths = []
    for path_id, title, section, name, artifact in (
        ("baseline-target", "修复前目标路径 · apb_read_pending_q", "baseline", "min", "before_min_path.txt"),
        ("repaired-target", "修复后同一目标路径 · apb_read_pending_q", "fixed", "target_min", "inputs/fixed_target_min_path.txt"),
        ("repaired-worst", "修复后全局最差 hold 路径", "fixed", "min", "after_min_path.txt"),
    ):
        # These records were re-parsed from the actual STA text above, including
        # every pin, cell, edge and reported delay. Required time is a separate
        # scalar; the points retain the source's launch-clock/data-path rows.
        record = details["timing_paths"][section][name]
        timing_paths.append({"id": path_id, "title": title,
                             **{key: record[key] for key in ("startpoint", "endpoint", "arrival_ns", "required_ns", "slack_ns", "status")},
                             "points": [{key: point[key] for key in ("pin", "cell", "edge", "time_ns", "delay_ns")}
                                        for point in record["points"]],
                             "report_url": frontend.relative_file(base, artifact).relative_to(root).as_posix()})
    require(timing_paths[0]["startpoint"] == timing_paths[1]["startpoint"]
            and timing_paths[0]["endpoint"] == timing_paths[1]["endpoint"] == eco["target_instance"],
            "The repaired target path does not retain its original launch/capture endpoints")
    model = {
        "summary": "同一控制器 RTL、原 10 ns SDC 与固定 Nangate45 典型角下，对实际最差 hold 路径实施单 BUF_X1 网表 ECO。保留两版的实际检查结果。",
        "metrics": metrics,
        "timing_paths": timing_paths,
        "stages": [
            {"id": "synthesis", "title": "标准单元映射与局部 ECO",
             "before": {"status": "PASS", "artifacts": [new("同次 ECO 前网表", "inputs/baseline_mapped.v"), previous("原归档综合统计", "inputs/synthesis_statistics.txt")]},
             "after": {"status": "PASS", "artifacts": [new("ECO 拓扑与哈希", "inputs/hold_eco.json"), new("ECO 后网表", "inputs/mapped.v"), new("实际综合统计", "inputs/synthesis_statistics.txt")]}},
            {"id": "sta", "title": "原约束下静态时序",
             "before": {"status": "TIMING_VIOLATION", "artifacts": [previous("原版完整报告", "report.json"), new("修复前精确 min 路径", "before_min_path.txt"), new("同次 ECO 前 STA", "inputs/baseline_sta.log"), previous("原归档 STA", "inputs/sta.log")]},
             "after": {"status": raw["status"], "artifacts": [new("ECO 后完整报告", "report.json"), new("修复后最差 min 路径", "after_min_path.txt"), new("完整 max/min 日志", "inputs/sta.log"), new("未改变的 10 ns SDC", "inputs/controller.sdc")]}},
            {"id": "gate", "title": "零延时 RTL / 门级对照",
             "before": {"status": old["gate_simulation"]["status"], "artifacts": [previous("原归档独立仿真日志", "inputs/gate_simulation.log")], "waveform_id": "frontend:gate-wave"},
             "after": {"status": raw["gate_simulation"]["status"], "artifacts": [new("ECO 后同次仿真日志", "inputs/gate_simulation.log"), new("ECO 后原始 VCD", "inputs/gate_smoke.vcd")], "waveform_id": "frontend-hold:gate-wave"}},
            {"id": "scan", "title": "逻辑扫描链与功能捕获",
             "before": {"status": old["scan"]["status"], "artifacts": [previous("原归档扫描链", "inputs/scan_chain.json")], "waveform_id": "frontend:scan-wave"},
             "after": {"status": raw["scan"]["status"], "artifacts": [new("ECO 后扫描链", "inputs/scan_chain.json"), new("移位 / 捕获日志", "inputs/gate_simulation.log")], "waveform_id": "frontend-hold:scan-wave"}},
        ],
        "diagnosis": [
            f"apb_read_pending_q 的修复前最差 min 路径：{before_path['startpoint']} → {before_path['endpoint']}。arrival {before_path['arrival_ns']:.5f} ns，required {before_path['required_ns']:.5f} ns，slack {before_path['slack_ns']:+.5f} ns。",
            f"在 {eco['target_instance']}/{eco['target_pin']} 前插入 {eco['buffer_cell']} {eco['buffer_instance']}：{eco['old_net']} → {eco['new_net']}。其余映射单元连接及 RTL、SDC 未改变。",
            f"该 BUF 的实测单元延时 {eco['buffer_delay_ns']:.5f} ns。原目标端点修复后 slack {eco['target_slack_after_ns']:+.5f} ns。",
            f"修复后全局最差 min 路径：{after_path['startpoint']} → {after_path['endpoint']}，slack {after_path['slack_ns']:+.5f} ns。完整路径以原始 STA 日志为准。",
            "范围为固定典型角、理想时钟、布局前单元延时及外部 RAM I/O 预算。门级采用零延时比较，扫描检查逻辑移位与捕获。尚未覆盖布局后、多角、SDF 或物理 DFT 签核。",
        ],
    }
    return model, waves, inputs


def package(report_path: Path, output: Path, baseline: Path, repeat_path: Path | None = None, fresh_path: Path | None = None) -> None:
    report_path, output, baseline = report_path.resolve(), output.resolve(), baseline.resolve()
    require(not output.exists() or output.is_dir() and not any(output.iterdir()), "Hold output must be new or empty")
    frontend.frontend_data(baseline, baseline.parent)
    raw = frontend.read(report_path)
    artifacts = {}
    for item in raw.get("artifacts", []):
        require(item["path"] not in artifacts, "Duplicate actual hold artifact")
        path = frontend.relative_file(report_path.parent, item["path"])
        require(frontend.digest(path) == item["sha256"] and path.stat().st_size == item["bytes"], "Actual hold artifact changed")
        artifacts[item["path"]] = item
    names = set(frontend.CURATED) | set(EXTRA) | {Path(source["path"]).name for source in raw.get("source_snapshot", [])}
    require(names.issubset(artifacts), "Actual hold execution is missing curated evidence")
    for source in raw["source_snapshot"]:
        path = frontend.relative_file(report_path.parent, Path(source["path"]).name)
        require(frontend.digest(path) == source["sha256"] and path.stat().st_size == source["bytes"], "Hold captured source differs from its snapshot")
        current = frontend.relative_file(ROOT, source["path"])
        require(frontend.digest(current) == source["sha256"], "Current hold source/tool differs from its measured version")
    details = validate_fixed(raw, report_path.parent, baseline)
    repeated = fresh = None
    if repeat_path:
        repeat_path = repeat_path.resolve()
        repeated = frontend.read(repeat_path)
        validate_fixed(repeated, repeat_path.parent, baseline)
        require(all(repeated.get(key) == raw.get(key) for key in (*MEASUREMENTS, "status", "execution_status", "implementation", "versions", "toolchain_lock", "sta_binary_sha256", "source_snapshot")), "Independent fixed runs disagree")
        second = {entry["path"]: entry for entry in repeated["artifacts"]}
        require(all(artifacts[name] == second[name] for name in IDENTICAL_FILES), "Independent fixed netlists differ")
        for name in REPEATED_FILES:
            path = frontend.relative_file(repeat_path.parent, name)
            require(frontend.digest(path) == second[name]["sha256"], "Independent fixed artifact changed")
            frontend.public_text(path)
        frontend.public_text(repeat_path)
    if fresh_path:
        fresh_path = fresh_path.resolve()
        fresh, _ = frontend.verify_run(fresh_path, current_sources=True)
        old = frontend.read(baseline / "report.json")
        require(all(fresh.get(key) == old.get(key) for key in ("synthesis", "sta", "gate_simulation", "scan", "versions", "toolchain_lock", "sta_binary_sha256")), "Fresh unmodified baseline differs from the original result")
        require(frontend.digest(fresh_path.parent / "mapped.v") == details["netlists"]["before"], "Fresh baseline netlist differs")
        frontend.public_text(fresh_path)
        for name in ("sta.log", "gate_simulation.log", "synthesis_statistics.txt"):
            frontend.public_text(fresh_path.parent / name)
    for path in [report_path] + [report_path.parent / name for name in names]:
        frontend.public_text(path)
    output.mkdir(parents=True, exist_ok=True)
    entries = []
    for name in sorted(names):
        target = output / "inputs" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(report_path.parent / name, target)
        entries.append(frontend.metadata(target, "inputs/" + name))
    shutil.copy2(report_path, output / "inputs/original_report.json")
    entries.append(frontend.metadata(output / "inputs/original_report.json", "inputs/original_report.json"))
    old = frontend.read(baseline / "report.json")
    report = {key: raw[key] for key in ("status", "execution_status", "implementation", "top", "scope", "source_snapshot", "versions", "toolchain_lock", "sta_binary_sha256", *MEASUREMENTS)}
    report.update(schema_version=1, original_report="inputs/original_report.json",
                  provenance={"raw_report_sha256": frontend.digest(report_path), "baseline_report_sha256": frontend.digest(baseline / "report.json"),
                              "baseline_original_report_sha256": frontend.digest(baseline / old["original_report"]),
                              "sealed_baseline_mapped_sha256": frontend.digest(baseline / "inputs/mapped.v"),
                              "fresh_baseline_mapped_sha256": details["netlists"]["before"], "fixed_mapped_sha256": details["netlists"]["after"],
                              "publisher": "py/hold_evidence.py", "publisher_sha256": frontend.digest(Path(__file__))})
    if repeated:
        report["repeat"] = {"status": "MATCH", "raw_report_sha256": frontend.digest(repeat_path),
                            "byte_identical_artifacts": [artifacts[name] for name in IDENTICAL_FILES]}
        for source, relative in [(repeat_path, "repeat/original_report.json")] + [(repeat_path.parent / name, "repeat/" + name) for name in REPEATED_FILES]:
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            entries.append(frontend.metadata(destination, relative))
    if fresh:
        report["fresh_baseline"] = {"raw_report_sha256": frontend.digest(fresh_path), "mapped_sha256": details["netlists"]["before"]}
        for source, relative in [(fresh_path, "fresh_baseline/original_report.json")] + [(fresh_path.parent / name, "fresh_baseline/" + name) for name in ("sta.log", "gate_simulation.log", "synthesis_statistics.txt")]:
            destination = output / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            entries.append(frontend.metadata(destination, relative))
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    entries.append(frontend.metadata(output / "report.json", "report.json"))
    for side in ("before", "after"):
        name = side + "_min_path.txt"
        (output / name).write_text(details[side + "_path"]["text"], encoding="utf-8", newline="\n")
        entries.append(frontend.metadata(output / name, name))
    (output / "README.md").write_text(
        "# Measured controller hold repair\n\n"
        "The original published baseline in `../frontend/` is unchanged. This bundle records an actual single-BUF_X1 "
        "mapped-netlist ECO at the APB read-pending flop D pin, with unchanged RTL, original 10 ns SDC and pinned Nangate45 typical library.\n\n"
        "`inputs/baseline_sta.log` and `inputs/baseline_mapped.v` are the same-run pre-ECO records. "
        "`inputs/sta.log`, mapped/scan netlists, gate log and `inputs/gate_smoke.vcd` belong to the repaired execution. "
        "`timing_paths.json` and the precise path text distinguish the repaired endpoint from the new global worst endpoint. "
        "The original gate/scan viewer remains an independent archived baseline execution. Optional `repeat/` and "
        "`fresh_baseline/` records identify their own executions and do not replace the primary VCD.\n\n"
        "The API checks hashes, same-source/constraint/library assumptions, exact one-buffer connectivity, actual STA paths, "
        "gate/scan counters and actual VCD samples. Scope remains one typical pre-layout corner with ideal clock and external "
        "RAM I/O budgets, zero-delay gate comparison and logical scan checks; this is not multi-corner physical signoff.\n\n"
        "Validate: `python py/hold_evidence.py --check docs/frontend_hold --baseline docs/frontend`. "
        "Regenerate into a fresh directory using `--report results/frontend_hold_final/report.json "
        "--repeat results/frontend_hold_repeat/report.json --fresh-baseline results/frontend_hold_baseline_current/report.json "
        "--baseline docs/frontend --out <fresh-directory>`. No EDA process runs during publication.\n",
        encoding="utf-8", newline="\n")
    entries.append(frontend.metadata(output / "README.md", "README.md"))
    (output / "inputs.json").write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8", newline="\n")
    hold_data(output, Path(os.path.commonpath((output, baseline))), baseline)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--baseline", type=Path, default=ROOT / "docs/frontend")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--repeat", type=Path)
    parser.add_argument("--fresh-baseline", type=Path)
    parser.add_argument("--check", type=Path)
    args = parser.parse_args()
    if args.check:
        model, waves, inputs = hold_data(args.check, Path(os.path.commonpath((args.check.resolve(), args.baseline.resolve()))), args.baseline)
        require(bool(model), "Hold evidence does not exist")
        print(json.dumps({"stages": len(model["stages"]), "waves": len(waves), "inputs": len(inputs)}))
    else:
        require(args.report is not None and args.out is not None, "--report and --out are required")
        package(args.report, args.out, args.baseline, args.repeat, args.fresh_baseline)
        print("HOLD_PACKAGED", args.out)


if __name__ == "__main__":
    main()
