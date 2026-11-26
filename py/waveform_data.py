"""Read interface VCD samples and reconstruct APB observations for diagnostics.

The decoder preserves X/Z and uses values strictly before each rising clock
edge, so post-NBA PRDATA changes cannot become the sampled read response.
This is an interface trace viewer, not an alternative verification oracle.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
import hashlib
from pathlib import Path
import re


SIGNALS = (
    "apb.clk", "apb.rst_n", "apb.psel", "apb.penable", "apb.pready",
    "apb.pwrite", "apb.paddr", "apb.pwdata", "apb.prdata", "apb.pslverr",
    "uart.rx", "uart.tx", "uart.irq",
)
SUBSYSTEM_SIGNALS = {
    "control.fault_enable": "Test fault enable",
    "control.ram_en": "RAM enable",
    "control.ram_we": "RAM write",
    "control.ram_addr": "RAM word index",
    "dut.memory_controller_i.busy_q": "MBIST busy",
    "dut.memory_controller_i.done_q": "MBIST done",
    "dut.memory_controller_i.fail_q": "MBIST fail",
    "dut.memory_controller_i.step_q": "March element",
    "dut.memory_controller_i.ram_wdata": "RAM write data",
    "dut.memory_controller_i.ram_rdata": "RAM read response",
}
SCALE_NS = {"s": 1e9, "ms": 1e6, "us": 1e3, "ns": 1.0, "ps": 1e-3, "fs": 1e-6}


def binary_value(value: str, width: int) -> str:
    value = value.lower()
    if not value or any(char not in "01xz" for char in value) or len(value) > width:
        raise ValueError("Invalid VCD binary value")
    fill = value[0] if value[0] in "xz" else "0"
    return value.rjust(width, fill)


def read_interface_vcd(path: Path, *, subsystem: bool = False, signal_names: list[str] | None = None) -> dict:
    path = Path(path)
    selected: dict[str, list[str]] = {}
    signals: dict[str, dict] = {}
    scopes: list[str] = []
    timescale = None
    scale_text = ""
    in_scale = False
    header = True
    timestamp = 0.0
    last_tick = 0
    sample_count = 0
    comment = False
    monitored = (*SIGNALS, *SUBSYSTEM_SIGNALS) if subsystem else SIGNALS
    exact_names = set(signal_names or ())
    with path.open(encoding="utf-8", errors="strict") as stream:
        for raw in stream:
            line = raw.strip()
            if header:
                if line.startswith("$timescale"):
                    in_scale = True
                    scale_text = line
                elif in_scale:
                    scale_text += " " + line
                if in_scale and "$end" in scale_text:
                    match = re.fullmatch(r"\$timescale\s+(\d+)\s*(s|ms|us|ns|ps|fs)\s+\$end", scale_text)
                    if not match or int(match[1]) < 1:
                        raise ValueError("Unsupported VCD timescale")
                    timescale = int(match[1]) * SCALE_NS[match[2]]
                    in_scale = False
                if line.startswith("$scope"):
                    scopes.append(line.split()[2])
                elif line.startswith("$upscope"):
                    if not scopes:
                        raise ValueError("Unbalanced VCD scope")
                    scopes.pop()
                elif line.startswith("$var"):
                    fields = line.split()
                    if len(fields) < 6:
                        raise ValueError("Malformed VCD declaration")
                    full_name = ".".join(scopes + [fields[4]])
                    if signal_names is None:
                        matches = [name for name in monitored if full_name.endswith("." + name) and name not in signals]
                    else:
                        matches = [full_name] if full_name in exact_names else []
                    for name in matches:
                        width = int(fields[2])
                        if not 1 <= width <= 64:
                            raise ValueError(f"Unsupported signal width: {name}")
                        if signal_names is not None and (name in signals or fields[1] in {"real", "realtime", "string", "event"}):
                            raise ValueError(f"Ambiguous or unsupported VCD signal: {name}")
                        signals[name] = {"id": name, "label": SUBSYSTEM_SIGNALS.get(name, name), "width": width,
                                         "full_name": full_name, "events": []}
                        selected.setdefault(fields[3], []).append(name)
                elif line.startswith("$enddefinitions"):
                    if timescale is None:
                        raise ValueError("VCD has no declared timescale")
                    header = False
                continue
            if comment:
                if "$end" in line:
                    comment = False
                continue
            if line.startswith("$comment"):
                comment = "$end" not in line
                continue
            if line.startswith("#"):
                tick = int(line[1:])
                if tick < last_tick:
                    raise ValueError("VCD timestamps are not monotonic")
                last_tick = tick
                timestamp = round(tick * timescale, 9)
                continue
            code = value = None
            if line[:1] in ("b", "B"):
                fields = line[1:].split()
                if len(fields) == 2:
                    value, code = fields
            elif line[:1].lower() in ("0", "1", "x", "z"):
                value, code = line[0], line[1:]
            if code not in selected:
                continue
            for name in selected[code]:
                signal = signals[name]
                normalized = binary_value(value, signal["width"])
                events = signal["events"]
                if events and events[-1][0] == timestamp:
                    events[-1][1] = normalized
                elif not events or events[-1][1] != normalized:
                    events.append([timestamp, normalized])
                    sample_count += 1
                if sample_count > 500_000:
                    raise ValueError("Interface trace exceeds the viewer sample limit; select a shorter VCD")
    if signal_names is not None:
        missing = [name for name in signal_names if not signals.get(name, {}).get("events")]
        if missing:
            raise ValueError(f"Selected VCD signals have no samples: {', '.join(missing)}")
    if header or not signals or not any(s["events"] for s in signals.values()):
        raise ValueError("No interface samples were recorded")
    return {"range": [0.0, timestamp], "unit": "ns", "signals": signals,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _value(signal: dict | None, timestamp: float, before: bool = True) -> str:
    if not signal:
        return "x"
    events = signal["events"]
    times = signal.get("times")
    if times is None:
        times = signal["times"] = [event[0] for event in events]
    index = (bisect_left(times, timestamp) if before else bisect_right(times, timestamp)) - 1
    return events[index][1] if index >= 0 else "x" * signal["width"]


def _number(value: str) -> int | None:
    return int(value, 2) if value and all(bit in "01" for bit in value) else None


def _hex(value: str) -> str:
    number = _number(value)
    return f"0x{number:0{max(1, (len(value) + 3) // 4)}X}" if number is not None else "0b" + value


def apb_transactions(signals: dict) -> list[dict]:
    if not all(name in signals for name in ("apb.clk", "apb.rst_n", "apb.psel", "apb.penable", "apb.pready")):
        return []
    edges = set()
    previous = "x"
    for timestamp, value in signals["apb.clk"]["events"]:
        if previous == "0" and value == "1":
            edges.add(timestamp)
        previous = value
    resets = set()
    previous = "x"
    for timestamp, value in signals["apb.rst_n"]["events"]:
        if previous == "1" and value == "0":
            resets.add(timestamp)
        previous = value
    result = []
    pending = None
    dlab = 0

    def finish(end: float, status: str, values: dict | None = None) -> None:
        nonlocal pending, dlab
        if pending is None:
            return
        pending.update(id=f"apb-{len(result)}", end=end, status=status)
        if values is not None:
            pending["read_data"] = _hex(values["prdata"])
            pending["slverr"] = _number(values["pslverr"])
            if pending["register"] == "LCR" and pending["write"]:
                data = _number(values["pwdata"])
                dlab = (data >> 7) & 1 if data is not None else None
        result.append(pending)
        pending = None

    for timestamp in sorted(edges | resets):
        if timestamp in resets:
            finish(timestamp, "RESET_ABORT")
            dlab = 0
        if timestamp not in edges or _value(signals["apb.rst_n"], timestamp, before=False) != "1":
            continue
        values = {name: _value(signals.get("apb." + name), timestamp) for name in
                  ("psel", "penable", "pready", "pwrite", "paddr", "pwdata", "prdata", "pslverr")}
        if values["psel"] == "1" and values["penable"] == "0":
            if pending:
                finish(timestamp, "INCOMPLETE")
            write = _number(values["pwrite"])
            address = _number(values["paddr"])
            offset = address & 7 if address is not None else None
            register = {2: "FCR" if write else "IIR", 3: "LCR", 4: "MCR", 5: "LSR", 6: "MSR", 7: "SCR"}.get(offset)
            if offset == 0:
                register = "DLL" if dlab == 1 else ("THR" if write else "RBR") if dlab == 0 else "BANK_UNKNOWN"
            elif offset == 1:
                register = "DLM" if dlab == 1 else "IER" if dlab == 0 else "BANK_UNKNOWN"
            pending = {"start": timestamp, "address": _hex(values["paddr"]), "write": bool(write) if write is not None else None,
                       "write_data": _hex(values["pwdata"]), "read_data": None, "wait_cycles": 0,
                       "register": register, "slverr": None}
        elif values["psel"] == "1" and values["penable"] == "1" and pending:
            if values["pready"] == "1":
                error = _number(values["pslverr"])
                finish(timestamp, "OK" if error == 0 else "SLVERR" if error == 1 else "UNKNOWN", values)
            elif values["pready"] == "0":
                pending["wait_cycles"] += 1
        elif pending:
            finish(timestamp, "INCOMPLETE")
    if pending:
        finish(max(event[0] for signal in signals.values() for event in signal["events"]), "INCOMPLETE")
    return result


def mbist_transactions(signals: dict) -> list[dict]:
    """Independently replay the native requests within each observed BUSY interval."""
    busy = "dut.memory_controller_i.busy_q"
    if busy not in signals:
        return []
    waves = signals[busy]["events"]
    clock = signals["apb.clk"]["events"]
    rising = [time for (_, previous), (time, value) in zip(clock, clock[1:]) if previous == "0" and value == "1"]
    # (direction, write sequence). None is a read, integers are data written.
    sequences = ((1, (0,)), (1, (None, 0xffffffff)), (1, (None, 0)),
                 (-1, (None, 0xffffffff)), (-1, (None, 0)), (1, (None,)))
    expected = [(step, address, word is not None, word) for step, (direction, operations) in enumerate(sequences)
                for address in range(64)[::direction] for word in operations]
    observed = []
    for (start, active), (end, _) in zip(waves, waves[1:]):
        if active != "1":
            continue
        operations = []
        for time in rising[bisect_right(rising, start):bisect_right(rising, end)]:
            if _value(signals.get("control.ram_en"), time) != "1":
                continue
            step = _number(_value(signals.get("dut.memory_controller_i.step_q"), time))
            address = _number(_value(signals.get("control.ram_addr"), time))
            write = _value(signals.get("control.ram_we"), time)
            data = _number(_value(signals.get("dut.memory_controller_i.ram_wdata"), time)) if write == "1" else None
            operations.append((step, address, {"0": False, "1": True}.get(write), data))
        reset = _value(signals.get("apb.rst_n"), end, before=False) == "0"
        done = _value(signals.get("dut.memory_controller_i.done_q"), end, before=False) == "1"
        fail = _value(signals.get("dut.memory_controller_i.fail_q"), end, before=False) == "1"
        status = "RESET_ABORT" if reset else "FAIL" if done and fail else "PASS" if done else "INCOMPLETE"
        compared = expected if status == "PASS" else expected[:len(operations)]
        step, address, _, _ = operations[-1] if operations else (None, None, None, None)
        observed.append({"start_ns": start, "end_ns": end, "status": status, "operations": len(operations),
                         "last_step": step, "last_word": address, "march_sequence_matches": operations == compared})
    return observed


def waveform(path: Path, *, id: str, title: str, run_id: str, url: str, uart_registers: bool = True,
             subsystem: bool = False) -> dict:
    trace = read_interface_vcd(path, subsystem=subsystem)
    transactions = apb_transactions(trace["signals"])
    if not uart_registers:
        for event in transactions:
            event.pop("register", None)
    duration = trace["range"][1]
    resets = [time for time, value in trace["signals"].get("apb.rst_n", {}).get("events", []) if value == "0" and time > 0]
    window_start = max(0, resets[0] - 1000) if resets else 0
    window_end = min(duration, window_start + 12000)
    if subsystem:
        failures = trace["signals"].get("dut.memory_controller_i.fail_q", {}).get("events", [])
        first_failure = next((time for time, value in failures if value == "1"), None)
        if first_failure is not None:
            window_start = max(0, first_failure - 250)
            window_end = min(duration, first_failure + 600)
    signals = [{key: signal[key] for key in ("id", "label", "width", "events")}
               for name, signal in trace["signals"].items() if name != "apb.clk"]
    result = {"id": id, "title": title, "run_id": run_id, "unit": "ns", "range": trace["range"],
              "default_window": [window_start, window_end], "signals": signals, "apb_events": transactions,
              "source": {"url": url, "sha256": trace["sha256"],
                         "note": "Actual interface VCD samples. APB observations use pre-edge values; X/Z are preserved. Trace decoding is a diagnostic view, not a checker result."}}
    if subsystem:
        result["mbist_runs"] = mbist_transactions(trace["signals"])
    return result
