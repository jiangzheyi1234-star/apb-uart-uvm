#!/usr/bin/env python3
"""Build an offline diagnostic workbench from audited, hash-checked evidence.

No regression result is generated here. Raw logs, measured native coverage and
VCD samples supply the data. UART, APB qualification and fault controls retain
separate scopes and denominators.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

from build_evidence import read_json, validate_transcript
from report_coverage import native_summary, parse_records, lcov_summary, lcov_file_details, source_scope
from recovered_waveforms import recovered_wave_links
from waveform_data import waveform


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = {
    "uart_parity_requirement_test", "uart_framing_requirement_test",
    "uart_error_association_test", "uart_irq_requirement_test",
}
ERROR_IDS = re.compile(r"^\s*(?:#\s*)?UVM_ERROR\b(?!\s*:)[^\r\n]*?\[([^]\r\n]+)\]", re.MULTILINE)
FAILURE_RECORD = re.compile(r"^\s*(?:#\s*)?UVM_(?:ERROR|FATAL)\b(?!\s*:)")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def inside(base: Path, relative: str) -> Path:
    require(isinstance(relative, str) and bool(relative), "A bundled evidence path is required")
    path = (base / relative).resolve()
    require(path.is_relative_to(base.resolve()) and path.is_file(), f"Evidence path is missing or escapes its bundle: {relative}")
    return path


def href(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def verify_bundle(base: Path, root: Path) -> list[dict]:
    manifest = json.loads((base / "inputs.json").read_text(encoding="utf-8"))
    require(isinstance(manifest, list), f"Expected a list manifest: {base}")
    results = []
    seen = set()
    for entry in manifest:
        if not entry.get("bundled_path"):
            continue
        path = inside(base, entry["bundled_path"])
        require(path not in seen, f"Duplicate bundled input: {path}")
        seen.add(path)
        require(digest(path) == entry["sha256"] and path.stat().st_size == entry["bytes"], f"Bundled input digest/size mismatch: {path}")
        results.append({"path": href(path, root), "sha256": entry["sha256"], "bytes": entry["bytes"]})
    require(bool(results), f"Empty evidence manifest: {base}")
    return results


def relative_rtl_source(filename: str, variant: str) -> str | None:
    """Normalize only repository-relative RTL names, never an absolute suffix."""
    if not isinstance(filename, str):
        return None
    path = filename.replace("\\", "/")
    if path.startswith("/") or ":" in path:
        return None
    parts = path.split("/")
    if any(part in ("", "..") for part in parts):
        return None
    normalized = "/".join(part for part in parts if part != ".")
    folder = "rtl_fixed" if variant == "fixed" else "rtl" if variant == "upstream" else None
    return normalized if folder and re.fullmatch(rf"{folder}/[A-Za-z0-9_./-]+\.sv", normalized) else None


def coverage_code_files(base: Path, report: dict, lcov_path: Path, summary: dict) -> list[dict] | None:
    """Link only a complete RTL scope authorized by its archived source snapshot.

    Older evidence without a snapshot, absolute/untrusted SF names, or ambiguous
    aliases retains its original summary and simply has no optional drilldown.
    """
    manifest = report.get("build_source_snapshot", {}).get("manifest_input")
    if not manifest:
        return None
    snapshot = read_json(inside(base, manifest))
    variant = report["rtl_variant"]
    authorized = {relative_rtl_source(item.get("path"), variant)
                  for item in snapshot.get("project_files", []) if isinstance(item, dict)} - {None}
    selected = []
    seen = set()
    for item in lcov_file_details(lcov_path, summary):
        if source_scope(item["filename"]) != "rtl":
            continue
        source = relative_rtl_source(item["filename"], variant)
        if source is None or source not in authorized or source in seen:
            return None
        seen.add(source)
        selected.append({"source_path": source, "lines": item["lines"],
                         "branches": item["branches"], "gaps": item["gaps"]})
    scope = summary["source_scopes"].get("rtl", {})
    for kind, prefix in (("lines", "lines"), ("branches", "branches")):
        for field, suffix in (("hit", "hit"), ("total", "total")):
            require(sum(item[kind][field] for item in selected) == scope.get(f"{prefix}_{suffix}", 0),
                    "Per-file RTL coverage contradicts LCOV scope")
    return sorted(selected, key=lambda item: item["source_path"])


def core_data(base: Path, root: Path) -> tuple[list[dict], list[dict], list[dict], list[str]]:
    summary = read_json(base / "summary.json")
    rows, coverage, waves, tools = [], [], [], []
    for report in summary["reports"]:
        raw = read_json(inside(base, report["report_input"]))
        require(raw.get("status") in ("PASS", "FAIL") and raw.get("simulator") == "verilator", "Completed real Verilator reports are required")
        raw_rows = {(r["test"], r["seed"]): r for r in raw["runs"]}
        require(len(raw_rows) == len(raw["runs"]) == len(report["runs"]), "Duplicate or missing regression rows")
        variant = report["rtl_variant"]
        require(variant in ("fixed", "upstream"), "Unknown UART variant")
        suite = "uart_ral" if all(r["test"] == "uart_ral_test" for r in report["runs"]) else "uart_core"
        uvm_version = report.get("build_source_snapshot", {}).get("uvm_version")
        tools.extend([report.get("tool_version"), "Accellera UVM " + uvm_version if uvm_version else None])
        for row in report["runs"]:
            actual = raw_rows[(row["test"], row["seed"])]
            require(row["status"] == actual["status"], "Summary changed a raw result")
            log = inside(base, row["transcript"])
            checked = validate_transcript(actual, log.read_text(encoding="utf-8"))
            require(checked["uvm"] == row["uvm"] and checked["scoreboard"] == row.get("scoreboard"), "Dashboard counts contradict the original log")
            run_id = f"{suite}:{variant}:{row['test']}:{row['seed']}"
            stats = checked["scoreboard"] or {}
            record = {"id": run_id, "suite_id": suite, "variant": variant, "test": row["test"], "seed": row["seed"],
                      "raw_status": row["status"], "classification": None,
                      "expected": (variant == "upstream" and row["test"] in REQUIREMENTS and row["status"] == "FAIL"
                                   and checked["uvm"]["error"] is not None and checked["uvm"]["error"] > 0
                                   and checked["uvm"]["fatal"] == 0 and actual.get("returncode") == 0 and not actual.get("timed_out")),
                      "metrics": {"tx": stats.get("tx"), "rx": stats.get("rx"), "errors": checked["uvm"]["error"],
                                  "fatals": checked["uvm"]["fatal"], "warnings": checked["uvm"]["warning"],
                                  "duration_s": row.get("elapsed_seconds")},
                      "log_url": href(log, root), "report_url": href(inside(base, report["report_input"]), root)}
            rows.append(record)
            if row.get("waveform") and row["seed"] == 1 and (
                row["test"] in ("uart_error_test", "uart_error_association_test")
                or variant == "fixed" and row["test"] == "uart_reset_test"
            ):
                path = inside(base, row["waveform"])
                require(digest(path) == row["waveform_sha256"], "Waveform digest mismatch")
                waves.append(waveform(path, id=run_id, title=f"{variant} / {row['test']} / seed 1", run_id=run_id, url=href(path, root)))
        measured = report.get("coverage")
        if not measured:
            continue
        native_path = inside(base, measured["merged_database_input"])
        native = native_summary(parse_records(native_path))
        functional = native["functional"]
        require(all(functional[key] == measured["functional"][key] for key in ("bins_hit", "bins_total")), "Coverage bins contradict the native database")
        lcov_path = inside(base, measured["lcov_input"])
        lcov = lcov_summary(lcov_path)
        code = lcov["source_scopes"].get("rtl", {})
        require(code == measured["code_scopes"].get("rtl", {}), "RTL coverage contradicts LCOV")
        groups = []
        for name, values in functional["by_point"].items():
            label = name.split("::")[-1]
            groups.append({"id": name, "title": label, "hit": values["bins_hit"], "total": values["bins_total"]})
        gaps = []
        for index, gap in enumerate(functional["uncovered_bins"]):
            diagnostic = "invalid_pending" in gap["hierarchy"]
            relative = "tb/" + gap["file"].replace("\\", "/").split("/tb/", 1)[1] if "/tb/" in gap["file"].replace("\\", "/") else None
            gaps.append({"id": f"gap-{index}", "group": gap["hierarchy"].split("::")[-1], "bin": gap["name"],
                         "hits": gap["hits"], "at_least": gap["at_least"],
                         "reason": "无效中断编码诊断项；修复版正确行为不应命中，仍保留在分母。" if diagnostic and variant == "fixed" else "原生数据库未记录达到阈值的命中；需按需求分析可达性。",
                         "source_path": relative, "source_line": gap.get("line")})
        coverage.append({"id": suite + ":" + variant, "title": f"{suite} / {variant}", "suite_id": suite, "variant": variant,
                         "scope": "Only PASS runs in this profile; RTL source files only for LCOV",
                         "note": "不同套件、不同 RTL 的覆盖分母独立；不对它们相加或用差值推断质量。",
                         "metrics": {"functional_bins": {"hit": functional["bins_hit"], "total": functional["bins_total"]},
                                     "rtl_lines": {"hit": code.get("lines_hit"), "total": code.get("lines_total")},
                                     "rtl_branches": {"hit": code.get("branches_hit"), "total": code.get("branches_total")}},
                         "groups": groups, "gaps": gaps,
                         "evidence_urls": [{"label": "原生 coverage.dat", "url": href(native_path, root)},
                                           {"label": "LCOV", "url": href(inside(base, measured["lcov_input"]), root)},
                                           {"label": "覆盖统计 JSON", "url": href(inside(base, measured["summary_input"]), root)}]})
        code_files = coverage_code_files(base, report, lcov_path, lcov)
        if code_files is not None:
            coverage[-1]["code_files"] = code_files
    return rows, coverage, waves, [tool for tool in dict.fromkeys(tools) if tool]


def control_data(base: Path, root: Path) -> list[dict]:
    data = read_json(base / "summary.json")
    require(data.get("status") == "PASS", "Checker evidence did not pass its independent audit")
    controls = data["checker_sensitivity"]
    baseline = read_json(inside(base, controls["baseline_raw_report"]))
    processes = read_json(inside(base, controls["raw_report"]))
    raw_rows = {(r["phase"], r["test"], r.get("mutation")): r for r in processes["runs"]}
    result = []
    for row in controls["runs"]:
        log = inside(base, row["transcript"])
        require(digest(log) == row["transcript_sha256"], "Control transcript digest mismatch")
        raw = raw_rows[(row["phase"], row["test"], row.get("mutation"))]
        text = log.read_text(encoding="utf-8")
        negative = row["phase"] == "mutation"
        ids = ERROR_IDS.findall(text)
        if negative:
            require(row["raw_simulation_status"] == "FAIL" and row["classification"] == "DETECTED", "Fault status/classification mismatch")
            require(set(ids) == {row["intended_checker"]} and row["uvm"]["error"] > 0 and row["uvm"]["fatal"] == 0, "Fault detection is not backed by its intended error")
            require(f"[MUTATION_ACTIVE] {row['mutation']}" in text, "Fault activation is missing")
        else:
            require(row["raw_simulation_status"] == "PASS" and not ids, "Control is not a clean PASS")
        require(raw.get("returncode") == 0 and not raw.get("timed_out"), "A crash or timeout cannot be plotted as a control result")
        counts = re.findall(r"\[SB_COUNTS\].*?TX=(\d+)\s+RX=(\d+)", text)
        tx, rx = map(int, counts[-1]) if counts else (None, None)
        result.append({"id": f"fault_control:{row['phase']}:{row['test']}:{row.get('mutation') or 'clean'}:{row['seed']}",
                       "suite_id": "fault_control", "variant": "fixed", "test": row["test"], "seed": row["seed"],
                       "phase": row["phase"], "raw_status": row["raw_simulation_status"], "classification": row["classification"], "expected": negative,
                       "metrics": {"tx": tx, "rx": rx, "errors": row["uvm"]["error"], "fatals": row["uvm"]["fatal"],
                                   "duration_s": raw.get("elapsed_seconds")},
                       "log_url": href(log, root), "report_url": href(inside(base, controls["raw_report"]), root),
                       "mutation": row.get("mutation"), "intended_checker": row.get("intended_checker")})
    require(baseline.get("status") == "PASS" and len(result) == 10, "Missing fixed baseline or checker controls")
    return result


def protocol_data(base: Path, root: Path) -> tuple[list[dict], list[dict]]:
    from run_protocol_checks import assess_run

    summary = read_json(base / "summary.json")
    require(summary.get("status") == "PASS" and len(summary["runs"]) == 15, "A complete protocol audit is required")
    result, waves = [], []
    for row in summary["runs"]:
        log = inside(base, row["log"])
        require(digest(log) == row["log_sha256"], "Protocol transcript changed")
        assessment = assess_run(log.read_text(encoding="utf-8"), row["returncode"], row["timed_out"], row["test"], row["phase"] == "negative")
        require(all(assessment[key] == row[key] for key in ("raw_status", "classification", "stats", "error_ids")), "Protocol display contradicts the original transcript")
        stats = row["stats"]
        run_id = f"apb_protocol:{row['phase']}:{row['test']}:{row['seed']}"
        result.append({"id": run_id, "suite_id": "apb_protocol", "variant": "agent", "test": row["test"], "seed": row["seed"],
                       "phase": row["phase"], "raw_status": row["raw_status"], "classification": row["classification"], "expected": row["phase"] == "negative",
                       "metrics": {"errors": row["uvm_errors"], "fatals": row["uvm_fatals"], "apb_completed": stats["completed"],
                                   "apb_reads": stats["reads"], "apb_writes": stats["writes"], "max_wait": stats["max_wait"],
                                   "reset_aborts": stats["reset_aborts"], "timeout_aborts": stats["timeout_aborts"]},
                       "log_url": href(log, root), "report_url": href(inside(base, summary["raw_audit"]), root)})
        if row.get("waveform_file"):
            path = inside(base, row["waveform_file"])
            decoded = waveform(path, id=run_id, title=f"APB / {row['test']} / {row['phase']} / seed {row['seed']}",
                               run_id=run_id, url=href(path, root), uart_registers=False)
            completed = [event for event in decoded["apb_events"] if event["status"] in ("OK", "SLVERR")]
            require(len(completed) == stats["completed"], "VCD APB completion count differs from the independent monitor")
            for wait in (0, 1, 3, 7):
                require(sum(event["wait_cycles"] == wait for event in completed) == stats[f"wait{wait}"],
                        "VCD APB wait histogram differs from the independent monitor")
            waves.append(decoded)
    return result, waves


def architecture(source_url) -> dict:
    definitions = [
        ("sequence", "Test / Sequence", "可复用激励", 30, 55, "tb/test/uart_tests.sv"),
        ("apb_driver", "APB Driver", "Setup / Access / wait / abort", 260, 55, "tb/apb_agent/apb_driver.sv"),
        ("dut", "APB UART DUT", "仅选择原版或修复版", 490, 55, "rtl_fixed/apb_uart.sv"),
        ("tx_monitor", "TX Pin Monitor", "独立引脚解码", 720, 55, "tb/uart_agent/uart_monitor.sv"),
        ("ral", "DLAB-aware RAL", "锁住切 bank 与恢复", 30, 235, "tb/ral/uart_dlab_frontdoor.sv"),
        ("apb_monitor", "APB Monitor", "仅发布已完成事务", 260, 235, "tb/apb_agent/apb_monitor.sv"),
        ("scoreboard", "Scoreboard", "独立数据与 FIFO 周期模型", 490, 235, "tb/scoreboard/apb_uart_scoreboard.sv"),
        ("coverage", "Coverage", "原生 bin 与独立 LCOV", 720, 235, "tb/coverage/apb_uart_coverage.sv"),
        ("predictor", "RAL Predictor", "实际 APB 驱动 mirror", 30, 415, "tb/ral/uart_bank_predictor.sv"),
        ("uart_driver", "UART RX Driver", "正常与错误帧注入", 260, 415, "tb/uart_agent/uart_driver.sv"),
        ("rx_monitor", "RX Pin Monitor", "独立接收帧观测", 490, 415, "tb/uart_agent/uart_monitor.sv"),
        ("slave", "APB test slave", "独立协议套件；替代 UART", 720, 415, "tb/protocol/apb_programmable_slave.sv"),
    ]
    nodes = [{"id": id, "label": label, "detail": detail, "x": x, "y": y, "width": 200, "height": 84, "source_url": source_url(path)}
             for id, label, detail, x, y, path in definitions]
    edges = [("sequence", "apb_driver"), ("apb_driver", "dut"), ("dut", "tx_monitor"), ("tx_monitor", "scoreboard"),
             ("apb_driver", "apb_monitor"), ("apb_monitor", "scoreboard"), ("apb_monitor", "coverage"),
             ("apb_monitor", "predictor"), ("predictor", "ral"), ("ral", "apb_driver"),
             ("uart_driver", "dut"), ("uart_driver", "rx_monitor"), ("rx_monitor", "scoreboard"), ("rx_monitor", "coverage"),
             ("apb_driver", "slave")]
    return {"nodes": nodes, "edges": [{"from": a, "to": b} for a, b in edges]}


def defects(rows: list[dict], source_url) -> list[dict]:
    definitions = [
        ("parity", "校验错误标记", "uart_parity_requirement_test", "校验位错误应使对应接收字节的 PE 可见。", "uart_rx.sv", "原版提交数据早于校验检查，且错误状态通路未完整保留。", "在 parity/stop 检查后提交带错误标记的数据。"),
        ("framing", "低停止位检测", "uart_framing_requirement_test", "低停止位应产生 framing error。", "uart_rx.sv", "停止位及 FE 的需求检查失败。", "显式检查停止位并随字节保存 FE。"),
        ("association", "错误与 FIFO 字节关联", "uart_error_association_test", "正常 / 错误 / 正常帧的状态必须跟随对应 FIFO 队首字节。", "apb_uart.sv", "错误状态无法与每个接收字节正确关联。", "RX FIFO 保存数据及 PE/FE，并从队首生成状态。"),
        ("irq", "RX 中断与确认", "uart_irq_requirement_test", "门限、优先级、确认与撤销必须满足记录的接口需求。", "uart_interrupt.sv", "RX 接线与无中断编码、确认/重触发行为存在失败。", "修复 RX 连接、优先级和来源各自的确认规则。"),
    ]
    result = []
    for id, title, test, summary, file, before, after in definitions:
        selected = [r for r in rows if r["test"] == test and r["suite_id"] == "uart_core"]
        links = [{"label": f"{variant} / seed {r['seed']} / {r['raw_status']}", "url": r["log_url"]}
                 for variant in ("upstream", "fixed") for r in selected if r["variant"] == variant and r["seed"] == 1]
        result.append({"id": id, "title": title, "summary": summary, "test_ids": [test], "suite_ids": ["uart_core"],
                       "upstream": {"description": before, "source_url": source_url("rtl/" + file)},
                       "fixed": {"description": after, "source_url": source_url("rtl_fixed/" + file)}, "evidence_urls": links})
    return result


def bind_verification_plan(plan: dict, rows: list[dict]) -> dict:
    """Bind authored points to exact archived IDs, without judging run results."""
    require(isinstance(plan, dict) and isinstance(plan.get("groups"), list), "Verification plan groups must be a list")
    suites = {}
    for row in rows:
        suites.setdefault(row.get("suite_id"), []).append(row)

    def string(value, field):
        require(isinstance(value, str) and bool(value.strip()), f"Verification plan {field} must be a nonempty string")
        return value

    def strings(value, field):
        require(isinstance(value, list), f"Verification plan {field} must be a list")
        return list(dict.fromkeys(string(item, field) for item in value))

    groups, group_ids, item_ids = [], set(), set()
    for group in plan["groups"]:
        require(isinstance(group, dict), "Verification plan groups must be objects")
        group_id = string(group.get("id"), "group id")
        require(group_id not in group_ids, f"Duplicate verification plan group id: {group_id}")
        group_ids.add(group_id)
        require(isinstance(group.get("items"), list), "Verification plan items must be a list")
        items = []
        for item in group["items"]:
            require(isinstance(item, dict), "Verification plan items must be objects")
            item_id = string(item.get("id"), "item id")
            require(item_id not in item_ids, f"Duplicate verification plan item id: {item_id}")
            item_ids.add(item_id)
            require(isinstance(item.get("checks"), list), "Verification plan checks must be a list")
            checks, selected = [], set()
            for check in item["checks"]:
                require(isinstance(check, dict), "Verification plan checks must be objects")
                suite = string(check.get("suite_id"), "suite_id")
                tests = strings(check.get("tests"), "tests")
                bound = {"suite_id": suite, "tests": tests}
                for name in ("phases", "variants"):
                    if name in check:
                        bound[name] = strings(check[name], name)
                matches = [row for row in suites.get(suite, []) if row.get("test") in tests
                           and ("phases" not in bound or row.get("phase") in bound["phases"])
                           and ("variants" not in bound or row.get("variant") in bound["variants"])]
                run_ids = list(dict.fromkeys(row["id"] for row in matches))
                found = {row.get("test") for row in matches}
                missing_tests = [test for test in tests if test not in found]
                bound.update(run_ids=run_ids, missing_tests=missing_tests,
                             binding_status="unrecorded" if not run_ids else "partial" if missing_tests else "recorded")
                selected.update(run_ids)
                checks.append(bound)
            run_ids = list(dict.fromkeys(row["id"] for row in rows if row["id"] in selected))
            items.append({"id": item_id, "title": string(item.get("title"), "item title"),
                          "summary": string(item.get("summary"), "item summary"), "checks": checks, "run_ids": run_ids,
                          "binding_status": "unrecorded" if not run_ids else
                          "recorded" if all(check["binding_status"] == "recorded" for check in checks) else "partial"})
        groups.append({"id": group_id, "title": string(group.get("title"), "group title"), "items": items})
    return {"groups": groups}


def failure_excerpt(text: str) -> list[str]:
    """Keep the first three actual severity records, not report-summary counts."""
    result = []
    for line in text.splitlines():
        if FAILURE_RECORD.match(line):
            result.append(line if len(line) <= 500 else line[:499] + "…")
            if len(result) == 3:
                break
    return result


def append_recovered_waveforms(base: Path, root: Path, rows: list[dict], waves: list[dict], inputs: list[dict]) -> None:
    """Append only independently verified bytes from the original failed run."""
    links = recovered_wave_links(base, root)
    if not links:
        return
    by_id = {row["id"]: row for row in rows}
    rendered = {wave["run_id"] for wave in waves}

    def add_input(path: Path, expected: dict | None = None):
        measured = {"path": href(path, root), "sha256": digest(path), "bytes": path.stat().st_size}
        if expected is not None:
            require(all(measured[key] == expected[key] for key in ("sha256", "bytes")), "Recovered VCD bytes changed")
        existing = next((entry for entry in inputs if entry["path"] == measured["path"]), None)
        require(existing is None or existing == measured, "Recovered input conflicts with an archived input")
        if existing is None:
            inputs.append(measured)

    add_input(inside(base, "recovered-vcd/index.json"))
    for run_id, entry in links.items():
        row = by_id.get(run_id)
        require(row is not None and row["suite_id"] == "uart_core" and row["variant"] == "upstream"
                and row["raw_status"] == "FAIL" and run_id not in rendered, "Recovered VCD does not name one unrendered original failure")
        path = inside(root, entry["url"])
        add_input(path, entry)
        decoded = waveform(path, id=run_id, title=f"upstream / {row['test']} / seed {row['seed']}", run_id=run_id, url=href(path, root))
        require(decoded["source"]["sha256"] == entry["sha256"], "Recovered VCD changed during decoding")
        decoded["source"]["recovered"] = True
        waves.append(decoded)
        rendered.add(run_id)


def annotate_failures(root: Path, rows: list[dict], waves: list[dict]) -> None:
    rendered = {wave["run_id"] for wave in waves}
    for row in rows:
        if row["raw_status"] != "FAIL" or not row.get("log_url"):
            continue
        excerpts = failure_excerpt(inside(root, row["log_url"]).read_text(encoding="utf-8"))
        if excerpts:
            row["failure_excerpt"] = excerpts
        if row["id"] in rendered:
            row.pop("waveform_unavailable", None)
            continue
        if row["suite_id"] == "fault_control" and row.get("phase") == "mutation":
            reason = "该次故障注入未启用 TRACE，原始运行没有生成 VCD。"
        elif row["suite_id"] == "apb_protocol" and row.get("seed") in (2, 3):
            reason = "该次 APB seed 2/3 的原始 VCD 未保留在证据包中；已归档的是 seed 1 波形。"
        else:
            reason = "当前证据包没有该次运行可解码的原始 VCD，仍可核对同次日志。"
        row["waveform_unavailable"] = reason


def build(root: Path, output: Path, template: Path, version: str, repository: str, commit: str | None = None) -> dict:
    root, output = root.resolve(), output.resolve()
    ref = commit or "main"
    # Preserve legacy repository/ref handling. New drilldown links must name a
    # repository and immutable commit; named/omitted refs still retain metrics.
    code_anchor = (bool(re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*/[A-Za-z0-9_-][A-Za-z0-9_.-]*", repository))
                   and bool(re.fullmatch(r"[a-fA-F0-9]{40}", commit or "")))
    inputs = []
    for folder in ("release", "features", "protocol"):
        inputs.extend(verify_bundle(root / folder, root))
    rows, coverage, waves, tools = core_data(root / "release", root)
    rows.extend(control_data(root / "features", root))
    protocol, protocol_waves = protocol_data(root / "protocol", root)
    rows.extend(protocol)
    waves.extend(protocol_waves)
    require(len({r["id"] for r in rows}) == len(rows), "Duplicate dashboard row identity")
    append_recovered_waveforms(root / "release", root, rows, waves, inputs)
    annotate_failures(root, rows, waves)
    source_url = lambda path: f"https://github.com/{repository}/blob/{ref}/{path}"
    for record in coverage:
        for file in record.get("code_files", []):
            if code_anchor:
                file["source_url"] = source_url(file["source_path"])
            else:
                file.pop("source_url", None)
        for gap in record["gaps"]:
            if gap.get("source_path"):
                gap["source_url"] = source_url(gap["source_path"]) + ("#L" + str(gap["source_line"]) if gap.get("source_line") else "")
    now = datetime.now(timezone.utc).isoformat()
    data = {"schema_version": 1,
            "project": {"title": "APB UART Verification Workbench", "version": version, "source_url": f"https://github.com/{repository}",
                        "commit": commit, "generated_utc": now, "toolchain": tools,
                        "source_note": "数据来自已归档日志、原生覆盖数据库与 VCD。UART、独立 APB 协议资格验证及故障控制分别计量；原始 FAIL 不改判。"},
            "headline": {"suite_ids": ["uart_core", "uart_ral"], "variant": "fixed"},
            "suites": [{"id": "uart_core", "title": "UART 核心回归", "kind": "uart", "scope": "15 测试 × 3 seeds × 两套 RTL", "note": "修复版与原版分别报告。"},
                       {"id": "uart_ral", "title": "UART RAL", "kind": "uart", "scope": "四寄存器；三个 seed", "note": "不把专项稀疏覆盖与核心合并。"},
                       {"id": "fault_control", "title": "检查器负向对照", "kind": "control", "scope": "4 次故障 + 6 次正常控制", "note": "DETECTED 表示指定 checker 触发，原始运行仍 FAIL。"},
                       {"id": "apb_protocol", "title": "独立 APB 代理资格验证", "kind": "protocol", "scope": "9 正向 + 3 超时负向 + 3 恢复控制", "note": "使用自建等待从设备；不代表 UART DUT 产生等待状态。"}],
            "runs": rows, "coverage": coverage, "waveforms": waves, "architecture": architecture(source_url), "defects": defects(rows, source_url),
            "inputs": inputs,
            "limitations": ["Verilator 动态结果不能代替四态 / X 传播签核。", "UART DUT 的 PREADY 恒为 1；等待状态、超时和取消在独立 APB 测试从设备中验证。",
                            "协议资格验证覆盖选定的 0/1/3/7 等待、复位和超时场景，不宣称穷举所有仲裁与时序组合。",
                            "不包含完整 16550 兼容、任意波特率失配、传输中配置热切换、活跃 TX 清 FIFO或持续 RX 超载。"]}
    plan_path = template / "verification-plan.json"
    if plan_path.exists():
        require(plan_path.is_file(), "Verification plan mapping must be a file")
        data["verification_plan"] = bind_verification_plan(read_json(plan_path), rows)
    output.mkdir(parents=True, exist_ok=True)
    (output / "assets").mkdir(exist_ok=True)
    (output / "data").mkdir(exist_ok=True)
    shutil.copyfile(template / "index.html", output / "index.html")
    for name in ("app.js", "styles.css"):
        shutil.copyfile(template / name, output / "assets" / name)
    chart_view = template / "chart-view.js"
    if chart_view.is_file():
        shutil.copyfile(chart_view, output / "assets" / chart_view.name)
        shutil.copytree(template / "vendor", output / "assets" / "vendor", dirs_exist_ok=True)
    serialized = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e")
    (output / "data/dashboard.js").write_text("window.UART_DASHBOARD=" + serialized + ";\n", encoding="utf-8", newline="\n")
    (output / "data/dashboard.json").write_text(json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", type=Path, default=ROOT / "docs")
    parser.add_argument("--out", type=Path, default=ROOT / "docs")
    parser.add_argument("--template", type=Path, default=ROOT / "web/dashboard")
    parser.add_argument("--version", default="1.2.0")
    parser.add_argument("--repository", default="jiangzheyi1234-star/apb-uart-uvm")
    parser.add_argument("--commit", help="Optional source commit associated with this report")
    args = parser.parse_args()
    try:
        data = build(args.evidence_root, args.out, args.template, args.version, args.repository, args.commit)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"DASHBOARD_ERROR: {error}", file=sys.stderr)
        return 1
    print(f"DASHBOARD_BUILT: {len(data['runs'])} measured runs; {len(data['waveforms'])} actual VCDs; {len(data['inputs'])} hash-checked inputs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
