#!/usr/bin/env python3
"""Package independently rechecked APB protocol evidence for offline review.

Consumes a completed run_protocol_checks.py audit with 9 positive runs,
3 expected raw timeout FAIL runs and 3 clean recovery controls. Original payloads
are copied byte-for-byte. Binary identity is checked against execution records;
the Linux executable need not remain available on the packaging computer.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import html
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_evidence import Bundle, digest, read_json, reference
from run_protocol_checks import NEGATIVE_TEST, POSITIVE_TESTS, assess_run
import run_regression as regression


ROOT = Path(__file__).resolve().parents[1]
PHASES = ("positive", "negative", "recovery")
REPRESENTATIVES = {("positive", "apb_wait_state_test", 1),
                   ("positive", "apb_reset_abort_test", 1),
                   ("negative", NEGATIVE_TEST, 1)}
METRICS = {"positive_passes": 9, "positive_total": 9, "timeouts_detected": 3,
           "negative_total": 3, "recovery_passes": 3, "recovery_total": 3,
           "raw_simulations": 15}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def safe_relative(raw: str) -> PurePosixPath:
    path, windows = PurePosixPath(raw), PureWindowsPath(raw)
    require(bool(raw) and not path.is_absolute() and not windows.is_absolute() and not windows.drive
            and ".." not in path.parts and ".." not in windows.parts and "\\" not in raw,
            "Unsafe source path in recorded provenance")
    return path


def recorded_identity(value: dict) -> tuple:
    require(sha(value.get("binary_sha256")) and type(value.get("binary_bytes")) is int and value["binary_bytes"] > 0
            and sha(value.get("source_snapshot_sha256")), "Incomplete recorded executable/source identity")
    require(isinstance(value.get("binary"), str) and bool(value["binary"]), "Recorded executable path is missing")
    return (value["binary"].replace("\\", "/"), value["binary_sha256"], value["binary_bytes"], value["source_snapshot_sha256"])


def copy_provenance(report: dict, raw_path: Path, project: Path, bundle: Bundle, phase: str) -> dict:
    require(report.get("suite") == "apb_protocol" and report.get("rtl_variant") is None
            and report.get("simulator") == "verilator" and report.get("completion_marker") == "APB_AGENT_TEST_PASS",
            "Raw profile is not an independent Verilator APB protocol report")
    require(report.get("status") == ("FAIL" if phase == "negative" else "PASS"), "Unexpected raw profile status")
    build_logs = []
    builds = report.get("build") or []
    require(bool(builds), "Actual compiler records are required")
    binary_commands = []
    for build in builds:
        require(build.get("returncode") == 0 and build.get("timed_out") is False, "Compiler did not complete normally")
        log = reference(build["log"], raw_path, project)
        text = log.read_text(encoding="utf-8", errors="replace")
        require(not regression.SIM_ERROR.search(text), "Compiler transcript reports an error")
        build_logs.append(bundle.add(log, "protocol_compiler_log")["bundled_path"])
        if "--binary" in build.get("command", []):
            binary_commands.append(build["command"])
    require(len(binary_commands) == 1, "Expected one recorded Verilator binary build")
    command = binary_commands[0]
    require("--top-module" in command and command[command.index("--top-module") + 1:][:1] == ["tb_top"], "Protocol build has the wrong top module")
    require("-f" in command and command[command.index("-f") + 1:]
            and PurePosixPath(command[command.index("-f") + 1].replace("\\", "/")).name == "files_protocol.f",
            "Protocol build has the wrong filelist")
    require("--coverage" not in command, "Protocol evidence must not use UART functional coverage")

    binary = report.get("compiled_binary") or {}
    snapshot = report.get("source_manifest") or {}
    stable = {key: snapshot.get(key) for key in ("project_files", "uvm_files", "rtl_variant")}
    snapshot_hash = hashlib.sha256(json.dumps(stable, sort_keys=True).encode("utf-8")).hexdigest()
    require(snapshot.get("suite") == "apb_protocol" and snapshot.get("rtl_variant") is None
            and snapshot.get("captured_before_compile") is True and snapshot.get("snapshot_sha256") == snapshot_hash,
            "Invalid protocol build-time snapshot")
    require(snapshot.get("project_files") and snapshot.get("uvm_files"), "Source snapshot is empty")
    identity = {"binary": binary.get("path"), "binary_sha256": binary.get("sha256"),
                "binary_bytes": binary.get("bytes"), "source_snapshot_sha256": snapshot_hash}
    recorded_identity(identity)
    snapshot_path = reference(report["source_manifest_file"], raw_path, project)
    require(read_json(snapshot_path) == snapshot, "Snapshot sidecar differs from its raw profile")

    origin_path = reference(report["source_origin_map"], raw_path, project)
    origin = read_json(origin_path)
    declared = report.get("source_origin") or {}
    require(digest(origin_path) == declared.get("origin_map_sha256"), "Stage-origin SHA-256 does not match the raw profile")
    files = origin.get("files") or []
    require(origin.get("all_staged_files_byte_equal") is True and declared.get("all_staged_files_byte_equal") is True
            and origin.get("verified_files") == declared.get("verified_files") == len(files) and bool(files),
            "Incomplete stage byte-equality record")
    for field in ("original_project_root", "staged_project_root"):
        require(isinstance(origin.get(field), str) and origin[field] == declared.get(field), "Stage roots disagree with the raw profile")
    require(origin.get("runner_command") == declared.get("runner_command") and bool(origin.get("runner_command")),
            "Stage runner command differs from the raw profile")
    staged = {}
    for entry in files:
        relative = safe_relative(entry["path"]).as_posix()
        require(relative not in staged and sha(entry.get("source_sha256")) and entry["source_sha256"] == entry.get("staged_sha256")
                and type(entry.get("bytes")) is int and entry["bytes"] >= 0, "Invalid, duplicate or unequal stage entries")
        staged[relative] = entry

    def match_snapshot(entries: list[dict], prefix: PurePosixPath = PurePosixPath(".")) -> None:
        seen = set()
        for entry in entries:
            relative = safe_relative(entry["path"])
            require(relative.as_posix() not in seen, "Duplicate source snapshot entries")
            seen.add(relative.as_posix())
            matched = staged.get((prefix / relative).as_posix(), {})
            require(sha(entry.get("sha256")) and entry["sha256"] == matched.get("staged_sha256")
                    and type(entry.get("bytes")) is int and entry["bytes"] == matched.get("bytes"),
                    "Compiled source snapshot differs from verified stage: " + entry["path"])

    project_paths = [entry["path"] for entry in snapshot["project_files"]]
    require("sim/files_protocol.f" in project_paths and not any(path.startswith(("rtl/", "rtl_fixed/")) for path in project_paths),
            "Protocol snapshot selects UART RTL or lacks its independent filelist")
    match_snapshot(snapshot["project_files"])
    stage_root = PurePosixPath(origin["staged_project_root"].replace("\\", "/"))
    uvm_root = PurePosixPath(snapshot["uvm_source_root"].replace("\\", "/"))
    prefix = uvm_root.relative_to(stage_root)
    safe_relative(prefix.as_posix())
    match_snapshot(snapshot["uvm_files"], prefix)

    version = reference(report["tool_version_log"], raw_path, project)
    version_process = report.get("tool_version_process") or {}
    require(version_process.get("returncode") == 0 and version_process.get("timed_out") is False
            and reference(version_process["log"], raw_path, project) == version, "Invalid tool-version execution record")
    version_text = version.read_text(encoding="utf-8", errors="replace")
    measured_version = "\n".join(line for line in version_text.splitlines() if not line.startswith("COMMAND ")).strip()
    require(bool(measured_version) and measured_version == report.get("tool_version"), "Recorded tool version differs from its log")
    return {"phase": phase, "raw_report": bundle.add(raw_path, "protocol_raw_profile")["bundled_path"],
            "raw_status": report["status"], "tool_version": report["tool_version"], "uvm_version": snapshot.get("uvm_version"),
            "snapshot_input": bundle.add(snapshot_path, "protocol_build_time_source_snapshot")["bundled_path"],
            "origin_map_input": bundle.add(origin_path, "protocol_verified_stage_origin_map")["bundled_path"],
            "version_log": bundle.add(version, "protocol_simulator_version_log")["bundled_path"],
            "build_logs": build_logs, "execution_identity": identity}


def build_summary(path: Path, project: Path, bundle: Bundle) -> dict:
    audit = read_json(path)
    require(audit.get("status") == "PASS" and audit.get("suite") == "apb_protocol" and audit.get("rtl_variant") is None,
            "A completed independent protocol audit PASS is required")
    require(audit.get("seeds") == [1, 2, 3] and audit.get("metrics") == METRICS, "Expected the full 9+3+3 protocol audit matrix")
    identity = audit.get("identity") or {}
    common = recorded_identity(identity)
    require(all(identity.get(flag) is True for flag in ("binary_unchanged_after_controls", "same_binary_all_profiles", "same_source_snapshot_all_profiles",
                                                       "current_project_sources_match", "current_uvm_sources_match")),
            "Execution audit lacks its binary/source identity checks")
    raw_profiles = audit.get("raw_reports") or []
    require([entry.get("phase") for entry in raw_profiles] == list(PHASES), "Raw profiles must preserve positive/negative/recovery order")
    flat_runs = audit.get("runs") or []
    expected = {(phase, test, seed) for phase, tests in (("positive", POSITIVE_TESTS), ("negative", (NEGATIVE_TEST,)), ("recovery", (POSITIVE_TESTS[0],)))
                for test in tests for seed in (1, 2, 3)}
    keys = [(run.get("phase"), run.get("test"), run.get("seed")) for run in flat_runs]
    require(len(keys) == 15 and set(keys) == expected, "Audit has incomplete or duplicate protocol runs")
    derived, provenance = {}, []
    audit_input = bundle.add(path, "protocol_raw_audit")["bundled_path"]
    for saved in raw_profiles:
        phase = saved["phase"]
        raw_path = reference(saved["path"], path, project)
        require(digest(raw_path) == saved.get("sha256"), "Raw profile bytes differ from the execution audit")
        report = read_json(raw_path)
        require(saved.get("raw_status") == report.get("status"), "Audit and raw profile status disagree")
        prov = copy_provenance(report, raw_path, project, bundle, phase)
        require(recorded_identity(prov["execution_identity"]) == common == recorded_identity(saved.get("source_identity") or {}),
                "Protocol profiles do not share the audited executable/source identity")
        sidecar = reference(report["source_manifest_file"], raw_path, project)
        require(reference(saved["source_identity"]["source_snapshot_file"], path, project) == sidecar,
                "Audit source-sidecar reference differs from its raw profile")
        process = saved.get("runner_process") or {}
        require(process.get("timed_out") is False and process.get("returncode") == (1 if phase == "negative" else 0), "Invalid wrapper execution result")
        prov["runner_log"] = bundle.add(reference(process["log"], path, project), "protocol_wrapper_log")["bundled_path"]
        provenance.append(prov)
        profile_runs = report.get("runs") or []
        selected = [key for key in expected if key[0] == phase]
        actual = [(phase, run.get("test"), run.get("seed")) for run in profile_runs]
        require(len(actual) == len(selected) and set(actual) == set(selected), "Raw profile test/seed matrix is incomplete or duplicated")
        for raw in profile_runs:
            key = (phase, raw["test"], raw["seed"])
            saved_run = flat_runs[keys.index(key)]
            log = reference(raw["log"], raw_path, project)
            require(reference(saved_run["log"], path, project) == log and digest(log) == saved_run.get("log_sha256"), "Protocol transcript SHA-256/path differs from the audit")
            require(raw.get("command") == saved_run.get("command") and raw.get("returncode") == saved_run.get("returncode")
                    and raw.get("timed_out") == saved_run.get("timed_out"), "Recorded process data differ between raw profile and audit")
            command = raw.get("command") or []
            require(command and command[0].replace("\\", "/") == common[0]
                    and f"+UVM_TESTNAME={raw['test']}" in command and f"+verilator+seed+{raw['seed']}" in command
                    and not any(part.startswith(("+RTL_FIXED", "+verilator+coverage")) for part in command)
                    and not raw.get("coverage_file"), "Protocol run command/flags disagree with execution identity")
            checked = assess_run(log.read_text(encoding="utf-8", errors="replace"), raw.get("returncode"), raw.get("timed_out", False), raw["test"], phase == "negative")
            require(checked["classification"] == ("DETECTED" if phase == "negative" else "PASS"), "Protocol log failed independent reassessment: " + checked["reason"])
            for field in ("raw_status", "classification", "stats", "error_ids", "uvm_errors", "uvm_fatals"):
                require(saved_run.get(field) == checked[field], "Audited protocol field differs from its log: " + field)
            require(raw.get("status") == checked["raw_status"] and raw.get("uvm_errors") == checked["uvm_errors"]
                    and raw.get("uvm_fatals") == checked["uvm_fatals"], "Raw protocol result differs from its transcript")
            record = {**saved_run, "log": bundle.add(log, "protocol_simulation_log")["bundled_path"], "waveform_file": None}
            if key in REPRESENTATIVES:
                require(bool(raw.get("waveform_file")) and bool(saved_run.get("waveform_file")), "Missing a representative seed-1 protocol waveform")
                wave = reference(raw["waveform_file"], raw_path, project)
                require(reference(saved_run["waveform_file"], path, project) == wave and wave.stat().st_size > 0, "Representative waveform differs from the audit or is empty")
                wave_input = bundle.add(wave, "protocol_representative_vcd")
                record.update(waveform_file=wave_input["bundled_path"], waveform_sha256=wave_input["sha256"])
            derived[key] = record
    require(len(derived) == 15, "Missing independently rechecked protocol runs")
    return {"status": "PASS", "generated_utc": datetime.now(timezone.utc).isoformat(),
            "scope": "Rechecked APB-agent protocol evidence: 9 positive PASS, 3 raw timeout FAIL/DETECTED, 3 clean recovery PASS; no UART coverage claim",
            "metrics": dict(METRICS), "identity": {"binary_sha256": common[1], "binary_bytes": common[2], "source_snapshot_sha256": common[3],
                    "same_binary_all_profiles": True, "same_source_snapshot_all_profiles": True, "binary_unchanged_after_controls": True,
                    "scope": "Execution-record identity, snapshot digest and recorded stage byte equality; packaging does not reopen or rerun the Linux executable"},
            "raw_audit": audit_input, "provenance": provenance, "runs": [derived[key] for key in keys]}


def render(summary: dict) -> str:
    e = lambda value: html.escape(str(value), quote=True)
    rows = []
    for run in summary["runs"]:
        stats = run["stats"]
        wave = f' · <a href="{e(run["waveform_file"])}">VCD</a>' if run["waveform_file"] else ""
        rows.append(f'<tr><td>{e(run["phase"])}</td><td><code>{e(run["test"])}</code></td><td>{run["seed"]}</td>'
                    f'<td>{e(run["raw_status"])}</td><td>{e(run["classification"])}</td><td>{stats["completed"]}</td>'
                    f'<td>{stats["reset_aborts"]} / {stats["timeout_aborts"]}</td><td><a href="{e(run["log"])}">日志</a>{wave}</td></tr>')
    builds = []
    for item in summary["provenance"]:
        links = [(item["raw_report"], "原始报告"), (item["snapshot_input"], "源码快照"), (item["origin_map_input"], "暂存字节映射"),
                 (item["version_log"], "版本日志"), (item["runner_log"], "运行器日志")]
        links += [(log, f"编译日志 {index + 1}") for index, log in enumerate(item["build_logs"])]
        builds.append('<li>' + e(item["phase"]) + '：' + ' · '.join(f'<a href="{e(link)}">{e(label)}</a>' for link, label in links) + '</li>')
    identity = summary["identity"]
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>APB Agent 协议验证证据</title><style>body{{font:16px/1.6 system-ui,sans-serif;margin:auto;padding:28px;max-width:1200px;color:#172b45}}section{{margin:28px 0}}table{{border-collapse:collapse;width:100%;font-size:14px}}td,th{{padding:9px;border:1px solid #d6e0ea;text-align:left}}th{{background:#edf3f8}}code,pre{{overflow-wrap:anywhere}}a{{color:#075ca8}}.table{{overflow-x:auto}}pre{{white-space:pre-wrap;background:#f1f5f8;padding:16px}}</style></head>
<body><main><h1>APB Agent 协议验证证据</h1><p>审计状态：<strong>{e(summary["status"])}</strong>。9 次正向通过、3 次预期超时的原始 FAIL 均被指定检查器检出，另有 3 次正常恢复对照通过。共 15 次独立仿真；审计 PASS 不表示全部原始运行为 PASS。</p>
<p>协议平台使用独立 APB 从设备验证 PREADY 等待、复位中止、超时与恢复，不计入 UART 核心回归、帧数或功能覆盖率。</p>
<section><h2>逐次运行</h2><div class="table"><table><thead><tr><th>阶段</th><th>测试</th><th>Seed</th><th>原始状态</th><th>审计判定</th><th>完成传输</th><th>复位 / 超时中止</th><th>证据</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p>DETECTED 要求唯一一次 APB_TIMEOUT、正常退出、零 FATAL、ARMED→错误→SCENARIO_COMPLETE 顺序、明确的超时后恢复传输，以及没有正常 PASS 标记。超时、崩溃或无关错误不计为检出。</p></section>
<section><h2>执行身份与来源</h2><pre>Binary SHA-256 at execution: {e(identity["binary_sha256"])}\nBinary bytes: {identity["binary_bytes"]}\nSource snapshot SHA-256: {e(identity["source_snapshot_sha256"])}</pre>
<p>三个阶段记录相同二进制与源码快照。打包工具重算快照摘要、核对暂存映射、逐份重读日志并验证 SHA-256；二进制身份来自执行记录，打包时不要求 Linux 可执行文件仍可访问，也不重新运行仿真。</p><ul>{''.join(builds)}</ul></section>
<section><h2>离线复核</h2><p><a href="{e(summary["raw_audit"])}">原始审计报告</a> · <a href="summary.json">派生汇总</a> · <a href="inputs.json">全部原始输入 SHA-256</a></p>
<p>整个目录中的原始报告、源码快照、暂存映射、编译与版本日志、15 份仿真日志和 3 份代表性 VCD 均保持原字节。原始报告内的执行路径未重写；本页与派生汇总使用相对链接。保留完整目录即可离线阅读。</p></section><footer>UTC {e(summary["generated_utc"])}</footer></main></body></html>'''


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    output = args.out.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error("--out must be a new or empty directory; original evidence is never overwritten")
    try:
        bundle = Bundle(output)
        summary = build_summary(args.report.resolve(), args.project_root.resolve(), bundle)
        for item in bundle.inputs:
            copied = output / item["bundled_path"]
            require(digest(copied) == item["sha256"] and copied.stat().st_size == item["bytes"], "Copied evidence differs from its original bytes")
        (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output / "inputs.json").write_text(json.dumps(bundle.inputs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output / "index.html").write_text(render(summary), encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"PROTOCOL_EVIDENCE_ERROR: {error}\n")
    print(f"PROTOCOL_EVIDENCE_PASS: positive9/9, selected timeouts3/3, recovery3/3; {output / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
