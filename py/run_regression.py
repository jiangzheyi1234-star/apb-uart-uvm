#!/usr/bin/env python3
"""Compile once and run APB UART UVM tests with Questa, VCS or Verilator.

Run from any directory. A PASS requires a normal process exit, a scoreboard
completion marker and a UVM summary with zero errors/fatals. Dry runs never pass.
Only Python's standard library is needed.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
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


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TESTS = (
    "uart_smoke_test", "uart_fifo_boundary_test", "uart_error_test", "uart_reset_test"
)
DEFAULT_PROTOCOL_TESTS = (
    "apb_wait_state_test", "apb_reset_abort_test", "apb_timeout_control_test"
)
DEFAULT_SUBSYSTEM_TESTS = (
    "subsystem_apb_test", "subsystem_mbist_test", "subsystem_mbist_fault_test", "subsystem_mbist_reset_test"
)
SUITE_PASS_MARKERS = {
    "uart": "UART_UVM_TEST_PASS", "apb_protocol": "APB_AGENT_TEST_PASS", "subsystem": "SUBSYSTEM_UVM_TEST_PASS"
}
SUITE_DEFAULT_TESTS = {"uart": DEFAULT_TESTS, "apb_protocol": DEFAULT_PROTOCOL_TESTS, "subsystem": DEFAULT_SUBSYSTEM_TESTS}
SUITE_TITLES = {
    "uart": "APB UART UVM regression", "apb_protocol": "APB agent protocol regression",
    "subsystem": "APB UART and RAM/MBIST subsystem regression",
}
PASS_MARKER = re.compile(
    r"^\s*(?:#\s*)?UVM_INFO\b[^\r\n]*\[UART_UVM_TEST_PASS\]", re.MULTILINE
)
UVM_MESSAGE_ERROR = re.compile(
    r"^\s*(?:#\s*)?UVM_(?:ERROR|FATAL)\b(?!\s*:)", re.MULTILINE
)
SIM_ERROR = re.compile(
    r"^\s*(?:#\s*)?(?:\*\*\s*(?:Error|Fatal)(?:\s*\([^\r\n]*?\))?:|(?:Error|Fatal)-\[|%Error(?:-[^:\r\n]+)?:|FATAL:)",
    re.MULTILINE,
)


@dataclass
class Outcome:
    status: str
    reason: str
    uvm_errors: int | None = None
    uvm_fatals: int | None = None


@dataclass
class ProcessResult:
    command: list[str]
    returncode: int | None
    timed_out: bool
    elapsed_seconds: float
    log: str


def classify_log(text: str, returncode: int | None, timed_out: bool = False,
                 pass_marker: str = "UART_UVM_TEST_PASS") -> Outcome:
    """Reject empty, truncated, simulator-error and false-success transcripts."""
    counts: dict[str, int | None] = {}
    for severity in ("ERROR", "FATAL"):
        matches = re.findall(
            rf"^\s*(?:#\s*)?UVM_{severity}\s*:\s*(\d+)\s*$", text, re.MULTILINE
        )
        # Every summary must be clean, including a repeated/earlier summary.
        counts[severity] = max(map(int, matches)) if matches else None
    errors, fatals = counts["ERROR"], counts["FATAL"]
    if timed_out:
        return Outcome("TIMEOUT", "Simulator exceeded the wall-clock timeout", errors, fatals)
    if returncode != 0:
        return Outcome("FAIL", f"Simulator exited with code {returncode}", errors, fatals)
    if SIM_ERROR.search(text):
        return Outcome("FAIL", "Simulator reported an error or fatal", errors, fatals)
    if UVM_MESSAGE_ERROR.search(text) or (errors or 0) or (fatals or 0):
        return Outcome("FAIL", "UVM reported an error or fatal", errors, fatals)
    if errors is None or fatals is None:
        return Outcome("FAIL", "Missing complete UVM severity summary", errors, fatals)
    completion = re.compile(r"^\s*(?:#\s*)?UVM_INFO\b[^\r\n]*\[" + re.escape(pass_marker) + r"\]", re.MULTILINE)
    if not completion.search(text):
        return Outcome("FAIL", f"Missing completion marker {pass_marker}", errors, fatals)
    return Outcome("PASS", "Completion marker observed; UVM error/fatal counts are zero", errors, fatals)


def run_process(command: list[str], cwd: Path, log: Path, timeout: float) -> ProcessResult:
    """Keep shell=False so test names, paths and seeds cannot become shell code."""
    start = time.monotonic()
    timed_out = False
    returncode = None
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as output:
        output.write("COMMAND " + json.dumps(command, ensure_ascii=False) + "\n")
        output.flush()
        process = subprocess.Popen(
            command, cwd=cwd, stdout=output, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, shell=False,
            start_new_session=os.name != "nt",
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
        )
        try:
            returncode = process.wait(timeout=timeout)
        except (subprocess.TimeoutExpired, KeyboardInterrupt) as error:
            timed_out = isinstance(error, subprocess.TimeoutExpired)
            # Simulators may launch worker children; kill the process tree.
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
                )
            else:
                import signal
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            if process.poll() is None:
                process.kill()
            returncode = process.wait()
            if isinstance(error, KeyboardInterrupt):
                raise
    return ProcessResult(command, returncode, timed_out, round(time.monotonic() - start, 3), str(log))


def read_log(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def find_uvm_home(explicit: Path | None, vlog: str) -> Path | None:
    """Find the source include directory accompanying Questa's bundled UVM 1.2."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(explicit)
    elif os.environ.get("UVM_HOME"):
        candidates.append(Path(os.environ["UVM_HOME"]))
    else:
        for key in ("QUESTA_HOME", "MTI_HOME", "MODEL_TECH"):
            if os.environ.get(key):
                base = Path(os.environ[key])
                candidates.extend((base / "verilog_src" / "uvm-1.2", base.parent / "verilog_src" / "uvm-1.2"))
        installed = shutil.which(vlog)
        if installed:
            candidates.append(Path(installed).resolve().parent.parent / "verilog_src" / "uvm-1.2")
    for candidate in candidates:
        for source in (candidate / "src", candidate):
            if (source / "uvm_macros.svh").is_file():
                return source.resolve()
    return None


def find_source_uvm(explicit: Path | None) -> Path | None:
    """Verilator compiles the selected UVM source rather than a vendor library."""
    candidates = [explicit] if explicit else (
        [Path(os.environ["UVM_HOME"])] if os.environ.get("UVM_HOME") else [
            ROOT / ".tools" / "uvm-2020-3.2-src", ROOT / ".tools" / "uvm-1.2-src"
        ]
    )
    for candidate in candidates:
        for source in (candidate / "src", candidate):
            if (source / "uvm_pkg.sv").is_file() and (source / "uvm_macros.svh").is_file():
                return source.resolve()
    return None


def source_list(args: argparse.Namespace) -> Path:
    suite = getattr(args, "suite", "uart")
    if suite == "apb_protocol":
        return ROOT / "sim" / "files_protocol.f"
    if suite == "subsystem":
        return ROOT / "sim" / "files_subsystem.f"
    return ROOT / "sim" / ("files_fixed.f" if args.rtl == "fixed" else "files.f")


def file_digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def capture_source_manifest(args: argparse.Namespace, uvm_src: Path | None) -> dict:
    """Capture the actual selected source contents immediately before compilation."""
    suite = getattr(args, "suite", "uart")
    variant = (args.rtl or "upstream") if suite == "uart" else "fixed" if suite == "subsystem" else None
    directories = [ROOT / "tb"]
    if variant:
        directories.append(ROOT / ("rtl_fixed" if variant == "fixed" else "rtl"))
    if suite == "subsystem":
        directories.append(ROOT / "rtl_subsystem")
    sources = {source_list(args)}
    for directory in directories:
        if directory.is_dir():
            sources.update(path for path in directory.rglob("*") if path.is_file() and path.suffix in (".sv", ".svh"))
    if suite != "subsystem":
        # Keep the historical UART and discrete APB snapshots independent of this extension.
        sources = {path for path in sources if not path.is_relative_to(ROOT / "tb" / "subsystem")}
    project_files = [{"path": path.relative_to(ROOT).as_posix(), "sha256": file_digest(path), "bytes": path.stat().st_size}
                     for path in sorted(sources)]
    snapshot = {"captured_utc": datetime.now(timezone.utc).isoformat(), "captured_before_compile": True,
                "algorithm": "sha256", "suite": suite, "rtl_variant": variant, "project_files": project_files,
                "uvm_files": [], "uvm_archives": [], "uvm_version": None}
    upstream = ROOT / "third_party" / "apb_uart_sv" / "manifest.json"
    if variant and upstream.is_file():
        metadata = json.loads(read_log(upstream))
        snapshot["upstream"] = {"repository": metadata.get("repository"), "commit": metadata.get("commit"),
                                "manifest_sha256": file_digest(upstream)}
    if uvm_src:
        snapshot["uvm_source_root"] = str(uvm_src)
        snapshot["uvm_files"] = [{"path": path.relative_to(uvm_src).as_posix(), "sha256": file_digest(path), "bytes": path.stat().st_size}
                                 for path in sorted(uvm_src.rglob("*")) if path.is_file() and path.suffix in (".sv", ".svh")]
        for package in (uvm_src, uvm_src.parent):
            for name in ("README.md", "README.txt", "README"):
                readme = package / name
                if readme.is_file():
                    match = re.search(r"(?mi)^#+\s*Kit version\s*\n\s*([^\r\n]+)", read_log(readme))
                    if match:
                        snapshot["uvm_version"] = match[1].strip()
            for name in (package.name, package.name.removesuffix("-src")):
                for extension in (".tar.gz", ".zip"):
                    archive = package.parent / (name + extension)
                    if archive.is_file() and not any(item["path"] == str(archive) for item in snapshot["uvm_archives"]):
                        snapshot["uvm_archives"].append({"path": str(archive), "sha256": file_digest(archive), "bytes": archive.stat().st_size})
        if snapshot["uvm_version"] is None:
            version_header = uvm_src / "macros" / "uvm_version_defines.svh"
            if version_header.is_file():
                defines = dict(re.findall(r"(?m)^`define\s+(UVM_(?:MAJOR|MINOR|FIX)_REV)\s+([^\r\n]+)", read_log(version_header)))
                snapshot["uvm_version_defines"] = defines
    else:
        snapshot["uvm_source_note"] = "Simulator bundled/precompiled UVM; source contents not available to the runner"
    stable = {"project_files": snapshot["project_files"], "uvm_files": snapshot["uvm_files"], "rtl_variant": variant}
    snapshot["snapshot_sha256"] = hashlib.sha256(json.dumps(stable, sort_keys=True).encode("utf-8")).hexdigest()
    return snapshot


def simulator_version_command(args: argparse.Namespace) -> list[str]:
    if args.sim == "questa":
        return [args.vsim, "-version"]
    if args.sim == "vcs":
        return [args.vcs, "-ID"]
    return [args.verilator, "--version"]


def compiled_binary_path(args: argparse.Namespace, output: Path) -> Path | None:
    build = args.build_dir or output / "build"
    return build / "Vtb_top" if args.sim == "verilator" else build / "simv" if args.sim == "vcs" else None


def plans(args: argparse.Namespace, output: Path, uvm_src: Path | None) -> tuple[list[list[str]], list[dict]]:
    build = args.build_dir or output / "build"
    file_list = source_list(args)
    includes = [f"+incdir+{ROOT / 'tb'}"]
    includes.extend(f"+incdir+{ROOT / 'tb' / name}" for name in (
        "apb_agent", "uart_agent", "scoreboard", "coverage", "env", "seq", "test"
    ))
    if args.sim == "questa":
        work = build / "work"
        uvm = [f"+incdir+{uvm_src or '<UVM_HOME>/src'}"]
        if args.compile_uvm_source:
            uvm.extend(["+define+UVM_NO_DPI", str((uvm_src or Path("<UVM_HOME>/src")) / "uvm_pkg.sv")])
            lib = []
        else:
            lib = ["-L", args.questa_uvm_lib]
        compile_commands = [
            [args.vlib, str(work)],
            [args.vlog, "-sv", "-timescale", "1ns/1ps", "-work", str(work), *lib, *includes, *uvm,
             *(["+cover=bcesft"] if args.coverage else []), "-f", str(file_list)],
        ]
    elif args.sim == "vcs":
        compile_commands = [[
            args.vcs, "-full64", "-sverilog", "-ntb_opts", "uvm-1.2", "-timescale=1ns/1ps",
            *includes, "-f", str(file_list), "-top", "tb_top",
            "-Mdir=" + str(build / "csrc"), "-o", str(build / "simv"),
            *(["-cm", "line+cond+tgl+branch+assert"] if args.coverage else []),
            *(["-debug_access+all"] if args.trace else []),
        ]]
    else:
        source = uvm_src or Path("<UVM_HOME>/src")
        compile_commands = [[
            args.verilator, "--binary", "--timing", "--assert", "--top-module", "tb_top",
            "--timescale", "1ns/1ps", "--Mdir", str(build / "obj_dir"), "-o", str(build / "Vtb_top"),
            "-j", str(args.jobs), "-Wno-fatal", "+define+UVM_NO_DPI", "+define+UVM_REGEX_NO_DPI",
            *includes, f"+incdir+{source}", str(source / "uvm_pkg.sv"), "-f", str(file_list),
            *(["--coverage"] if args.coverage else []), *(["--trace"] if args.trace else []),
            *args.verilator_arg,
        ]]
    runs = []
    defaults = SUITE_DEFAULT_TESTS[getattr(args, "suite", "uart")]
    for test in args.test or defaults:
        for seed in args.seeds:
            directory = output / f"{test}_seed_{seed}"
            if args.sim == "questa":
                # Forward slashes and Tcl braces support Windows paths with spaces.
                coverage = directory / "coverage.ucdb"
                do = (
                    "coverage save -onexit {" + coverage.as_posix() + "}; "
                    if args.coverage else ""
                ) + "run -all; quit -f"
                command = [
                    args.vsim, "-c", "-lib", str(work), *lib, "tb_top", "-sv_seed", str(seed),
                    f"+UVM_TESTNAME={test}", "-l", str(directory / "transcript.log"),
                    *(["-coverage"] if args.coverage else []), "-do", do,
                    *(["-voptargs=+acc"] if args.trace else []),
                ]
                coverage_path = directory / "coverage.ucdb"
            elif args.sim == "vcs":
                command = [
                    str(build / "simv"), f"+UVM_TESTNAME={test}", f"+ntb_random_seed={seed}",
                    *(["-cm", "line+cond+tgl+branch+assert", "-cm_dir", str(directory / "coverage.vdb")] if args.coverage else []),
                ]
                coverage_path = directory / "coverage.vdb"
            else:
                coverage_path = directory / "coverage.dat"
                command = [str(build / "Vtb_top"), f"+UVM_TESTNAME={test}", f"+verilator+seed+{seed}",
                           *([f"+verilator+coverage+file+{coverage_path}"] if args.coverage else [])]
            if getattr(args, "suite", "uart") == "uart" and args.rtl == "fixed":
                command.append("+RTL_FIXED=1")
            if args.trace:
                command.extend(["+TRACE", f"+VCD_FILE={directory / 'waves.vcd'}"])
            runs.append({"test": test, "seed": seed, "command": command, "directory": str(directory),
                         "coverage_file": str(coverage_path) if args.coverage else None,
                         "waveform_file": str(directory / "waves.vcd") if args.trace else None})
    return compile_commands, runs


def summarize_lcov(path: Path) -> dict:
    """Report measured code line/branch coverage, separately from covergroup bins."""
    files = {}
    current = None
    for line in read_log(path).splitlines():
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
    for metrics in files.values():
        metrics["line_percent"] = round(100 * metrics["lines_hit"] / metrics["lines_total"], 2) if metrics["lines_total"] else None
    return {"files": files, "scope": "LCOV code lines and branches; functional covergroup bins are in coverage.dat"}


def export_verilator_coverage(args: argparse.Namespace, output: Path, report: dict) -> bool:
    """Merge only successful runs; retain every raw database for inspection."""
    inputs = [run["coverage_file"] for run in report["runs"] if run["status"] == "PASS" and run.get("coverage_file")]
    report["coverage"] = {"status": "SKIPPED", "inputs": inputs, "commands": [],
                          "scope": "Only PASS runs contribute to merged coverage"}
    if not inputs:
        return True
    directory = output / "coverage"
    directory.mkdir()
    commands = [
        [args.verilator_coverage, "--write", str(directory / "merged.dat"), *inputs],
        [args.verilator_coverage, "--write-info", str(directory / "coverage.info"), *inputs],
        [args.verilator_coverage, "--annotate", str(directory / "annotated"), "--annotate-points", str(directory / "merged.dat")],
        [sys.executable, str(Path(__file__).with_name("report_coverage.py")), str(directory / "merged.dat"),
         "--lcov", str(directory / "coverage.info"), "--out", str(directory)],
    ]
    for index, command in enumerate(commands):
        result = run_process(command, ROOT, directory / f"export_{index}.log", args.build_timeout)
        report["coverage"]["commands"].append(asdict(result))
        if result.timed_out or result.returncode != 0 or SIM_ERROR.search(read_log(result.log)):
            report["coverage"]["status"] = "FAIL"
            report["coverage"]["reason"] = f"Coverage export failed; inspect {result.log}"
            return False
    report["coverage"].update({"status": "EXPORTED", "merged_database": str(directory / "merged.dat"),
                              "lcov": str(directory / "coverage.info"), "annotated_sources": str(directory / "annotated")})
    if not (directory / "merged.dat").is_file() or not (directory / "coverage.info").is_file():
        report["coverage"].update({"status": "FAIL", "reason": "Coverage tool returned without producing requested files"})
        return False
    report["coverage"]["code_summary"] = summarize_lcov(directory / "coverage.info")
    native = directory / "coverage_summary.json"
    if not native.is_file():
        report["coverage"].update({"status": "FAIL", "reason": "Measured native coverage summary was not produced"})
        return False
    report["coverage"]["native_summary"] = str(native)
    report["coverage"]["functional_bins"] = json.loads(read_log(native))["functional"]
    return True


def write_reports(output: Path, report: dict) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = [
        "# " + SUITE_TITLES[report.get("suite", "uart")],
        "", f"Status: **{report['status']}**", "",
        f"Simulator: {report['simulator']}", f"Started (UTC): {report['started_utc']}", "",
    ]
    if report.get("rtl_variant"):
        lines.extend([f"RTL variant: {report['rtl_variant']}", ""])
    if report.get("reason"):
        lines.extend([report["reason"], ""])
    lines.extend(["| Test | Seed | Status | Errors | Fatals | Reason |", "| --- | ---: | --- | ---: | ---: | --- |"])
    for result in report["runs"]:
        lines.append(
            f"| {result['test']} | {result['seed']} | {result['status']} | "
            f"{result.get('uvm_errors', '')} | {result.get('uvm_fatals', '')} | {result.get('reason', '')} |"
        )
    artifacts = [result for result in report["runs"] if result.get("coverage_file") or result.get("waveform_file")]
    if artifacts:
        lines.extend(["", "| Test / seed | Coverage database | VCD waveform |", "| --- | --- | --- |"])
        for result in artifacts:
            lines.append(f"| {result['test']} / {result['seed']} | {result.get('coverage_file') or ''} | {result.get('waveform_file') or ''} |")
    if report.get("coverage"):
        coverage = report["coverage"]
        lines.extend(["", f"Merged coverage: {coverage['status']}", coverage["scope"]])
        for key in ("merged_database", "lcov", "annotated_sources", "reason"):
            if coverage.get(key):
                lines.append(f"{key}: {coverage[key]}")
    lines.extend(["", "PASS requires normal exit, the selected suite's completion marker and a clean UVM summary.",
                  "DRY_RUN only lists commands; no RTL simulation or coverage measurement was performed.",
                  "Coverage databases, when requested, belong to individual runs and require the simulator's reporting tools.", ""])
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--sim", choices=("questa", "vcs", "verilator"), default="questa")
    p.add_argument("--suite", choices=tuple(SUITE_DEFAULT_TESTS), default="uart", help="Select UART, independent APB protocol, or RAM/MBIST subsystem")
    p.add_argument("--rtl", choices=("upstream", "fixed"), help="UART defaults to upstream RTL; subsystem uses fixed RTL")
    p.add_argument("--test", action="append", help="UVM test class; repeat to select several (default: suite's positive tests)")
    p.add_argument("--seeds", type=int, nargs="+", default=[1], help="Positive seeds, one run per test and seed")
    p.add_argument("--out", type=Path, help="Fresh output directory; defaults to results/<UTC timestamp>")
    p.add_argument("--build-dir", type=Path, help="Optional persistent build directory (e.g. Linux /var/tmp/uart-build); the real build command still runs every time")
    p.add_argument("--timeout", type=float, default=120.0, help="Wall-clock seconds per simulation (default: 120)")
    p.add_argument("--build-timeout", type=float, default=900.0)
    p.add_argument("--dry-run", action="store_true", help="Write command plans only; status is DRY_RUN, never PASS")
    p.add_argument("--coverage", action="store_true", help="Save per-run simulator coverage databases")
    p.add_argument("--trace", action="store_true", help="Save a per-run VCD waveform using the testbench dump hook")
    p.add_argument("--uvm-home", type=Path, help="UVM root (or src directory); also reads UVM_HOME. Recent Verilator officially supports UVM2020 3.2.")
    p.add_argument("--jobs", type=int, default=2, help="Verilator C++ build parallelism (default: 2)")
    p.add_argument("--verilator-arg", action="append", default=[], help="Extra Verilator build argument (repeat; use --verilator-arg=--flag)")
    p.add_argument("--verilator-coverage", default="verilator_coverage", help="Path to verilator_coverage executable")
    p.add_argument("--questa-uvm-lib", default="mtiUvm", help="Questa precompiled UVM library (default: mtiUvm)")
    p.add_argument("--compile-uvm-source", action="store_true", help="Questa: compile UVM_HOME/src/uvm_pkg.sv with UVM_NO_DPI")
    for executable in ("vlib", "vlog", "vsim", "vcs", "verilator"):
        p.add_argument("--" + executable, default=executable, help=f"Path to {executable} executable")
    return p


def main(argv: list[str] | None = None) -> int:
    arg_parser = parser()
    args = arg_parser.parse_args(argv)
    if args.suite == "subsystem" and args.rtl == "upstream":
        arg_parser.error("--suite subsystem requires --rtl fixed")
    args.rtl = args.rtl or ("fixed" if args.suite == "subsystem" else "upstream")
    if args.build_dir:
        args.build_dir = args.build_dir.resolve()
        if args.build_dir.exists() and not args.build_dir.is_dir():
            arg_parser.error("--build-dir must be a directory")
    if args.timeout <= 0 or args.build_timeout <= 0 or args.jobs < 1:
        arg_parser.error("timeouts and --jobs must be positive")
    if any(seed < 1 or seed > 2147483647 for seed in args.seeds):
        arg_parser.error("seeds must be in 1..2147483647")
    if len(args.seeds) != len(set(args.seeds)) or (args.test and len(args.test) != len(set(args.test))):
        arg_parser.error("duplicate tests or seeds would overwrite run artifacts")
    if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", test) for test in (args.test or [])):
        arg_parser.error("test names must be SystemVerilog class identifiers")
    if args.compile_uvm_source and args.sim != "questa":
        arg_parser.error("--compile-uvm-source is only supported for Questa")
    if args.suite == "apb_protocol" and args.coverage:
        arg_parser.error("--coverage exports UART functional coverage; the protocol suite uses APB_AGENT_STATS and optional --trace")
    output = (args.out or ROOT / "results" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")).resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        arg_parser.error("--out must be an empty or new directory to prevent stale PASS logs or coverage")
    # Tcl braces are used around Questa coverage paths.
    if args.coverage and args.sim == "questa" and any(c in str(output) for c in "{}\r\n"):
        arg_parser.error("Questa coverage output paths cannot contain braces or newlines")
    output.mkdir(parents=True, exist_ok=True)
    report = {"status": "ERROR", "simulator": args.sim, "suite": args.suite,
              "rtl_variant": None if args.suite == "apb_protocol" else args.rtl,
              "completion_marker": SUITE_PASS_MARKERS[args.suite],
              "source_file_list": str(source_list(args)),
              "build_directory": str(args.build_dir or output / "build"),
              "started_utc": datetime.now(timezone.utc).isoformat(), "build": [], "runs": []}
    uvm_src = (find_uvm_home(args.uvm_home, args.vlog) if args.sim == "questa" else
               find_source_uvm(args.uvm_home) if args.sim == "verilator" else None)
    report["uvm_source"] = str(uvm_src) if uvm_src else None
    commands, runs = plans(args, output, uvm_src)
    report["planned_build_commands"] = commands
    if args.dry_run:
        report["status"] = "DRY_RUN"
        report["runs"] = [dict(run, status="DRY_RUN", reason="Command planned; simulator was not executed") for run in runs]
        write_reports(output, report)
        print(f"DRY_RUN: {len(runs)} planned runs; no simulation performed. {output / 'report.json'}")
        return 0
    required = ([args.vlib, args.vlog, args.vsim] if args.sim == "questa" else
                [args.verilator, *([args.verilator_coverage] if args.coverage else [])] if args.sim == "verilator" else [args.vcs])
    missing = [exe for exe in required if not shutil.which(exe)]
    reason = None
    if missing:
        reason = "Simulator executables not found: " + ", ".join(missing)
    elif not source_list(args).is_file():
        reason = f"Missing source file list: {source_list(args)}"
    elif args.sim == "questa" and uvm_src is None:
        reason = "Cannot find uvm_macros.svh. Set --uvm-home or UVM_HOME to Questa's UVM 1.2 directory."
    elif args.sim == "verilator" and uvm_src is None:
        reason = "Verilator needs UVM source. Set --uvm-home or UVM_HOME (UVM2020 3.2 recommended with Verilator >=5.052)."
    elif args.compile_uvm_source and not (uvm_src / "uvm_pkg.sv").is_file():
        reason = "--compile-uvm-source requires uvm_pkg.sv in UVM_HOME/src"
    if reason:
        report["reason"] = reason
        write_reports(output, report)
        print("ERROR: " + reason, file=sys.stderr)
        print(f"Report: {output / 'report.json'}", file=sys.stderr)
        return 2
    (output / "build").mkdir()
    if args.build_dir:
        args.build_dir.mkdir(parents=True, exist_ok=True)
    try:
        version = run_process(simulator_version_command(args), ROOT, output / "build" / "version.log", 30)
        version_lines = read_log(version.log).splitlines()
        report["tool_version"] = "\n".join(line for line in version_lines if not line.startswith("COMMAND ")).strip()
        report["tool_version_log"] = version.log
        report["tool_version_process"] = asdict(version)
        if version.timed_out or version.returncode != 0:
            raise OSError("Could not query simulator version; inspect build/version.log")
        report["source_manifest"] = capture_source_manifest(args, uvm_src)
        report["source_manifest_file"] = str(output / "source_snapshot.json")
        Path(report["source_manifest_file"]).write_text(json.dumps(report["source_manifest"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_reports(output, report)
        for index, command in enumerate(commands):
            process = run_process(command, ROOT, output / "build" / f"build_{index}.log", args.build_timeout)
            report["build"].append(asdict(process))
            if process.timed_out or process.returncode != 0 or SIM_ERROR.search(read_log(process.log)):
                report["status"] = "BUILD_FAIL"
                report["reason"] = f"Build failed; inspect {process.log}"
                write_reports(output, report)
                print(report["reason"], file=sys.stderr)
                return 1
        binary = compiled_binary_path(args, output)
        if binary:
            if not binary.is_file():
                raise FileNotFoundError(f"Build returned without producing executable: {binary}")
            report["compiled_binary"] = {"path": str(binary), "sha256": file_digest(binary), "bytes": binary.stat().st_size}
        for run in runs:
            directory = Path(run["directory"])
            directory.mkdir()
            process = run_process(run["command"], directory, directory / "simulation.log", args.timeout)
            outcome = classify_log(read_log(process.log), process.returncode, process.timed_out,
                                   SUITE_PASS_MARKERS[args.suite])
            result = {"test": run["test"], "seed": run["seed"], **asdict(process), **asdict(outcome)}
            missing_artifacts = []
            for key in ("coverage_file", "waveform_file"):
                requested = run.get(key)
                result[key] = requested if requested and Path(requested).exists() else None
                if requested and not result[key]:
                    missing_artifacts.append(requested)
            if outcome.status == "PASS" and missing_artifacts:
                result.update(status="FAIL", reason="Missing requested artifact(s): " + ", ".join(missing_artifacts))
            report["runs"].append(result)
            print(f"{result['status']}: {run['test']} seed={run['seed']} ({result['reason']})", flush=True)
            # Persist after every run so interrupted regressions retain completed evidence.
            report["status"] = "RUNNING"
            write_reports(output, report)
        coverage_ok = export_verilator_coverage(args, output, report) if args.sim == "verilator" and args.coverage else True
    except (OSError, KeyboardInterrupt) as error:
        report["status"] = "INTERRUPTED" if isinstance(error, KeyboardInterrupt) else "ERROR"
        report["reason"] = str(error) or "Interrupted by user"
        write_reports(output, report)
        print(f"{report['status']}: {report['reason']}", file=sys.stderr)
        return 130 if isinstance(error, KeyboardInterrupt) else 2
    report["status"] = "PASS" if coverage_ok and all(run["status"] == "PASS" for run in report["runs"]) else "FAIL"
    write_reports(output, report)
    print(f"{report['status']}: report at {output / 'report.md'}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
