"""Guarded single-buffer mapped-netlist ECO and actual OpenSTA path parsing.

Only the next-state D input of apb_read_pending_q is changed. RTL and timing
constraints are not modified. The topology and measured worst path must match
the intended synchronous-read-pending feedback before an ECO is permitted.
"""
from pathlib import Path
import re


def require(condition, message):
    if not condition:
        raise ValueError(message)


def instances(text: str) -> dict:
    found = {}
    expression = re.compile(r"(?m)^\s*(\w+)\s+(\S+)\s*\((.*?)\);", re.DOTALL)
    for match in expression.finditer(text):
        kind, name, body = match.groups()
        if kind == "module":
            continue
        ports = re.findall(r"\.(\w+)\(\s*([^()]+?)\s*\)", body)
        require(name not in found and len(ports) == len(dict(ports)), "Ambiguous mapped instance or pin")
        found[name] = {"cell": kind, "pins": dict(ports), "span": match.span(), "text": match[0]}
    return found


def first_path(log: str, section: str) -> dict:
    marker = "=== " + section + " ==="
    require(marker in log, "Missing actual STA path section: " + section)
    body = log.split(marker, 1)[1].split("===", 1)[0]
    blocks = re.split(r"\n(?=Startpoint:)", body.strip())
    require(blocks and blocks[0].startswith("Startpoint:"), "STA section has no timed path")
    text = blocks[0].strip() + "\n"
    start = re.search(r"^Startpoint:\s+(\S+)", text, re.MULTILINE)
    end = re.search(r"^Endpoint:\s+(\S+)", text, re.MULTILINE)
    slack = re.search(r"^\s*(-?[0-9.]+)\s+slack\s+\((MET|VIOLATED)\)", text, re.MULTILINE)
    arrival = re.search(r"^\s*(-?[0-9.]+)\s+data arrival time", text, re.MULTILINE)
    required = re.search(r"^\s*(-?[0-9.]+)\s+data required time", text, re.MULTILINE)
    require(all((start, end, slack, arrival, required)), "Incomplete actual STA path")
    points = [{"delay_ns": float(delay), "time_ns": float(at), "edge": edge,
               "pin": pin, "cell": cell}
              for delay, at, edge, pin, cell in re.findall(
                  r"^\s*(-?[0-9.]+)\s+(-?[0-9.]+)\s+([\^v])\s+(\S+)\s+\((\w+)\)", text, re.MULTILINE)]
    return {"startpoint": start[1], "endpoint": end[1], "slack_ns": float(slack[1]),
            "arrival_ns": float(arrival[1]), "required_ns": float(required[1]),
            "status": slack[2], "points": points, "text": text}


def measure_sta(log: str) -> dict:
    require("FRONTEND_STA_COMPLETE" in log and not re.search(r"^Error:", log, re.MULTILINE), "STA did not complete normally")
    setup = re.findall(r"^worst slack max\s+(-?[0-9.]+)$", log, re.MULTILINE)
    hold = re.findall(r"^worst slack min\s+(-?[0-9.]+)$", log, re.MULTILINE)
    require(len(setup) == len(hold) == 1, "Missing unambiguous global setup/hold slack")
    maximum, minimum = first_path(log, "MAX PATHS"), first_path(log, "MIN PATHS")
    require(maximum["slack_ns"] == float(setup[0]) and minimum["slack_ns"] == float(hold[0]),
            "Worst path and global STA slack disagree")
    return {"status": "PASS" if float(setup[0]) >= 0 and float(hold[0]) >= 0 else "VIOLATED",
            "setup_worst_slack_ns": float(setup[0]), "hold_worst_slack_ns": float(hold[0]),
            "clock_period_ns": 10, "input_delay_max_ns": 2, "input_delay_min_ns": .2,
            "output_delay_max_ns": 2, "output_delay_min_ns": .2, "load_pf": .01,
            "clock_uncertainty_ns": .1,
            "scope": "One typical pre-layout corner; controller external RAM interface budgets only"}


def repair_netlist(source: Path, destination: Path, baseline_log: str) -> dict:
    text = source.read_text()
    cells = instances(text)
    targets = [(name, value) for name, value in cells.items()
               if value["cell"] == "DFFR_X1" and value["pins"].get("Q") == "apb_read_pending_q"]
    require(len(targets) == 1, "Expected one asynchronous-reset apb_read_pending_q flop")
    name, target = targets[0]
    pins = target["pins"]
    require(pins.get("CK") == "CLK" and pins.get("RN") == "RSTN" and pins.get("D") and pins.get("QN"),
            "Pending-read flop clock/reset/pins changed")
    old_net, qn = pins["D"], pins["QN"]
    nand = [(key, value) for key, value in cells.items() if value["cell"] == "NAND2_X1"
            and {value["pins"].get("A1"), value["pins"].get("A2")} == {"RSTN", qn}]
    require(len(nand) == 1, "Expected unique reset/QN NAND feedback")
    nand_name, nand_cell = nand[0]
    nor = [(key, value) for key, value in cells.items() if value["cell"] == "NOR4_X1"
           and value["pins"].get("ZN") == old_net
           and {"PWRITE", "apb_read_pending_q", nand_cell["pins"].get("ZN")}.issubset(
               {value["pins"].get("A1"), value["pins"].get("A2"), value["pins"].get("A3"), value["pins"].get("A4")})]
    require(len(nor) == 1, "Expected unique read-pending NOR next-state driver")
    nor_name, nor_cell = nor[0]
    consumers = [(key, pin) for key, cell in cells.items() for pin, net in cell["pins"].items()
                 if net == old_net and pin not in ("Z", "ZN", "Q", "QN")]
    require(consumers == [(name, "D")], "Old D net has unexpected consumers")
    path = first_path(baseline_log, "MIN PATHS")
    expected_path = [name + "/QN", nand_name + "/ZN", nor_name + "/ZN", name + "/D"]
    actual_path = [point["pin"] for point in path["points"] if not point["pin"].endswith("/CK")]
    require(path["slack_ns"] < 0 and path["startpoint"] == path["endpoint"] == name
            and actual_path == expected_path, "Actual worst hold path differs from the guarded feedback path")
    buffer_name, new_net = "hold_eco_apb_read_pending_d", "hold_eco_apb_read_pending_d_net"
    require(buffer_name not in text and new_net not in text, "ECO identifiers already exist")
    replacement, edits = re.subn(r"\.D\(\s*" + re.escape(old_net) + r"\s*\)", ".D(" + new_net + ")", target["text"])
    require(edits == 1, "Target D connection is ambiguous")
    changed = text[:target["span"][0]] + replacement + text[target["span"][1]:]
    declaration = ("\n  // Hold ECO: one non-inverting buffer on pending-read flop D; RTL/SDC unchanged.\n"
                   f"  wire {new_net};\n  BUF_X1 {buffer_name} (.A({old_net}), .Z({new_net}));\n")
    changed, count = re.subn(r"(\bmodule\s+apb_ram_mbist\s*\([^;]*?\);)", lambda match: match[1] + declaration, changed, count=1)
    require(count == 1, "Expected one mapped module header")
    new_cells = instances(changed)
    require(len(new_cells) == len(cells) + 1 and new_cells[name]["pins"]["D"] == new_net
            and new_cells[buffer_name]["pins"] == {"A": old_net, "Z": new_net}, "ECO topology check failed")
    for key, old_cell in cells.items():
        wanted = {**old_cell["pins"], **({"D": new_net} if key == name else {})}
        require(new_cells[key]["cell"] == old_cell["cell"] and new_cells[key]["pins"] == wanted,
                "ECO changed another cell or pin")
    destination.write_text(changed)
    return {"method": "single_noninverting_buffer_on_flop_D", "target_instance": name, "target_pin": "D",
            "logical_q": "apb_read_pending_q", "old_net": old_net, "new_net": new_net,
            "buffer_instance": buffer_name, "buffer_cell": "BUF_X1", "buffer_input_pin": "A", "buffer_output_pin": "Z",
            "cell_count_before": len(cells), "cell_count_after": len(new_cells),
            "guarded_path_pins": expected_path,
            "guarded_cells": [{"instance": key, "cell": cells[key]["cell"], "pins": cells[key]["pins"]}
                              for key in (name, nand_name, nor_name)],
            "baseline_target_path": path,
            "scope": "Logical standard-cell hold ECO at one typical pre-layout corner; no physical parasitic/clock-tree signoff"}
