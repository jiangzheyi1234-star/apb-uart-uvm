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
from report_coverage import native_summary, parse_records, lcov_summary
from waveform_data import waveform


ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = {
    "uart_parity_requirement_test", "uart_framing_requirement_test",
    "uart_error_association_test", "uart_irq_requirement_test",
}
ERROR_IDS = re.compile(r"^\s*(?:#\s*)?UVM_ERROR\b(?!\s*:)[^\r\n]*?\[([^]\r\n]+)\]", re.MULTILINE)


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
        code = lcov_summary(inside(base, measured["lcov_input"]))["source_scopes"].get("rtl", {})
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
        result.append({"id": id, "title": title, "summary": summary, "test_ids": [test],
                       "upstream": {"description": before, "source_url": source_url("rtl/" + file)},
                       "fixed": {"description": after, "source_url": source_url("rtl_fixed/" + file)}, "evidence_urls": links})
    return result


def build(root: Path, output: Path, template: Path, version: str, repository: str, commit: str | None = None) -> dict:
    root, output = root.resolve(), output.resolve()
    inputs = []
    for folder in ("release", "features", "protocol"):
        inputs.extend(verify_bundle(root / folder, root))
    rows, coverage, waves, tools = core_data(root / "release", root)
    rows.extend(control_data(root / "features", root))
    protocol, protocol_waves = protocol_data(root / "protocol", root)
    rows.extend(protocol)
    waves.extend(protocol_waves)
    require(len({r["id"] for r in rows}) == len(rows), "Duplicate dashboard row identity")
    ref = commit or "main"
    source_url = lambda path: f"https://github.com/{repository}/blob/{ref}/{path}"
    for record in coverage:
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
    output.mkdir(parents=True, exist_ok=True)
    (output / "assets").mkdir(exist_ok=True)
    (output / "data").mkdir(exist_ok=True)
    shutil.copyfile(template / "index.html", output / "index.html")
    for name in ("app.js", "styles.css"):
        shutil.copyfile(template / name, output / "assets" / name)
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
