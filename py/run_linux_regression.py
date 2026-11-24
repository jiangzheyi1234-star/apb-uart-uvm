#!/usr/bin/env python3
"""Run the real Verilator regression from a byte-verified ASCII Linux stage.

Invoke in WSL from the original project directory:
  python3 py/run_linux_regression.py --rtl fixed --coverage --trace --seeds 1

Only allowlisted project/tool files are copied; original files are unchanged.
Reports stay under the original project's results/ directory. No stage files
are deleted. The real compiler is invoked on every run, including cache reuse.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = ("rtl", "rtl_fixed", "tb", "sim", "py", "tests", "third_party",
               ".tools/verilator", ".tools/uvm-core-2020.3.1")
SKIP = {"__pycache__", ".git", ".pytest_cache"}
FILES = (".tools/uvm-core-2020.3.1.tar.gz", ".tools/verilator-v5.054.tar.gz")


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def inventory(project: Path) -> list[Path]:
    files = set()
    for name in DIRECTORIES:
        directory = project / name
        if not directory.is_dir():
            continue
        for parent, directories, names in os.walk(directory, followlinks=False):
            directories[:] = sorted(name for name in directories if name not in SKIP)
            for name in names:
                source = Path(parent) / name
                if source.is_file():
                    files.add(source)
    for pattern in ("README*", ".git*"):
        files.update(path for path in project.glob(pattern) if path.is_file())
    files.update(project / name for name in FILES if (project / name).is_file())
    return sorted(files)


def copy_stage(project: Path, stage: Path) -> dict:
    sources = inventory(project)
    if not sources:
        raise ValueError("The source project allowlist is empty")
    records = []
    copied = 0
    for source in sources:
        relative = source.relative_to(project)
        destination = stage / relative
        if not destination.resolve().is_relative_to(stage):
            raise ValueError(f"Stage path escapes the selected directory: {relative}")
        source_hash = digest(source)
        if not destination.is_file() or destination.stat().st_size != source.stat().st_size or digest(destination) != source_hash:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination, follow_symlinks=True)
            copied += 1
        staged_hash = digest(destination)
        if staged_hash != source_hash:
            raise ValueError(f"Stage byte verification failed: {relative}")
        records.append({"path": relative.as_posix(), "source_sha256": source_hash,
                        "staged_sha256": staged_hash, "bytes": destination.stat().st_size})
    # Avoid silently compiling obsolete SV files left from a different project.
    # A fresh stage is the recovery path; this wrapper never deletes user files.
    active = {record["path"] for record in records}
    for name in ("rtl", "rtl_fixed", "tb"):
        directory = stage / name
        if directory.is_dir():
            for candidate in directory.rglob("*"):
                if candidate.is_file() and candidate.suffix in (".sv", ".svh") and candidate.relative_to(stage).as_posix() not in active:
                    raise ValueError(f"Stale staged source found: {candidate}. Select a fresh --stage-dir; no files were deleted.")
    return {"captured_utc": datetime.now(timezone.utc).isoformat(), "original_project_root": str(project),
            "staged_project_root": str(stage), "all_staged_files_byte_equal": True,
            "verification_scope": "Source/stage equality at staging time, before the actual compiler invocation",
            "copied_files": copied, "verified_files": len(records), "files": records}


def take_option(arguments: list[str], name: str) -> tuple[list[str], str | None]:
    """Remove one wrapper-controlled runner option without interpreting shell text."""
    remaining = []
    value = None
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == name:
            if index + 1 >= len(arguments):
                raise ValueError(f"{name} requires a value")
            if value is not None:
                raise ValueError(f"duplicate {name}")
            value = arguments[index + 1]
            index += 2
        elif argument.startswith(name + "="):
            if value is not None:
                raise ValueError(f"duplicate {name}")
            value = argument.split("=", 1)[1]
            index += 1
        else:
            remaining.append(argument)
            index += 1
    return remaining, value


def staged_path(raw: str | None, project: Path, stage: Path, default: Path) -> Path:
    if raw is None:
        return default
    selected = Path(raw)
    selected = (project / selected).resolve() if not selected.is_absolute() else selected.resolve()
    if selected.is_relative_to(project):
        selected = stage / selected.relative_to(project)
    if not str(selected).isascii():
        raise ValueError(f"Tool and UVM paths must be ASCII in the Linux stage: {selected}")
    return selected


def default_stage_directory(suite: str) -> Path:
    return Path("/var/tmp/apb-agent-protocol-workspace" if suite == "apb_protocol" else "/var/tmp/apb-uart-uvm-workspace")


def default_build_directory(suite: str, variant: str) -> Path:
    return Path("/var/tmp/apb-agent-protocol-build" if suite == "apb_protocol" else f"/var/tmp/apb-uart-uvm-build-{variant}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog="Other arguments are passed to run_regression.py. Use that script's --help for runner options.")
    parser.add_argument("--stage-dir", type=Path)
    parser.add_argument("--suite", choices=("uart", "apb_protocol"), default="uart")
    parser.add_argument("--source-root", type=Path, default=ROOT)
    args, forwarded = parser.parse_known_args()
    if forwarded[:1] == ["--"]:
        forwarded = forwarded[1:]
    if os.name == "nt":
        parser.error("Invoke this helper with Linux/WSL python3, not Windows Python")
    project = args.source_root.resolve()
    stage = (args.stage_dir or default_stage_directory(args.suite)).resolve()
    if not str(stage).isascii() or stage == Path("/") or stage == project or stage.is_relative_to(project) or project.is_relative_to(stage):
        parser.error("--stage-dir must be a separate, non-root ASCII directory outside the original project")
    try:
        forwarded, simulator = take_option(forwarded, "--sim")
        if simulator not in (None, "verilator"):
            raise ValueError("This staging helper is for --sim verilator")
        forwarded, variant = take_option(forwarded, "--rtl")
        variant = variant or "upstream"
        if variant not in ("upstream", "fixed"):
            raise ValueError("--rtl must be upstream or fixed")
        forwarded, out_value = take_option(forwarded, "--out")
        output = (Path(out_value) if out_value else Path("results") / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ"))
        output = (project / output).resolve() if not output.is_absolute() else output.resolve()
        if output.exists() and (not output.is_dir() or any(output.iterdir())):
            raise ValueError("--out must be a new or empty directory")
        forwarded, build_value = take_option(forwarded, "--build-dir")
        build = Path(build_value).resolve() if build_value else default_build_directory(args.suite, variant)
        if not str(build).isascii():
            raise ValueError("--build-dir must be an ASCII Linux path")
        forwarded, verilator_value = take_option(forwarded, "--verilator")
        forwarded, coverage_value = take_option(forwarded, "--verilator-coverage")
        forwarded, uvm_value = take_option(forwarded, "--uvm-home")
        stage.mkdir(parents=True, exist_ok=True)
        manifest = copy_stage(project, stage)
        tools = stage / ".tools" / "verilator"
        verilator = staged_path(verilator_value, project, stage, tools / "bin" / "verilator")
        coverage = staged_path(coverage_value, project, stage, tools / "bin" / "verilator_coverage")
        uvm = staged_path(uvm_value, project, stage, stage / ".tools" / "uvm-core-2020.3.1" / "src")
        verilator_root = tools / "share" / "verilator"
        for required in (verilator, coverage, uvm / "uvm_pkg.sv", uvm / "uvm_macros.svh", verilator_root / "include" / "verilated.mk"):
            if not required.is_file():
                raise FileNotFoundError(f"Required staged tool/source is missing: {required}")
        command = [sys.executable, str(stage / "py" / "run_regression.py"), "--sim", "verilator", "--suite", args.suite, "--rtl", variant,
                   "--out", str(output), "--build-dir", str(build), "--verilator", str(verilator),
                   "--verilator-coverage", str(coverage), "--uvm-home", str(uvm), *forwarded]
        environment = os.environ.copy()
        environment["VERILATOR_ROOT"] = str(verilator_root)
        environment["UVM_HOME"] = str(uvm)
        environment["PATH"] = str(tools / "bin") + os.pathsep + environment.get("PATH", "")
        manifest["runner_command"] = command
        manifest["environment_overrides"] = {name: environment[name] for name in ("VERILATOR_ROOT", "UVM_HOME")}
        manifest["build_directory"] = str(build)
        manifest["suite"] = args.suite
        print(f"STAGE_VERIFIED: {manifest['verified_files']} byte-equal files; {manifest['copied_files']} copied to {stage}", flush=True)
        print("RUNNER_COMMAND " + json.dumps(command, ensure_ascii=False), flush=True)
        returncode = subprocess.run(command, cwd=stage, env=environment, stdin=subprocess.DEVNULL, shell=False).returncode
        report_path = output / "report.json"
        if report_path.is_file():
            origin_map = output / "stage_origin.json"
            origin_map.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["source_origin_map"] = str(origin_map)
            report["source_origin"] = {"original_project_root": str(project), "staged_project_root": str(stage),
                                       "all_staged_files_byte_equal": True, "verified_files": manifest["verified_files"],
                                       "origin_map_sha256": digest(origin_map), "runner_command": command}
            report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return returncode
    except (OSError, ValueError) as error:
        parser.exit(2, f"LINUX_STAGE_ERROR: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
