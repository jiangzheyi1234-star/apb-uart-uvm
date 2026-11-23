#!/usr/bin/env python3
"""Package independently audited RAL and checker-sensitivity simulation evidence.

Consumes actual completed reports, never simulated fixtures or proposed results.
All original report/log bytes are copied without rewriting their raw outcomes.
The four selected runtime faults measure checker sensitivity, not exhaustive RTL
mutation coverage and not four additional defects discovered in the design.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path, PurePosixPath
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_evidence import Bundle, digest, read_json, reference


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_CASES = {
    "tx_data_xor": ("uart_smoke_test", "TX_MISMATCH"),
    "rx_data_xor": ("uart_smoke_test", "RX_MISMATCH"),
    "parity_mask": ("uart_parity_requirement_test", "STATUS"),
    "irq_stuck_low": ("uart_irq_requirement_test", "IRQ"),
}
CONTROLS = ("uart_smoke_test", "uart_parity_requirement_test", "uart_irq_requirement_test")
RAL_STATS = re.compile(
    r"\[RAL_STATS\]\s+registers=(\d+)\s+random_iterations=(\d+)\s+RAL_writes=(\d+)"
    r"\s+mirror_reads=(\d+)\s+predicted_normal=(\d+)\s+predicted_banked=(\d+)\s+resets=(\d+)"
)
ACTIVE = re.compile(r"^\s*(?:#\s*)?UVM_INFO\b[^\r\n]*\[MUTATION_ACTIVE\]\s*(\S+)\s*$", re.MULTILINE)
ERROR_IDS = re.compile(r"^\s*(?:#\s*)?UVM_ERROR\b(?!\s*:)[^\r\n]*?\[([^]\r\n]+)\]", re.MULTILINE)
FATAL = re.compile(r"^\s*(?:#\s*)?(?:UVM_FATAL\b(?!\s*:)|%Error|%Fatal|FATAL:|\*\*\s*(?:Error|Fatal)|(?:Error|Fatal)-\[|Segmentation fault|terminate called|Aborting\b)", re.MULTILINE)
PASS_MARKER = re.compile(r"^\s*(?:#\s*)?UVM_INFO\b[^\r\n]*\[UART_UVM_TEST_PASS\]\s+(\w+)\s+completed\b", re.MULTILINE)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def severities(text: str) -> dict:
    result = {}
    for severity in ("ERROR", "FATAL"):
        counts = re.findall(rf"^\s*(?:#\s*)?UVM_{severity}\s*:\s*(\d+)\s*$", text, re.MULTILINE)
        require(bool(counts), f"Missing UVM_{severity} summary")
        result[severity.lower()] = max(map(int, counts))
    return result


def clean_run(run: dict, text: str) -> dict:
    counts = severities(text)
    require(run.get("status") == "PASS" and run.get("returncode") == 0 and run.get("timed_out") is False,
            "Clean control or RAL run must have raw PASS, normal exit and no timeout")
    require(counts == {"error": 0, "fatal": 0} and not ERROR_IDS.search(text) and not FATAL.search(text),
            "Clean transcript contains UVM or simulator failures")
    require(PASS_MARKER.findall(text) == [run["test"]], "Clean transcript lacks the exact single test completion marker")
    require(not ACTIVE.search(text), "A clean control unexpectedly enabled a fault")
    return counts


def copy_log(run: dict, report_path: Path, project: Path, bundle: Bundle, role: str) -> tuple[Path, str, dict]:
    log = reference(run["log"], report_path, project)
    text = log.read_text(encoding="utf-8", errors="replace")
    entry = bundle.add(log, role)
    if run.get("log_sha256"):
        require(entry["sha256"] == run["log_sha256"], f"Transcript SHA-256 mismatch: {log}")
    return log, text, entry


def copy_build_provenance(report: dict, path: Path, project: Path, bundle: Bundle) -> dict:
    require(report.get("status") == "PASS" and report.get("simulator") == "verilator" and report.get("rtl_variant") == "fixed",
            f"Expected a real fixed-RTL Verilator PASS report: {path}")
    builds = report.get("build") or []
    require(bool(builds), "Actual compiler process is missing")
    build_logs = []
    for build in builds:
        require(build.get("returncode") == 0 and build.get("timed_out") is False, "Compiler process did not complete successfully")
        log = reference(build["log"], path, project)
        require(not FATAL.search(log.read_text(encoding="utf-8", errors="replace")), "Compiler transcript contains an error")
        build_logs.append(bundle.add(log, "compiler_log")["bundled_path"])
    binary = report.get("compiled_binary") or {}
    require(bool(re.fullmatch(r"[0-9a-f]{64}", binary.get("sha256", ""))) and binary.get("bytes", 0) > 0,
            "Compiled binary identity is missing")
    snapshot = report.get("source_manifest") or {}
    stable = {key: snapshot.get(key) for key in ("project_files", "uvm_files", "rtl_variant")}
    snapshot_hash = hashlib.sha256(json.dumps(stable, sort_keys=True).encode("utf-8")).hexdigest()
    require(snapshot.get("captured_before_compile") is True and snapshot.get("snapshot_sha256") == snapshot_hash,
            "Build-time source snapshot digest is invalid")
    require(bool(snapshot.get("project_files")) and bool(snapshot.get("uvm_files")), "Source snapshot is empty")
    snapshot_path = reference(report["source_manifest_file"], path, project)
    require(read_json(snapshot_path) == snapshot, "Standalone source snapshot disagrees with the raw report")
    snapshot_entry = bundle.add(snapshot_path, "build_time_source_snapshot")
    origin_path = reference(report["source_origin_map"], path, project)
    origin = read_json(origin_path)
    require(digest(origin_path) == report["source_origin"]["origin_map_sha256"], "ASCII stage origin map SHA-256 mismatch")
    files = origin.get("files", [])
    require(origin.get("all_staged_files_byte_equal") is True and origin.get("verified_files") == len(files),
            "Stage byte-equality evidence is incomplete")
    require(all(item.get("source_sha256") == item.get("staged_sha256") for item in files), "Stage contains altered file bytes")
    staged = {item["path"]: item["staged_sha256"] for item in files}
    for item in snapshot["project_files"]:
        require(staged.get(item["path"]) == item["sha256"], f"Compiled source differs from the verified stage: {item['path']}")
    prefix = PurePosixPath(snapshot["uvm_source_root"]).relative_to(PurePosixPath(origin["staged_project_root"]))
    for item in snapshot["uvm_files"]:
        require(staged.get((prefix / item["path"]).as_posix()) == item["sha256"], "Compiled UVM source differs from the verified stage")
    version = reference(report["tool_version_log"], path, project)
    return {"tool_version": report["tool_version"], "version_log": bundle.add(version, "simulator_version_log")["bundled_path"],
            "binary_sha256_at_execution": binary["sha256"], "binary_bytes": binary["bytes"],
            "source_snapshot_sha256": snapshot_hash, "snapshot_input": snapshot_entry["bundled_path"],
            "origin_map_input": bundle.add(origin_path, "verified_stage_origin_map")["bundled_path"],
            "build_logs": build_logs, "uvm_version": snapshot.get("uvm_version"),
            "upstream": snapshot.get("upstream"), "uvm_archives": snapshot.get("uvm_archives", [])}


def audit_ral(path: Path, project: Path, bundle: Bundle) -> dict:
    report = read_json(path)
    provenance = copy_build_provenance(report, path, project, bundle)
    runs = report.get("runs", [])
    require(len(runs) == 3 and {(run["test"], run["seed"]) for run in runs} == {("uart_ral_test", seed) for seed in (1, 2, 3)},
            "RAL evidence must contain exactly uart_ral_test at seeds 1, 2 and 3")
    audited = []
    for run in sorted(runs, key=lambda item: item["seed"]):
        _, text, entry = copy_log(run, path, project, bundle, "RAL_simulation_log")
        counts = clean_run(run, text)
        matches = RAL_STATS.findall(text)
        require(len(matches) == 1, "RAL run must have exactly one measured RAL_STATS event")
        stats = dict(zip(("registers", "random_iterations", "RAL_writes", "mirror_reads", "predicted_normal", "predicted_banked", "resets"), map(int, matches[0])))
        require(stats["registers"] == 4 and stats["random_iterations"] == 12 and stats["RAL_writes"] == 56 and stats["mirror_reads"] >= 97,
                "Measured RAL work does not satisfy the four-register / 56-write / 97-read feature contract")
        require(stats["predicted_normal"] > 0 and stats["predicted_banked"] > 0 and stats["resets"] >= 2,
                "Both bank prediction paths and reset behavior must execute")
        audited.append({"test": run["test"], "seed": run["seed"], "raw_status": run["status"], "uvm": counts,
                        "statistics": stats, "transcript": entry["bundled_path"], "transcript_sha256": entry["sha256"]})
    return {"raw_report": bundle.add(path, "RAL_raw_report")["bundled_path"], "raw_report_sha256": digest(path),
            "raw_status": report["status"], "provenance": provenance, "runs": audited,
            "metrics": {"pass_runs": len(audited), "runs": 3, "configuration_registers": 4,
                        "total_recorded_RAL_writes": sum(item["statistics"]["RAL_writes"] for item in audited),
                        "total_recorded_mirror_reads": sum(item["statistics"]["mirror_reads"] for item in audited)}}


def audit_mutations(path: Path, project: Path, bundle: Bundle, ral: dict) -> dict:
    report = read_json(path)
    require(report.get("status") == "PASS" and report.get("binary_unchanged_after_controls") is True,
            "Mutation experiment must finish with passing controls and an unchanged recorded executable")
    identity = report["baseline"]
    baseline_path = reference(identity["report"], path, project)
    require(digest(baseline_path) == identity["report_sha256"], "Referenced baseline report changed after the experiment")
    baseline = read_json(baseline_path)
    baseline_provenance = copy_build_provenance(baseline, baseline_path, project, bundle)
    binary_hash = baseline_provenance["binary_sha256_at_execution"]
    require(identity["binary_sha256"] == binary_hash == ral["provenance"]["binary_sha256_at_execution"],
            "RAL, mutation and baseline captured binary identities differ")
    require(identity["binary_bytes"] == baseline_provenance["binary_bytes"] == ral["provenance"]["binary_bytes"],
            "Captured binary sizes disagree despite the declared hash identity")
    require(identity["source_snapshot_sha256"] == baseline_provenance["source_snapshot_sha256"] == ral["provenance"]["source_snapshot_sha256"],
            "RAL and mutation baseline compiled source snapshots differ")
    baseline_logs = []
    for run in baseline["runs"]:
        _, text, entry = copy_log(run, baseline_path, project, bundle, "mutation_baseline_clean_log")
        clean_run(run, text)
        baseline_logs.append({"test": run["test"], "seed": run["seed"], "transcript": entry["bundled_path"], "sha256": entry["sha256"]})
    declared_baselines = identity.get("validated_baseline_tests", [])
    require({item["test"] for item in declared_baselines} == set(CONTROLS) and len(declared_baselines) == 3,
            "Mutation experiment does not reference all three independent baseline tests")
    for item in declared_baselines:
        logfile = reference(item["log"], baseline_path, project)
        require(digest(logfile) == item["log_sha256"], "Baseline clean-log hash mismatch")
        candidates = [run for run in baseline["runs"] if run["test"] == item["test"] and run["seed"] == item["seed"]]
        require(item["seed"] == 1 and len(candidates) == 1 and reference(candidates[0]["log"], baseline_path, project) == logfile,
                "Referenced baseline clean log does not match its declared test / seed")
    runs = report.get("runs", [])
    expected_matrix = {("control_before", test, None) for test in CONTROLS} | {("control_after", test, None) for test in CONTROLS}
    expected_matrix |= {("mutation", test, mode) for mode, (test, _) in EXPECTED_CASES.items()}
    matrix = [(run.get("phase"), run.get("test"), run.get("mutation")) for run in runs]
    require(len(matrix) == 10 and len(set(matrix)) == 10 and set(matrix) == expected_matrix,
            "Expected exactly six before/after controls and four distinct selected faults")
    require([run["phase"] for run in runs] == ["control_before"] * 3 + ["mutation"] * 4 + ["control_after"] * 3,
            "Controls must execute before and after the four injected-fault processes")
    audited = []
    for run in runs:
        _, text, entry = copy_log(run, path, project, bundle, "checker_sensitivity_log")
        require(run.get("returncode") == 0 and run.get("timed_out") is False and not FATAL.search(text),
                "A crash, fatal, timeout or simulator failure cannot count as sensitivity evidence")
        require(run["command"][0] == identity["binary"] and f"+verilator+seed+{run['seed']}" in run["command"] and "+RTL_FIXED=1" in run["command"],
                "Run command does not match the proven binary / seed / fixed-RTL contract")
        counts = severities(text)
        if run["phase"] == "mutation":
            mode = run["mutation"]
            expected_test, expected_id = EXPECTED_CASES[mode]
            require(run["test"] == expected_test and run["seed"] == 1, "Unexpected fault test or seed")
            require(run.get("status") == "DETECTED" and run.get("raw_simulation_status") == "FAIL", "Raw fault outcome must remain FAIL with separate DETECTED classification")
            require(ACTIVE.findall(text) == [mode] and "+MUTATION=" + mode in run["command"], "Fault activation marker or command does not match")
            require(counts["fatal"] == 0 and counts["error"] > 0 and not PASS_MARKER.search(text), "Fault run did not fail cleanly through its checker")
            observed = sorted(set(ERROR_IDS.findall(text)))
            require(observed == [expected_id] and run.get("observed_error_ids") == observed and run.get("expected_error_id") == expected_id,
                    "Only the intended functional error ID may appear")
            raw_status, classified = "FAIL", "DETECTED"
        else:
            clean_run(run, text)
            require(run["seed"] == 1 and not any(arg.startswith("+MUTATION=") for arg in run["command"]), "Clean controls must have no mutation plusarg")
            expected_id = None
            raw_status, classified = "PASS", "PASS"
        audited.append({"phase": run["phase"], "test": run["test"], "seed": run["seed"], "mutation": run.get("mutation"),
                        "raw_simulation_status": raw_status, "classification": classified, "intended_checker": expected_id,
                        "uvm": counts, "transcript": entry["bundled_path"], "transcript_sha256": entry["sha256"]})
    measured = {"clean_control_passes": 6, "clean_control_total": 6, "mutations_detected": 4, "mutations_total": 4, "mutation_score_percent": 100.0}
    require(report.get("metrics") == measured, "Stored mutation metrics disagree with independently audited transcripts")
    return {"raw_report": bundle.add(path, "mutation_raw_report")["bundled_path"], "raw_report_sha256": digest(path),
            "baseline_raw_report": bundle.add(baseline_path, "mutation_baseline_raw_report")["bundled_path"],
            "baseline_raw_report_sha256": digest(baseline_path), "baseline_logs": baseline_logs,
            "baseline_provenance": baseline_provenance, "metrics": measured, "runs": audited,
            "scope": "Four selected testbench-to-DUT boundary faults, not exhaustive RTL mutation coverage or additional discovered RTL bugs"}


def render(summary: dict) -> str:
    e = lambda value: html.escape(str(value))
    ral, mutation = summary["RAL"], summary["checker_sensitivity"]
    ral_rows = "".join(f'<tr><td>{run["seed"]}</td><td class="ok">{run["raw_status"]}</td><td>{run["statistics"]["registers"]}</td><td>{run["statistics"]["RAL_writes"]}</td><td>{run["statistics"]["mirror_reads"]}</td><td>{run["statistics"]["predicted_normal"]} / {run["statistics"]["predicted_banked"]}</td><td><a href="{run["transcript"]}">原始日志</a></td></tr>' for run in ral["runs"])
    fault_rows, control_rows = [], []
    for run in mutation["runs"]:
        if run["phase"] == "mutation":
            fault_rows.append(f'<tr><td><code>{e(run["mutation"])}</code></td><td>{e(run["test"])}</td><td class="fail">FAIL</td><td class="ok">DETECTED</td><td><code>{e(run["intended_checker"])}</code></td><td>{run["uvm"]["error"]} / {run["uvm"]["fatal"]}</td><td><a href="{run["transcript"]}">故障日志</a></td></tr>')
        else:
            phase = "注入前" if run["phase"] == "control_before" else "注入后"
            control_rows.append(f'<tr><td>{phase}</td><td>{e(run["test"])}</td><td>{run["seed"]}</td><td class="ok">PASS</td><td><a href="{run["transcript"]}">控制日志</a></td></tr>')
    p = ral["provenance"]
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>APB UART · RAL 与检查器敏感性证据</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f1f5f9;color:#0f172a;font:15px/1.65 system-ui,"Microsoft YaHei",sans-serif}}header{{padding:48px max(24px,calc((100vw - 1160px)/2));background:#0f172a;color:white}}h1{{font-size:34px;margin:12px 0}}header p{{max-width:940px;color:#cbd5e1}}.eyebrow{{color:#a5b4fc;font-size:13px;letter-spacing:.13em}}main{{max-width:1208px;padding:24px;margin:auto}}.cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}}.card,section{{background:white;border:1px solid #e2e8f0;border-radius:14px;padding:24px}}section{{margin-top:22px}}.card strong{{display:block;font-size:34px;color:#3730a3}}h2{{font-size:22px;margin:0 0 12px}}.muted{{color:#64748b}}.scroll{{overflow:auto}}table{{border-collapse:collapse;width:100%}}td,th{{text-align:left;padding:11px;border-bottom:1px solid #e2e8f0;vertical-align:top}}th{{background:#f8fafc;color:#475569}}.ok{{color:#047857;font-weight:650}}.fail{{color:#b91c1c;font-weight:650}}a{{color:#4338ca}}code,pre{{font:12px/1.6 ui-monospace,Consolas,monospace}}pre{{white-space:pre-wrap;background:#f8fafc;padding:14px;border-radius:8px}}footer{{color:#64748b;padding:24px 0}}@media(max-width:700px){{.cards{{grid-template-columns:1fr}}h1{{font-size:27px}}}}
</style></head><body><header><div class="eyebrow">APB UART / MEASURED FEATURE EVIDENCE</div><h1>寄存器模型与检查器敏感性</h1><p>三次 RAL 实测通过；四种指定边界故障均由预期检查器发现。故障运行的原始状态保留为 FAIL，DETECTED 只表示负向控制生效。所有数字由随包报告和日志重新核验。</p></header><main><div class="cards"><div class="card">RAL 测试<strong>3 / 3 PASS</strong><span class="muted">seed 1、2、3</span></div><div class="card">无故障前后控制<strong>6 / 6 PASS</strong><span class="muted">同一记录二进制与 seed 1</span></div><div class="card">指定故障检出<strong>4 / 4 DETECTED</strong><span class="muted">四项原始仿真状态均为 FAIL</span></div></div>
<section><h2>四个配置寄存器的 RAL 前门访问</h2><p>模型覆盖 IER、LCR、DLL、DLM；通过 APB adapter、bank-aware predictor 与原子 bank frontdoor 检查 DLAB 分页别名、镜像预测、复位和寄存器并发访问。它没有把 FIFO 弹出等副作用寄存器计入四寄存器镜像模型。</p><div class="scroll"><table><tr><th>Seed</th><th>原始结果</th><th>寄存器</th><th>RAL 写</th><th>镜像读</th><th>普通 / 分页预测</th><th>证据</th></tr>{ral_rows}</table></div><p>三次运行累计记录 {ral["metrics"]["total_recorded_RAL_writes"]} 次 RAL 写与 {ral["metrics"]["total_recorded_mirror_reads"]} 次镜像读。每次含 12 轮随机配置；这不是对全部寄存器值组合的穷举。</p><p><a href="{ral["raw_report"]}">原始 RAL 报告</a></p></section>
<section><h2>四个明确的负向控制</h2><p>注入点位于验证平台与 DUT 的连接边界；上游 RTL 文件未改写。一次检出要求激活标记匹配、只出现指定 UVM_ERROR ID、ERROR 数大于零、FATAL 为零、进程正常退出且不产生 PASS 标记。崩溃、超时、无关报错都不能计为检出。</p><div class="scroll"><table><tr><th>故障模式</th><th>测试</th><th>原始仿真</th><th>分类</th><th>唯一检查器 ID</th><th>ERROR / FATAL</th><th>证据</th></tr>{''.join(fault_rows)}</table></div><p class="muted">4/4 仅表示这四个指定控制通过；不代表对所有 RTL 故障有 100% 检出率，也不增加设计缺陷发现数量。</p><p><a href="{mutation["raw_report"]}">原始敏感性实验报告</a> · <a href="{mutation["baseline_raw_report"]}">实验前基线报告</a></p></section>
<section><h2>注入前后都恢复无故障状态</h2><div class="scroll"><table><tr><th>阶段</th><th>测试</th><th>Seed</th><th>原始结果</th><th>证据</th></tr>{''.join(control_rows)}</table></div><p>RAL、实验基线与十次控制记录的编译二进制 SHA-256 一致；实验后再次核对二进制未改变。这里展示的是仿真时记录的身份，未声称分发了可在所有系统运行的仿真二进制。</p></section>
<section><h2>来源、构建与逐文件审计</h2><pre>{e(p["tool_version"])}\nAccellera UVM {e(p["uvm_version"])}\nBinary SHA-256: {e(p["binary_sha256_at_execution"])}\nSource snapshot SHA-256: {e(p["source_snapshot_sha256"])}</pre><p><a href="{p["snapshot_input"]}">编译时源码快照</a> · <a href="{p["origin_map_input"]}">ASCII 暂存字节一致性映射</a> · <a href="{p["version_log"]}">真实工具版本日志</a> · <a href="summary.json">机器可读汇总</a> · <a href="inputs.json">所有输入文件 SHA-256</a></p><p class="muted">打包的是原始报告、三次 RAL 日志、十次控制日志、四次原始基线日志和构建来源文件。原始报告与日志内容均未修改。</p></section><footer>UTC {e(summary["generated_utc"])} · 分享整个目录即可保留上述相对链接与审计文件。</footer></main></body></html>'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ral-report", type=Path, required=True)
    parser.add_argument("--mutation-report", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "features")
    parser.add_argument("--project-root", type=Path, default=ROOT)
    args = parser.parse_args()
    output, project = args.out.resolve(), args.project_root.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error("--out must be a fresh or empty directory; original evidence is never overwritten")
    try:
        bundle = Bundle(output)
        ral = audit_ral(args.ral_report.resolve(), project, bundle)
        mutations = audit_mutations(args.mutation_report.resolve(), project, bundle, ral)
        summary = {"status": "PASS", "generated_utc": datetime.now(timezone.utc).isoformat(),
                   "scope": "Audited RAL and four selected checker controls; no exhaustive verification claim", "RAL": ral, "checker_sensitivity": mutations}
        (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output / "inputs.json").write_text(json.dumps(bundle.inputs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output / "index.html").write_text(render(summary), encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"FEATURE_EVIDENCE_ERROR: {error}\n")
    print(f"FEATURE_EVIDENCE_PASS: actual RAL3/3, clean controls6/6, selected faults4/4; {output / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
