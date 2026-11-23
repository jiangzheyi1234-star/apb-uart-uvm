#!/usr/bin/env python3
"""Summarize measured Verilator coverage.dat records, without inferred bins.

Functional results are unweighted eligible bin-hit ratios, not SystemVerilog's
weighted covergroup API percentage. Ignore, illegal, default and zero-weight
bins are listed separately and excluded from that ratio. Code-point results
and LCOV line results are distinct from functional bins.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
from urllib.parse import unquote


KEYS = {"B": "bin", "Bt": "bin_type", "f": "filename", "l": "lineno", "n": "column",
        "o": "comment", "h": "hier", "t": "type", "s": "thresh", "w": "weight",
        "Gw": "group_weight", "C": "cross", "Cb": "cross_bins", "P": "per_instance", "S": "linescov"}
RECORD = re.compile(r"^C '(.+)' (\d+)\s*$")


def parse_records(path: Path) -> list[dict]:
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8", errors="strict").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        match = RECORD.fullmatch(line)
        if not match:
            raise ValueError(f"Unsupported Verilator coverage record at {path}:{number}")
        # Native metadata delimiters are literal control bytes 0x01 / 0x02.
        # Percent escaping applies to field values, so split before unescaping.
        attributes = {}
        for field in match[1].split("\x01"):
            if not field:
                continue
            if "\x02" not in field:
                raise ValueError(f"Malformed coverage metadata at {path}:{number}")
            key, value = field.split("\x02", 1)
            attributes[KEYS.get(key, key)] = unquote(value)
        records.append({"attributes": attributes, "hits": int(match[2])})
    if not records:
        raise ValueError(f"No coverage records in {path}")
    return records


def source_scope(filename: str) -> str:
    path = "/" + filename.replace("\\", "/").lstrip("/")
    if "/rtl/" in path or "/rtl_fixed/" in path:
        return "rtl"
    if "/tb/" in path:
        return "testbench"
    return "library_or_external"


def ratio(hit: int, total: int) -> float | None:
    return round(100 * hit / total, 2) if total else None


def point_hierarchy(hierarchy: str, bin_name: str) -> str:
    """Remove the native bin suffix only when it matches the recorded bin name."""
    suffix = "." + bin_name
    if bin_name and hierarchy.endswith(suffix) and len(hierarchy) > len(suffix):
        return hierarchy[:-len(suffix)]
    return hierarchy


def native_summary(records: list[dict]) -> dict:
    functional = []
    excluded = []
    code = defaultdict(lambda: {"points_seen": 0, "points_total": 0})
    for record in records:
        attributes, hits = record["attributes"], record["hits"]
        if attributes.get("bin"):
            threshold = int(attributes.get("thresh", "1"))
            item = {"file": attributes.get("filename", ""), "line": attributes.get("lineno", ""),
                    "hierarchy": attributes.get("hier", ""), "name": attributes["bin"],
                    "point": attributes.get("comment", ""), "cross": attributes.get("cross", ""),
                    "hits": hits, "at_least": threshold, "covered": hits >= threshold}
            bin_type = attributes.get("bin_type", "normal")
            if bin_type in ("ignore", "illegal", "default"):
                item["exclusion"] = bin_type
                excluded.append(item)
            elif float(attributes.get("weight", "1")) == 0 or float(attributes.get("group_weight", "1")) == 0:
                item["exclusion"] = "zero_weight"
                excluded.append(item)
            else:
                functional.append(item)
        else:
            kind = attributes.get("type") or attributes.get("page", "unknown").split("/")[0]
            group = source_scope(attributes.get("filename", "")) + "/" + kind
            code[group]["points_total"] += 1
            code[group]["points_seen"] += int(hits > 0)
    covered = sum(item["covered"] for item in functional)
    by_point = defaultdict(lambda: {"bins_hit": 0, "bins_total": 0})
    for item in functional:
        hierarchy = point_hierarchy(item["hierarchy"], item["name"])
        point = f"{item['file']}:{item['line']} {hierarchy} {item['point']}".rstrip()
        by_point[point]["bins_total"] += 1
        by_point[point]["bins_hit"] += int(item["covered"])
    for item in by_point.values():
        item["bin_hit_percent"] = ratio(item["bins_hit"], item["bins_total"])
    for item in code.values():
        item["point_seen_percent"] = ratio(item["points_seen"], item["points_total"])
    return {
        "functional": {"status": "MEASURED" if functional else "NO_FUNCTIONAL_BIN_RECORDS",
                       "metric": "Unweighted eligible bin-hit ratio; not the weighted SystemVerilog covergroup API percentage",
                       "bins_hit": covered, "bins_total": len(functional), "bin_hit_percent": ratio(covered, len(functional)),
                       "by_point": dict(sorted(by_point.items())), "uncovered_bins": [item for item in functional if not item["covered"]],
                       "all_bins": functional, "excluded_bins": excluded},
        "code_points": {"metric": "Instrumented native counters with at least one observed hit; separate from line and functional coverage",
                        "by_source_scope_and_type": dict(sorted(code.items()))},
        "record_count": len(records),
    }


def lcov_summary(path: Path) -> dict:
    files = {}
    current = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("SF:"):
            current = line[3:]
            files.setdefault(current, {"lines_hit": 0, "lines_total": 0, "branches_hit": 0, "branches_total": 0})
        elif current and line.startswith("DA:"):
            _, hits, *_ = line[3:].split(",")
            files[current]["lines_total"] += 1
            files[current]["lines_hit"] += int(int(hits) > 0)
        elif current and line.startswith("BRDA:"):
            hits = line[5:].split(",")[-1]
            files[current]["branches_total"] += 1
            files[current]["branches_hit"] += int(hits != "-" and int(hits) > 0)
        elif line == "end_of_record":
            current = None
    scopes = defaultdict(lambda: {"lines_hit": 0, "lines_total": 0, "branches_hit": 0, "branches_total": 0})
    for filename, metrics in files.items():
        for key in scopes[source_scope(filename)]:
            scopes[source_scope(filename)][key] += metrics[key]
        metrics["line_percent"] = ratio(metrics["lines_hit"], metrics["lines_total"])
    for metrics in scopes.values():
        metrics["line_percent"] = ratio(metrics["lines_hit"], metrics["lines_total"])
        metrics["branch_percent"] = ratio(metrics["branches_hit"], metrics["branches_total"])
    return {"files": files, "source_scopes": dict(scopes), "metric": "LCOV executable line and branch coverage"}


def generate_report(database: Path, output: Path, lcov: Path | None = None) -> dict:
    summary = native_summary(parse_records(database))
    summary["database"] = str(database.resolve())
    if lcov:
        summary["lcov"] = lcov_summary(lcov)
    output.mkdir(parents=True, exist_ok=True)
    (output / "coverage_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    functional = summary["functional"]
    lines = ["# Measured Verilator coverage", "", functional["metric"], "",
             f"Eligible bins hit: {functional['bins_hit']} / {functional['bins_total']} ({functional['bin_hit_percent']}%).", "",
             f"Excluded bins: {len(functional['excluded_bins'])} (ignore / illegal / default / zero weight).", "",
             "| Coverpoint location / hierarchy | Bins hit | Bins total | Bin hit ratio |",
             "| --- | ---: | ---: | ---: |"]
    for point, metrics in functional["by_point"].items():
        lines.append(f"| {point.replace('|', '/')} | {metrics['bins_hit']} | {metrics['bins_total']} | {metrics['bin_hit_percent']}% |")
    if summary.get("lcov"):
        lines.extend(["", "LCOV executable code coverage:", "", "| Scope | Lines hit | Lines total | Line coverage |", "| --- | ---: | ---: | ---: |"])
        for scope, metrics in summary["lcov"]["source_scopes"].items():
            lines.append(f"| {scope} | {metrics['lines_hit']} | {metrics['lines_total']} | {metrics['line_percent']}% |")
    lines.extend(["", "Uncovered eligible bins:", "", "| Location | Bin | Hits | Required |", "| --- | --- | ---: | ---: |"])
    for item in functional["uncovered_bins"]:
        lines.append(f"| {item['file']}:{item['line']} {item['hierarchy']} | {item['name']} | {item['hits']} | {item['at_least']} |")
    lines.extend(["", "Only counters present in the native database are reported. No uninstrumented requirements are counted as covered.", ""])
    (output / "coverage_summary.md").write_text("\n".join(lines), encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("database", type=Path, help="Merged native Verilator coverage.dat")
    parser.add_argument("--lcov", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = generate_report(args.database, args.out, args.lcov)
    except (OSError, ValueError) as error:
        parser.exit(2, f"COVERAGE_REPORT_ERROR: {error}\n")
    print(f"COVERAGE_REPORTED: {summary['record_count']} measured records; {args.out / 'coverage_summary.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
