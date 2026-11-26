#!/usr/bin/env python3
"""Actually map, time and compare the standalone APB RAM/MBIST controller.

External RAM timing is assumed at the controller ports. STA is one typical,
pre-layout corner; no extracted interconnect, SDF, physical scan placement or
ATPG claim. A deterministic netlist transform replaces mapped DFFs with actual
scan cells from the same Liberty. The dynamic check covers scan shift and the
functional RTL/mapped/scan port equivalence for the recorded smoke scenarios.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from hold_repair import first_path, measure_sta, repair_netlist

ROOT = Path(__file__).resolve().parents[2]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_yosys(path):
    value = str(path)
    require(not any(char in value for char in '"\r\n'), "Unsupported Yosys path")
    return '"' + value + '"'


def insert_scan(netlist, destination, metadata):
    """One deterministic chain of real Nangate SDFF* cells, no RTL alteration."""
    text = netlist.read_text()
    flops = []
    expression = re.compile(r"(?m)^\s*(DFF(?:RS|R|S)?_X[12])\s+(\S+)\s*\((.*?)\);", re.DOTALL)

    def replace(match):
        kind, instance, ports = match.groups()
        require(re.search(r"\.CK\(\s*CLK\s*\)", ports), "Scan insertion requires the single controller clock")
        output = re.search(r"\.Q\(\s*([^()]+?)\s*\)", ports)
        require(output is not None, "Mapped flop has no positive Q pin")
        index = len(flops)
        flops.append({"instance": instance, "original_cell": kind, "scan_cell": "S" + kind,
                      "q": output[1], "index": index})
        return f"\n  S{kind} {instance} ({ports.rstrip()},\n    .SE(SCAN_EN), .SI(_scan_link[{index}])\n  );"

    text, count = expression.subn(replace, text)
    expected = sum(number for kind, number in metadata.items() if kind.startswith("DFF"))
    require(count > 0 and count == expected, "Not every mapped flip-flop entered the scan chain")
    header = re.compile(r"\bmodule\s+apb_ram_mbist\s*\((.*?)\);", re.DOTALL)
    declarations = [f"\n  input SCAN_EN, SCAN_IN; output SCAN_OUT; wire [{count}:0] _scan_link;",
                    "  assign _scan_link[0] = SCAN_IN;", f"  assign SCAN_OUT = _scan_link[{count}];"]
    declarations += [f"  assign _scan_link[{i+1}] = {entry['q']};" for i, entry in enumerate(flops)]
    text, headers = header.subn(lambda match: "module apb_ram_mbist_scan(" + match[1] + ", SCAN_EN, SCAN_IN, SCAN_OUT);" + "\n".join(declarations), text)
    require(headers == 1, "Expected one mapped controller module")
    destination.write_text("// Derived mapped netlist: all DFFs replaced by matching scan cells; no physical reorder or ATPG.\n" + text)
    return {"chains": 1, "length": count, "cells": flops,
            "scope": "Deterministic logical gate-level scan substitution; actual Nangate scan cells, no placement-aware stitching or ATPG"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tools", type=Path, default=Path("/var/tmp/apb-frontend-tools"))
    parser.add_argument("--out", type=Path, required=True, help="Fresh durable output directory")
    parser.add_argument("--work", type=Path, help="Fresh ASCII Linux work directory")
    parser.add_argument("--source", type=Path, default=ROOT / "rtl_subsystem/apb_ram_mbist.sv")
    parser.add_argument("--hold-repair", action="store_true", help="Preserve baseline and insert one guarded BUF_X1 on the measured pending-read hold path")
    a = parser.parse_args()
    output = a.out.resolve()
    started = datetime.now(timezone.utc)
    stamp = started.strftime("%Y%m%dT%H%M%S%fZ")
    work = a.work.resolve() if a.work else Path("/var/tmp") / ("apb-frontend-" + stamp)
    require(not output.exists() or not any(output.iterdir()), "Output must be new or empty")
    require(not work.exists() and str(work).isascii(), "Work must be a fresh ASCII path")
    work.mkdir(parents=True)
    report = {"schema_version": 1, "status": "RUNNING", "started_utc": started.isoformat(), "processes": [],
              "top": "apb_ram_mbist", "scope": "Mapped controller only; external 64x32 RAM is excluded from area and internal timing",
              "limitations": ["Single typical 25C/1.1V Nangate45 corner, ideal clock, pre-layout, no extracted parasitics.",
                              "RAM I/O delay budgets are assumptions, not a characterized memory macro.",
                              "Functional reset is deasserted; reset distribution and recovery/removal are not analyzed.",
                              "Gate simulation is zero-delay and covers the recorded stimuli; it is not formal equivalence or SDF timing simulation.",
                              "Scan is logical standard-cell substitution plus shift/functional testing; no physical DFT closure, ATPG or fault coverage."]}

    def run(command, name, *, env=None):
        log = work / (name + ".log")
        start = time.monotonic()
        with log.open("w") as stream:
            stream.write("COMMAND " + json.dumps([str(arg) for arg in command]) + "\n")
            stream.flush()
            process = subprocess.run(command, cwd=work, stdout=stream, stderr=subprocess.STDOUT,
                                     env=env, timeout=600, check=False)
        report["processes"].append({"command": [str(arg) for arg in command], "returncode": process.returncode,
                                    "elapsed_seconds": round(time.monotonic() - start, 3), "log": log.name})
        require(process.returncode == 0, f"Process failed: {name}; inspect {log}")
        return log.read_text()

    try:
        tools = a.tools.resolve()
        lock = json.loads((ROOT / "flow/frontend/toolchain.lock.json").read_text())
        lib = tools / "NangateOpenCellLibrary_typical.lib"
        expected_lib = next(item for item in lock["artifacts"] if item["file"] == lib.name)
        require(lib.is_file() and sha(lib) == expected_lib["sha256"], "Liberty does not match the pinned public library")
        sta = tools / "opensta-build/sta"
        require(sta.is_file(), "OpenSTA is not built; run scripts/frontend/bootstrap.py --build")
        sources = [a.source.resolve(), ROOT / "flow/frontend/controller.sdc", ROOT / "flow/frontend/controller_sta.tcl",
                   ROOT / "flow/frontend/gate_smoke.sv", ROOT / "flow/frontend/toolchain.lock.json", Path(__file__).resolve(),
                   Path(__file__).with_name("hold_repair.py").resolve()]
        snapshot = [{"path": path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path),
                     "sha256": sha(path), "bytes": path.stat().st_size} for path in sources]
        report["source_snapshot"] = snapshot
        report["library"] = expected_lib
        report["toolchain_lock"] = lock
        report["sta_binary_sha256"] = sha(sta)
        report["versions"] = {"yosys": run(["yosys", "-V"], "version_yosys").splitlines()[1],
                              "opensta": run([str(sta), "-version"], "version_opensta").splitlines()[1],
                              "iverilog": run(["iverilog", "-V"], "version_iverilog").splitlines()[1]}
        for path in sources:
            shutil.copy2(path, work / path.name)
        shutil.copy2(tools / "NANGATE_LICENSE", work / "NANGATE_LICENSE")
        rtl = work / a.source.name
        script = work / "synthesize.ys"
        script.write_text("\n".join([
            f"read_liberty -lib {safe_yosys(lib)}", f"read_verilog -sv {safe_yosys(rtl)}",
            "hierarchy -check -top apb_ram_mbist", "synth -top apb_ram_mbist -flatten -noabc",
            f"dfflibmap -liberty {safe_yosys(lib)}", f"abc -liberty {safe_yosys(lib)}",
            "clean", "check -assert", f"tee -o synthesis_statistics.txt stat -liberty {safe_yosys(lib)}",
            "write_verilog -noattr -noexpr mapped.v", "write_json mapped.json", ""]))
        synth_log = run(["yosys", "-s", str(script)], "synthesis")
        require("ERROR:" not in synth_log and "Found and reported 0 problems" in synth_log, "Synthesis checking did not complete cleanly")
        design = json.loads((work / "mapped.json").read_text())
        counts = Counter(cell["type"] for cell in design["modules"]["apb_ram_mbist"]["cells"].values())
        require(bool(counts) and all(not kind.startswith("$") for kind in counts), "Unmapped internal cells remain")
        area = re.search(r"Chip area for module.*?:\s*([0-9.]+)", synth_log)
        require(area is not None, "Mapped standard-cell area not reported")
        report["synthesis"] = {"cells": dict(sorted(counts.items())), "cell_count": sum(counts.values()),
                               "sequential_cells": sum(number for kind, number in counts.items() if kind.startswith("DFF")),
                               "area_um2": float(area[1]), "scope": "Controller standard-cell area; excludes external RAM, placement, routing and physical overhead"}

        def timing_run(netlist, name, target=None):
            environment = os.environ.copy()
            environment.pop("FRONTEND_HOLD_FROM", None)
            environment.pop("FRONTEND_HOLD_TO", None)
            environment.update(FRONTEND_LIBERTY=str(lib), FRONTEND_NETLIST=str(netlist), FRONTEND_SDC=str(work / "controller.sdc"))
            if target:
                environment.update(FRONTEND_HOLD_FROM=target + "/QN", FRONTEND_HOLD_TO=target + "/D")
            return run([str(sta), "-exit", str(work / "controller_sta.tcl")], name, env=environment)

        paths = {}
        if a.hold_repair:
            report["implementation"] = "hold_repair"
            for before, after in (("mapped.v", "baseline_mapped.v"), ("mapped.json", "baseline_mapped.json"),
                                  ("synthesis_statistics.txt", "baseline_synthesis_statistics.txt")):
                shutil.copy2(work / before, work / after)
            baseline_timing = timing_run(work / "baseline_mapped.v", "baseline_sta")
            baseline_metrics = measure_sta(baseline_timing)
            require(baseline_metrics["status"] == "VIOLATED" and baseline_metrics["setup_worst_slack_ns"] >= 0,
                    "Hold ECO requires an actual hold-only baseline violation")
            paths["baseline"] = {"min": first_path(baseline_timing, "MIN PATHS"), "max": first_path(baseline_timing, "MAX PATHS")}
            for key, path in paths["baseline"].items():
                (work / ("baseline_" + key + "_path.txt")).write_text(path["text"])
            report["baseline"] = {"synthesis": report["synthesis"], "sta": baseline_metrics,
                                  "netlist_sha256": sha(work / "baseline_mapped.v"), "netlist": "baseline_mapped.v",
                                  "sta_log": "baseline_sta.log", "statistics": "baseline_synthesis_statistics.txt",
                                  "sdc_sha256": sha(work / "controller.sdc"), "liberty_sha256": sha(lib)}
            eco = repair_netlist(work / "baseline_mapped.v", work / "mapped.v", baseline_timing)
            eco.update(pre_netlist_sha256=sha(work / "baseline_mapped.v"), post_netlist_sha256=sha(work / "mapped.v"),
                       liberty_sha256=sha(lib), sdc_sha256=sha(work / "controller.sdc"), rtl_sha256=sha(rtl),
                       constraints_unchanged=True, manifest="hold_eco.json", paths_file="timing_paths.json")
            archived = ROOT / "docs/frontend/inputs/mapped.v"
            if archived.is_file():
                eco["archived_baseline_netlist_sha256"] = sha(archived)
                eco["baseline_matches_archived"] = sha(archived) == eco["pre_netlist_sha256"]
                require(eco["baseline_matches_archived"], "Fresh baseline differs from the archived mapped controller")
            eco_script = work / "hold_eco_check.ys"
            eco_script.write_text("\n".join([
                f"read_liberty -lib {safe_yosys(lib)}", "read_verilog mapped.v", "hierarchy -check -top apb_ram_mbist",
                "check -assert", f"tee -o synthesis_statistics.txt stat -liberty {safe_yosys(lib)}", "write_json mapped.json", ""]))
            eco_log = run(["yosys", "-s", str(eco_script)], "hold_eco_check")
            require("Found and reported 0 problems" in eco_log and "ERROR:" not in eco_log, "Fixed mapped netlist did not pass structural checks")
            fixed_design = json.loads((work / "mapped.json").read_text())
            fixed_counts = Counter(cell["type"] for cell in fixed_design["modules"]["apb_ram_mbist"]["cells"].values())
            require(fixed_counts == counts + Counter({"BUF_X1": 1}), "ECO changed cells beyond the single requested buffer")
            fixed_area = re.search(r"Chip area for module.*?:\s*([0-9.]+)", eco_log)
            require(fixed_area is not None, "Fixed cell area was not measured")
            counts = fixed_counts
            report["synthesis"] = {**report["synthesis"], "cells": dict(sorted(counts.items())),
                                   "cell_count": sum(counts.values()), "area_um2": float(fixed_area[1])}
            report["hold_eco"] = eco
        scan = insert_scan(work / "mapped.v", work / "scan_mapped.v", counts)
        capture_mask, capture_expected, capture_source_bits = 0, 0, set()
        for entry in scan["cells"]:
            match = re.fullmatch(r"actual_q\[(\d+)\]", entry["q"])
            if match:
                bit_index = int(match[1])
                capture_source_bits.add(bit_index)
                capture_mask |= 1 << entry["index"]
                capture_expected |= ((0xfffffff7 >> bit_index) & 1) << entry["index"]
        require(capture_source_bits == set(range(32)), "Capture check requires all actual_q data flops")
        (work / "scan_capture.vh").write_text(
            f"localparam [SCAN_LENGTH-1:0] SCAN_CAPTURE_MASK={scan['length']}'h{capture_mask:x};\n"
            f"localparam [SCAN_LENGTH-1:0] SCAN_CAPTURE_EXPECTED={scan['length']}'h{capture_expected:x};\n")
        report["scan"] = scan
        (work / "scan_chain.json").write_text(json.dumps(scan, indent=2) + "\n")
        # These zero-delay models are derived from the same Liberty functions,
        # not handwritten approximations of the mapped cell behavior.
        cells_script = work / "cell_models.ys"
        cells_script.write_text(f"read_liberty -ignore_miss_func -ignore_miss_dir {safe_yosys(lib)}\nwrite_verilog -noattr cells.v\n")
        run(["yosys", "-s", str(cells_script)], "cell_models")
        modeled = set(re.findall(r"\bmodule\s+(\w+)\s*\(", (work / "cells.v").read_text()))
        require(set(counts).issubset(modeled) and {entry["scan_cell"] for entry in scan["cells"]}.issubset(modeled),
                "A used mapped or scan cell lacks its Liberty-derived simulation model")
        library_header = lib.read_text().split("library (", 1)[0]
        model_file = work / "cells.v"
        model_file.write_text(library_header + "\n// Zero-delay functions derived by Yosys from the pinned Liberty; platform license is NANGATE_LICENSE.\n" + model_file.read_text())
        original_text = rtl.read_text()
        renamed, number = re.subn(r"\bmodule\s+apb_ram_mbist\b", "module apb_ram_mbist_rtl", original_text)
        require(number == 1, "Expected one standalone controller module")
        (work / "rtl_reference.sv").write_text(renamed)
        run(["iverilog", "-g2012", "-s", "frontend_gate_smoke", "-Pfrontend_gate_smoke.SCAN_LENGTH=" + str(scan["length"]),
             "-o", "gate_smoke.vvp", "rtl_reference.sv", "mapped.v", "scan_mapped.v", "cells.v", "gate_smoke.sv"], "gate_compile")
        gate_log = run(["vvp", "gate_smoke.vvp"], "gate_simulation")
        passed = re.findall(r"^FRONTEND_GATE_PASS comparisons=(\d+) apb_transactions=(\d+) scan_length=(\d+) scan_bits_checked=(\d+) capture_bits_checked=(\d+)$", gate_log, re.MULTILINE)
        require(len(passed) == 1 and not re.search(r"FATAL:|ERROR:", gate_log), "Gate smoke lacks its unique clean completion")
        comparisons, transactions, chain_length, scan_bits, capture_bits = map(int, passed[0])
        require(comparisons > 1000 and transactions > 100 and chain_length == scan["length"] and scan_bits == 4 * chain_length and capture_bits == 32,
                "Gate/scan comparison or traffic evidence is incomplete")
        require("GATE_CLEAN_MBIST native_ops=640 reads=320 writes=320" in gate_log
                and "GATE_FAULT_MBIST addr=63 step=2 expected=ffffffff actual=fffffff7" in gate_log,
                "Missing clean/fault March observations")
        report["gate_simulation"] = {"status": "PASS", "comparisons": comparisons, "apb_transactions": transactions,
                                     "clean_march_native_operations": 640, "scope": "RTL, mapped gates and scan gates compared at every checked cycle; zero-delay"}
        report["scan"].update(status="PASS", patterns=["all zero", "all one", "one at first chain position", "alternating"], bits_checked=scan_bits,
                             capture_bits_checked=capture_bits, capture_expected="0xfffffff7", capture_scope="actual_q[31:0] after functional-mode March failure capture; other scan bits are not capture-graded")
        timing = timing_run(work / "mapped.v", "sta", report.get("hold_eco", {}).get("target_instance"))
        report["sta"] = measure_sta(timing)
        timing_met = report["sta"]["status"] == "PASS"
        if a.hold_repair:
            paths["fixed"] = {"min": first_path(timing, "MIN PATHS"), "max": first_path(timing, "MAX PATHS"),
                              "target_min": first_path(timing, "ECO TARGET MIN PATH")}
            require(timing_met, "The hold ECO did not close all measured setup and hold paths")
            target = paths["fixed"]["target_min"]
            buffer_pins = [point for point in target["points"] if point["pin"] == report["hold_eco"]["buffer_instance"] + "/Z"
                           and point["cell"] == "BUF_X1"]
            require(len(buffer_pins) == 1 and buffer_pins[0]["delay_ns"] > 0 and target["slack_ns"] >= 0,
                    "Target path does not show the actual positive-delay repair")
            report["hold_eco"].update(buffer_delay_ns=buffer_pins[0]["delay_ns"],
                                      target_slack_after_ns=target["slack_ns"],
                                      global_min_endpoint_after=paths["fixed"]["min"]["endpoint"],
                                      target_path_after=target)
            for key, path in paths["fixed"].items():
                (work / ("fixed_" + key + "_path.txt")).write_text(path["text"])
            (work / "hold_eco.json").write_text(json.dumps(report["hold_eco"], indent=2) + "\n")
            (work / "timing_paths.json").write_text(json.dumps(paths, indent=2) + "\n")
        require(all(sha(path) == item["sha256"] for path, item in zip(sources, snapshot)), "Source changed during execution")
        report["execution_status"] = "PASS"
        report["status"] = "PASS" if timing_met else "TIMING_VIOLATION"
        if not timing_met:
            report["reason"] = "Real controller STA reports a timing violation; constraints and raw paths are retained unchanged"
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        report.update(status="FAIL", reason=str(error))
    finally:
        report["completed_utc"] = datetime.now(timezone.utc).isoformat()
        report["artifacts"] = [{"path": path.name, "sha256": sha(path), "bytes": path.stat().st_size}
                               for path in sorted(work.iterdir()) if path.is_file()]
        (work / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        output.mkdir(parents=True, exist_ok=True)
        for path in work.iterdir():
            if path.is_file():
                shutil.copy2(path, output / path.name)
        print(json.dumps({"status": report["status"], "reason": report.get("reason"), "report": str(output / "report.json")}), flush=True)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
