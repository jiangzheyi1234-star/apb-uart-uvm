#!/usr/bin/env python3
"""Bundle real UART regression evidence into a shareable Chinese HTML report.

Example:
  python py/build_evidence.py --report results/fixed/report.json \
    --report results/upstream/report.json \
    --expected-fail-report results/upstream/report.json --out docs/evidence

PASS is cross-checked against the original transcript. Dry-run and incomplete
reports are rejected. Expected failures retain their original FAIL status.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil


ROOT = Path(__file__).resolve().parents[1]
SUMMARY = {severity: re.compile(rf"^\s*(?:#\s*)?UVM_{severity}\s*:\s*(\d+)\s*$", re.MULTILINE)
           for severity in ("ERROR", "FATAL", "WARNING")}
MARKER = re.compile(r"^\s*(?:#\s*)?UVM_INFO\b[^\r\n]*\[UART_UVM_TEST_PASS\]", re.MULTILINE)
ERROR = re.compile(r"^\s*(?:#\s*)?(?:UVM_(?:ERROR|FATAL)\b(?!\s*:)|\*\*\s*(?:Error|Fatal)|%Error|(?:Error|Fatal)-\[|FATAL:)", re.MULTILINE)
COUNTS = re.compile(r"\[SB_COUNTS\][^\r\n]*?TX=(\d+)\s+RX=(\d+)\s+resets=(\d+)\s+max_tx=(\d+)\s+max_rx=(\d+)")
BOUNDARIES = re.compile(r"\[SB_BOUNDARIES\][^\r\n]*?TX accepted=(\d+)\s+dropped=(\d+)\s+empty_RBR_reads=(\d+)")


def digest(path: Path, algorithm: str = "sha256") -> str:
    checksum = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def reference(raw: str, report_path: Path, project: Path) -> Path:
    """Resolve saved Linux/WSL paths when reading the evidence on Windows too."""
    value = str(raw).replace("\\", "/")
    candidates = [Path(raw), report_path.parent / raw, project / raw]
    if os.name == "nt":
        match = re.match(r"^/mnt/([a-zA-Z])/(.*)$", value)
        if match:
            candidates.append(Path(match[1].upper() + ":/" + match[2]))
    report_segment = "/" + report_path.parent.name + "/"
    if report_segment in value:
        candidates.append(report_path.parent / value.rsplit(report_segment, 1)[1])
    if "/results/" in value:
        candidates.append(project / "results" / value.split("/results/", 1)[1])
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(f"Referenced evidence file was not found: {raw}")


class Bundle:
    def __init__(self, output: Path):
        self.output = output
        self.inputs = []
        self.seen = {}
        (output / "inputs").mkdir(parents=True)

    def add(self, path: Path, role: str, copy: bool = True) -> dict:
        path = path.resolve()
        if path in self.seen:
            return self.seen[path]
        item = {"original_path": str(path), "role": role, "sha256": digest(path), "bytes": path.stat().st_size,
                "bundled_path": None}
        if copy:
            safe = re.sub(r"[^A-Za-z0-9_.-]", "_", path.name)
            destination = Path("inputs") / f"{len(self.inputs):03d}_{safe}"
            shutil.copyfile(path, self.output / destination)
            item["bundled_path"] = destination.as_posix()
        self.inputs.append(item)
        self.seen[path] = item
        return item


def validate_transcript(run: dict, transcript: str) -> dict:
    severities = {}
    for severity, pattern in SUMMARY.items():
        values = pattern.findall(transcript)
        severities[severity.lower()] = max(map(int, values)) if values else None
    clean = (run.get("returncode") == 0 and not run.get("timed_out", False)
             and severities["error"] == 0 and severities["fatal"] == 0
             and bool(MARKER.search(transcript)) and not ERROR.search(transcript))
    if run.get("status") == "PASS" and not clean:
        raise ValueError(f"Stored PASS is contradicted by its transcript: {run.get('test')} / {run.get('seed')}")
    checks = COUNTS.findall(transcript)
    counters = None
    if checks:
        counters = dict(zip(("tx", "rx", "resets", "max_tx", "max_rx"), map(int, checks[-1])))
    if run.get("status") == "PASS" and counters is None:
        raise ValueError(f"PASS run lacks measured SB_COUNTS: {run.get('test')} / {run.get('seed')}")
    boundary_matches = BOUNDARIES.findall(transcript)
    boundaries = dict(zip(("tx_accepted", "tx_dropped", "empty_rbr_reads"), map(int, boundary_matches[-1]))) if boundary_matches else None
    return {"clean_completion_validated": clean, "uvm": severities, "scoreboard": counters, "boundaries": boundaries}


def load_regression(path: Path, expected: bool, project: Path, bundle: Bundle, include_waveforms: bool,
                    include_databases: bool = False, waveform_tests: set[str] | None = None, waveform_seed: int = 1) -> dict:
    raw = read_json(path)
    if raw.get("status") in (None, "DRY_RUN", "RUNNING", "INTERRUPTED"):
        raise ValueError(f"Only completed actual regression reports are evidence inputs: {path} ({raw.get('status')})")
    report_input = bundle.add(path, "regression_report")
    runs = raw.get("runs", [])
    if not isinstance(runs, list):
        raise ValueError(f"runs must be a list: {path}")
    if raw["status"] == "PASS" and (not runs or any(run.get("status") != "PASS" for run in runs)):
        raise ValueError(f"Invalid PASS report with missing or failed runs: {path}")
    if expected and (raw["status"] != "FAIL" or not any(run.get("status") != "PASS" for run in runs)):
        raise ValueError(f"Expected-failure demonstration must be an actual FAIL regression: {path}")
    result = {"name": path.parent.name, "status": raw["status"], "expected_failure_demonstration": expected,
              "simulator": raw.get("simulator"), "tool_version": raw.get("tool_version"),
              "rtl_variant": raw.get("rtl_variant", "unspecified"), "uvm_source": raw.get("uvm_source"),
              "started_utc": raw.get("started_utc"), "report_input": report_input["bundled_path"],
              "report_sha256": report_input["sha256"], "runs": [], "coverage": None, "build_logs": []}
    snapshot = raw.get("source_manifest")
    if snapshot:
        stable = {"project_files": snapshot["project_files"], "uvm_files": snapshot["uvm_files"], "rtl_variant": snapshot["rtl_variant"]}
        expected_digest = hashlib.sha256(json.dumps(stable, sort_keys=True).encode("utf-8")).hexdigest()
        if not snapshot.get("captured_before_compile") or snapshot.get("snapshot_sha256") != expected_digest:
            raise ValueError(f"Invalid build-time source snapshot: {path}")
        snapshot_input = None
        if raw.get("source_manifest_file"):
            snapshot_path = reference(raw["source_manifest_file"], path, project)
            if read_json(snapshot_path) != snapshot:
                raise ValueError(f"Standalone source snapshot contradicts report: {snapshot_path}")
            snapshot_input = bundle.add(snapshot_path, "build_time_source_manifest")["bundled_path"]
        mismatches = []
        for item in snapshot["project_files"]:
            current = (project / item["path"]).resolve()
            if not current.is_relative_to(project):
                raise ValueError(f"Build snapshot path escapes project: {item['path']}")
            if not current.is_file() or digest(current) != item["sha256"]:
                mismatches.append(item["path"])
        result["build_source_snapshot"] = {"snapshot_sha256": snapshot["snapshot_sha256"],
                                           "captured_utc": snapshot["captured_utc"], "manifest_input": snapshot_input,
                                           "uvm_version": snapshot.get("uvm_version"), "uvm_archives": snapshot.get("uvm_archives", []),
                                           "project_files_count": len(snapshot["project_files"]), "uvm_files_count": len(snapshot["uvm_files"]),
                                           "current_project_sources_match": not mismatches, "current_project_source_mismatches": mismatches}
    if raw.get("source_origin_map"):
        origin_path = reference(raw["source_origin_map"], path, project)
        origin = read_json(origin_path)
        declared = raw.get("source_origin") or {}
        if declared.get("origin_map_sha256") != digest(origin_path):
            raise ValueError(f"Stage origin map does not match the report SHA-256: {origin_path}")
        entries = origin.get("files", [])
        if not origin.get("all_staged_files_byte_equal") or origin.get("verified_files") != len(entries):
            raise ValueError(f"Incomplete stage verification: {origin_path}")
        if any(item.get("source_sha256") != item.get("staged_sha256") for item in entries):
            raise ValueError(f"Stage origin map includes unequal source bytes: {origin_path}")
        staged_files = {item["path"]: item["staged_sha256"] for item in entries}
        if snapshot:
            for item in snapshot["project_files"]:
                if staged_files.get(item["path"]) != item["sha256"]:
                    raise ValueError(f"Compiled project snapshot differs from verified stage: {item['path']}")
            uvm_root = PurePosixPath(snapshot["uvm_source_root"])
            stage_root = PurePosixPath(origin["staged_project_root"])
            uvm_relative = uvm_root.relative_to(stage_root)
            for item in snapshot["uvm_files"]:
                relative = (uvm_relative / item["path"]).as_posix()
                if staged_files.get(relative) != item["sha256"]:
                    raise ValueError(f"Compiled UVM snapshot differs from verified stage: {relative}")
        result["source_origin"] = {"original_project_root": origin["original_project_root"],
                                   "staged_project_root": origin["staged_project_root"],
                                   "verified_files": len(entries), "all_staged_files_byte_equal": True,
                                   "map_input": bundle.add(origin_path, "verified_ascii_stage_origin_map")["bundled_path"]}
    result["compiled_binary"] = raw.get("compiled_binary")
    for build in raw.get("build", []):
        if build.get("log"):
            source = reference(build["log"], path, project)
            result["build_logs"].append(bundle.add(source, "build_log")["bundled_path"])
    if raw.get("tool_version_log"):
        bundle.add(reference(raw["tool_version_log"], path, project), "simulator_version_log")
    for run in runs:
        if run.get("status") in (None, "DRY_RUN", "RUNNING"):
            raise ValueError(f"Non-executed run in actual regression: {path}")
        if not run.get("log"):
            raise ValueError(f"Run has no transcript reference: {path} {run.get('test')}")
        source = reference(run["log"], path, project)
        transcript = source.read_text(encoding="utf-8", errors="replace")
        validated = validate_transcript(run, transcript)
        record = {"test": run.get("test"), "seed": run.get("seed"), "status": run["status"],
                  "reason": run.get("reason"), "elapsed_seconds": run.get("elapsed_seconds"),
                  "transcript": bundle.add(source, "simulation_log")["bundled_path"], **validated}
        waveform = run.get("waveform_file")
        if waveform:
            wave = reference(waveform, path, project)
            selected = bool(waveform_tests and run.get("test") in waveform_tests and run.get("seed") == waveform_seed)
            artifact = bundle.add(wave, "vcd_waveform", copy=include_waveforms or selected)
            record["waveform"] = artifact["bundled_path"]
            record["waveform_original_path"] = str(wave)
            record["waveform_sha256"] = artifact["sha256"]
        result["runs"].append(record)
    coverage = raw.get("coverage") or {}
    if coverage.get("native_summary"):
        summary_path = reference(coverage["native_summary"], path, project)
        actual = read_json(summary_path)
        bundle.add(summary_path, "measured_coverage_summary")
        functional = actual.get("functional", {})
        eligible = functional.get("all_bins")
        if eligible is not None:
            hit = sum(bool(item["covered"]) for item in eligible)
            if hit != functional.get("bins_hit") or len(eligible) != functional.get("bins_total"):
                raise ValueError(f"Coverage summary counts contradict recorded bins: {summary_path}")
            measured_percent = round(100 * hit / len(eligible), 2) if eligible else None
            if measured_percent != functional.get("bin_hit_percent"):
                raise ValueError(f"Coverage percentage contradicts recorded bins: {summary_path}")
        result["coverage"] = {"functional": {key: functional.get(key) for key in ("metric", "bins_hit", "bins_total", "bin_hit_percent", "status", "by_point")},
                              "code_scopes": actual.get("lcov", {}).get("source_scopes", {}),
                              "uncovered_bins": functional.get("uncovered_bins", []),
                              "summary_input": bundle.seen[summary_path]["bundled_path"]}
        for key in ("merged_database", "lcov"):
            if coverage.get(key):
                artifact = bundle.add(reference(coverage[key], path, project), "coverage_" + key,
                                      copy=key == "lcov" or include_databases)
                result["coverage"][key + "_input"] = artifact["bundled_path"]
                result["coverage"][key + "_sha256"] = artifact["sha256"]
    return result


def source_identity(manifest: Path | None, project: Path, bundle: Bundle) -> dict:
    result = {"manifest": None, "repository": None, "upstream_commit": None, "current_source_files": [],
              "hash_scope": "Current source files at evidence generation time; build-time identity requires the original build logs/report."}
    if manifest:
        metadata = read_json(manifest)
        result.update(manifest=bundle.add(manifest, "source_manifest")["bundled_path"],
                      repository=metadata.get("repository"), upstream_commit=metadata.get("commit"))
        for item in metadata.get("files", []):
            source = (project / item["path"]).resolve()
            if not source.is_relative_to(project):
                raise ValueError(f"Source manifest path escapes the project: {item['path']}")
            content = source.read_bytes()
            blob = hashlib.sha1(b"blob " + str(len(content)).encode("ascii") + b"\0" + content).hexdigest()
            expected = item.get("git_blob_sha1")
            if expected and expected != blob:
                raise ValueError(f"Upstream file no longer matches its pinned Git blob: {item['path']}")
            result["current_source_files"].append({"path": item["path"], "sha256": hashlib.sha256(content).hexdigest(),
                                                   "verified_git_blob_sha1": blob if expected else None})
    for directory in (project / "rtl_fixed", project / "tb"):
        if directory.is_dir():
            for source in sorted(directory.rglob("*.sv")):
                result["current_source_files"].append({"path": source.relative_to(project).as_posix(), "sha256": digest(source)})
    return result


def coverage_svg(reports: list[dict]) -> str:
    rows = []
    for report in reports:
        measured = report.get("coverage")
        if not measured:
            continue
        functional = measured["functional"]
        hit, total = functional.get("bins_hit"), functional.get("bins_total")
        if isinstance(hit, int) and isinstance(total, int) and total > 0:
            rows.append((report["name"] + " · 功能 bins", hit, total, "#4f46e5"))
        rtl = measured["code_scopes"].get("rtl", {})
        hit, total = rtl.get("lines_hit"), rtl.get("lines_total")
        if isinstance(hit, int) and isinstance(total, int) and total > 0:
            rows.append((report["name"] + " · RTL 代码行", hit, total, "#0f766e"))
    height = max(100, 44 + 54 * len(rows))
    pieces = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1000" height="{height}" viewBox="0 0 1000 {height}" role="img" aria-label="实测覆盖率，功能 bins 与代码行分开显示">',
              '<rect width="100%" height="100%" fill="#ffffff"/>']
    if not rows:
        pieces.append('<text x="20" y="50" fill="#64748b" font-family="sans-serif" font-size="16">输入报告未包含可绘制的实测覆盖率。</text>')
    for index, (label, hit, total, color) in enumerate(rows):
        y = 22 + index * 54
        percent = hit / total * 100
        pieces.extend([f'<text x="16" y="{y+18}" font-family="sans-serif" font-size="14" fill="#334155">{html.escape(label)}</text>',
                       f'<rect x="330" y="{y}" width="480" height="26" rx="5" fill="#e2e8f0"/>',
                       f'<rect x="330" y="{y}" width="{480*hit/total:.2f}" height="26" rx="5" fill="{color}"/>',
                       f'<text x="828" y="{y+18}" font-family="sans-serif" font-size="14" fill="#0f172a">{percent:.2f}% · {hit}/{total}</text>'])
    pieces.append("</svg>")
    return "".join(pieces)


def render_html(summary: dict, chart: str) -> str:
    e = lambda value: html.escape(str(value if value is not None else "未记录"))
    totals = summary["totals"]
    cards = [("PASS 运行", totals["pass_runs"]), ("原始失败运行", totals["nonpass_runs"]),
             ("TX 成功比对帧", totals["pass_tx_compares"]), ("RX 成功比对帧", totals["pass_rx_compares"])]
    sections = []
    for report in summary["reports"]:
        badge = " · 预期缺陷复现，原始 FAIL 保留" if report["expected_failure_demonstration"] else ""
        rows = []
        for run in report["runs"]:
            counts = run["scoreboard"] or {}
            style = "ok" if run["status"] == "PASS" else "bad"
            wave = f' · <a href="{e(run["waveform"])}">VCD</a>' if run.get("waveform") else ""
            rows.append(f'<tr><td>{e(run["test"])}</td><td>{e(run["seed"])}</td><td class="{style}">{e(run["status"])}</td><td>{e(counts.get("tx"))} / {e(counts.get("rx"))}</td><td>{e(run["uvm"]["error"])} / {e(run["uvm"]["fatal"])}</td><td><a href="{e(run["transcript"])}">日志</a>{wave}</td></tr>')
        gaps = report.get("coverage", {}) or {}
        gap_rows = "".join(f'<li>{e(item.get("file"))}:{e(item.get("line"))} · {e(item.get("name"))} · hits {e(item.get("hits"))}/{e(item.get("at_least"))}</li>' for item in gaps.get("uncovered_bins", []))
        gaps_html = f'<details><summary>未命中的功能 bins：{len(gaps.get("uncovered_bins", []))}</summary><ul>{gap_rows}</ul></details>' if gaps else ""
        if gaps:
            grouped = gaps.get("functional", {}).get("by_point") or {}
            grouped_rows = "".join(f'<tr><td>{e(point)}</td><td>{e(metrics["bins_hit"])}/{e(metrics["bins_total"])}</td><td>{e(metrics["bin_hit_percent"])}%</td></tr>' for point, metrics in grouped.items())
            gaps_html = f'<details><summary>功能覆盖分组（{len(grouped)} 个 coverpoints / crosses）</summary><div class="scroll"><table><tr><th>分组</th><th>有效 bins 命中</th><th>命中率</th></tr>{grouped_rows}</table></div></details>' + gaps_html
            coverage_links = [("summary_input", "实测覆盖率 JSON"), ("merged_database_input", "原生覆盖率数据库（.dat）"), ("lcov_input", "LCOV 代码覆盖率")]
            links = [f'<a href="{e(gaps[key])}">{label}</a>' for key, label in coverage_links if gaps.get(key)]
            gaps_html = '<p>' + ' · '.join(links) + '</p>' + gaps_html
        snapshot = report.get("build_source_snapshot")
        snapshot_html = ""
        if snapshot:
            location = f'<a href="{e(snapshot["manifest_input"])}">编译时源码快照</a>' if snapshot["manifest_input"] else "编译时源码快照"
            consistency = "与当前工程一致" if snapshot["current_project_sources_match"] else "当前工程已变化，按快照复现历史结果"
            snapshot_html = f'<p>{location} · <code>{e(snapshot["snapshot_sha256"])}</code><br>UVM: {e(snapshot["uvm_version"])} · {e(snapshot["project_files_count"])} 个工程文件 / {e(snapshot["uvm_files_count"])} 个 UVM 文件 · {consistency}</p>'
        binary = report.get("compiled_binary")
        if binary:
            snapshot_html += f'<p>编译产物 SHA-256：<code>{e(binary.get("sha256"))}</code></p>'
        origin = report.get("source_origin")
        if origin:
            snapshot_html += f'<p><a href="{e(origin["map_input"])}">ASCII 仿真暂存映射</a> · {e(origin["verified_files"])} 个文件字节一致，编译快照与映射已交叉校验。</p>'
        sections.append(f'<section><div class="sectionhead"><h2>{e(report["name"])}</h2><span class="tag">{e(report["status"])}{badge}</span></div><p class="meta">RTL: {e(report["rtl_variant"])} · Simulator: {e(report["simulator"])} · {e(report["started_utc"])}</p><pre>{e(report["tool_version"])}</pre><p><a href="{e(report["report_input"])}">原始回归报告</a> · SHA-256 <code>{e(report["report_sha256"])}</code></p>{snapshot_html}<div class="scroll"><table><thead><tr><th>Test</th><th>Seed</th><th>原始状态</th><th>TX / RX 比对</th><th>UVM ERROR / FATAL</th><th>证据</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>{gaps_html}</section>')
    source = summary["source"]
    source_rows = "".join(f'<tr><td>{e(item["path"])}</td><td><code>{e(item["sha256"])}</code></td></tr>' for item in source["current_source_files"])
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>APB UART · 验证证据</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f1f5f9;color:#0f172a;font:15px/1.65 system-ui,"Microsoft YaHei",sans-serif}}header{{padding:54px max(24px,calc((100vw - 1160px)/2));background:#0f172a;color:white}}header p{{color:#cbd5e1;max-width:850px}}.eyebrow{{font-size:13px;letter-spacing:.14em;color:#a5b4fc}}h1{{font-size:38px;margin:12px 0}}main{{max-width:1208px;margin:28px auto;padding:0 24px}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px}}.card,section{{background:#fff;border:1px solid #e2e8f0;border-radius:14px;padding:24px}}.card strong{{display:block;font-size:32px;color:#312e81}}section{{margin-top:22px}}h2{{font-size:21px;margin:0}}.sectionhead{{display:flex;gap:20px;justify-content:space-between;align-items:center}}.tag{{border-radius:6px;padding:3px 9px;background:#eef2ff;color:#3730a3}}.meta,.muted{{color:#64748b}}a{{color:#4338ca}}table{{width:100%;border-collapse:collapse}}th,td{{padding:11px 12px;text-align:left;border-bottom:1px solid #e2e8f0;vertical-align:top}}th{{color:#475569;background:#f8fafc}}.scroll{{overflow:auto}}.ok{{color:#047857;font-weight:650}}.bad{{color:#b91c1c;font-weight:650}}code,pre{{font-family:ui-monospace,Consolas,monospace;font-size:12px}}pre{{white-space:pre-wrap;background:#f8fafc;padding:12px;border-radius:6px}}svg{{width:100%;height:auto}}details{{margin-top:20px}}summary{{cursor:pointer}}footer{{padding:20px 0 40px;color:#64748b}}@media(max-width:760px){{.cards{{grid-template-columns:repeat(2,1fr)}}h1{{font-size:30px}}.sectionhead{{display:block}}.tag{{display:inline-block;margin-top:10px}}}}
</style></head><body><header><div class="eyebrow">APB UART / UVM VERIFICATION</div><h1>可复核的验证结果</h1><p>由实际回归报告、仿真日志和覆盖率数据库生成。功能 bins 与 RTL 代码行分别计量；缺陷复现保留原始 FAIL。TX/RX 汇总仅包含已交叉校验日志的 PASS 运行。</p></header><main><div class="cards">{"".join(f'<div class="card"><span>{e(label)}</span><strong>{e(value)}</strong></div>' for label,value in cards)}</div><section><h2>实测覆盖率</h2><p class="muted">功能指标为有效 bins 的未加权命中率，排除 default / ignore / illegal / 零权重 bins；它与 SystemVerilog 加权 covergroup API 百分比不同。图表按每份真实合并报告展示，不对重叠 bins 相加。</p>{chart}</section>{"".join(sections)}<section><h2>来源与复现</h2><p>上游：{e(source["repository"])}<br>固定提交：<code>{e(source["upstream_commit"])}</code></p><p class="muted">源码哈希记录生成证据时的文件状态。原始报告中的编译命令、工具版本及日志用于复现；这些当前哈希不冒充编译时快照。</p><p><a href="summary.json">机器可读汇总</a> · <a href="inputs.json">输入文件 SHA-256 清单</a> · <a href="coverage.svg">覆盖率 SVG</a></p><details><summary>当前源码 SHA-256（{len(source["current_source_files"])} 个文件）</summary><div class="scroll"><table><tr><th>文件</th><th>SHA-256</th></tr>{source_rows}</table></div></details></section><footer>生成时间 UTC：{e(summary["generated_utc"])} · 原始状态与输入内容未被改写。分享整个目录可同时保留已打包的报告和日志。</footer></main></body></html>'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", type=Path, action="append", required=True)
    parser.add_argument("--expected-fail-report", type=Path, action="append", default=[])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--source-manifest", type=Path)
    parser.add_argument("--include-waveforms", action="store_true", help="Copy VCDs into the portable evidence folder; otherwise record paths and hashes only")
    parser.add_argument("--include-databases", action="store_true", help="Copy merged native .dat coverage databases for independent bin-counter audits")
    parser.add_argument("--waveform-test", action="append", default=[], help="Copy VCDs only for this test at --waveform-seed; repeat to select several (--include-waveforms still copies all)")
    parser.add_argument("--waveform-seed", type=int, default=1, help="Seed for selected --waveform-test VCDs (default: 1)")
    args = parser.parse_args()
    reports = [path.resolve() for path in args.report]
    expected = {path.resolve() for path in args.expected_fail_report}
    output, project = args.out.resolve(), args.project_root.resolve()
    if len(set(reports)) != len(reports):
        parser.error("duplicate --report inputs")
    if args.waveform_seed < 1:
        parser.error("--waveform-seed must be positive")
    if not expected.issubset(set(reports)):
        parser.error("every --expected-fail-report must also be supplied with --report")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error("--out must be a new or empty directory")
    manifest = args.source_manifest or project / "third_party" / "apb_uart_sv" / "manifest.json"
    if args.source_manifest and not manifest.is_file():
        parser.error("--source-manifest file does not exist")
    try:
        bundle = Bundle(output)
        actual = [load_regression(path, path in expected, project, bundle, args.include_waveforms,
                                  args.include_databases, set(args.waveform_test), args.waveform_seed) for path in reports]
        identities = source_identity(manifest.resolve() if manifest.is_file() else None, project, bundle)
        status_counts = Counter(run["status"] for report in actual for run in report["runs"])
        passing = [run for report in actual for run in report["runs"] if run["status"] == "PASS"]
        summary = {"generated_utc": datetime.now(timezone.utc).isoformat(), "reports": actual, "source": identities,
                   "totals": {"report_count": len(actual), "test_seed_runs": sum(status_counts.values()),
                              "pass_runs": status_counts["PASS"], "nonpass_runs": sum(count for status,count in status_counts.items() if status != "PASS"),
                              "status_counts": dict(status_counts),
                              "expected_failure_runs": sum(run["status"] != "PASS" for report in actual if report["expected_failure_demonstration"] for run in report["runs"]),
                              "pass_tx_compares": sum(run["scoreboard"]["tx"] for run in passing),
                              "pass_rx_compares": sum(run["scoreboard"]["rx"] for run in passing)}}
        chart = coverage_svg(actual)
        (output / "coverage.svg").write_text(chart, encoding="utf-8")
        (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output / "inputs.json").write_text(json.dumps(bundle.inputs, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output / "index.html").write_text(render_html(summary, chart), encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, f"EVIDENCE_ERROR: {error}\n")
    print(f"EVIDENCE_BUILT: {summary['totals']['pass_runs']} PASS / {summary['totals']['test_seed_runs']} actual runs; {output / 'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
