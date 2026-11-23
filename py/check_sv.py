#!/usr/bin/env python3
"""Check the real RTL and UVM testbench with slang; this is NOT simulation.

Install pyslang in the current interpreter or under .tools/python. The checker
uses --uvm-home / UVM_HOME, or the official UVM 1.2 source archive at
.tools/uvm-1.2.tar.gz (also accepts the legacy fallback .tools/uvm.zip).
All diagnostics remain visible, including errors in authored testbench files.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import sys
import tarfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def extract_uvm_source(archive: Path, destination: Path) -> Path:
    """Extract only the official archive's distrib/src subtree, without zip slip."""
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        packages = [item.filename for item in bundle.infolist() if item.filename.endswith("/src/uvm_pkg.sv") and "/docs/" not in item.filename]
        if len(packages) != 1:
            raise ValueError("UVM archive must contain one src/uvm_pkg.sv")
        prefix = packages[0].removesuffix("uvm_pkg.sv")
        members = [item for item in bundle.infolist() if item.filename.startswith(prefix)]
        if sum(item.file_size for item in members) > 128 * 1024 * 1024:
            raise ValueError("UVM source subtree exceeds 128 MiB")
        checked = []
        for item in members:
            name = item.filename.removeprefix(prefix)
            posix, windows = PurePosixPath(name), PureWindowsPath(name)
            target = (destination / name).resolve()
            if posix.is_absolute() or windows.drive or windows.is_absolute() or ".." in posix.parts or ".." in windows.parts or not target.is_relative_to(destination):
                raise ValueError(f"Unsafe UVM archive path: {item.filename}")
            if ((item.external_attr >> 16) & 0o170000) == 0o120000:
                raise ValueError(f"UVM archive symlinks are not supported: {item.filename}")
            checked.append((item, target))
        for item, target in checked:
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(bundle.read(item))
    return destination


def extract_uvm_tar_source(archive: Path, destination: Path) -> Path:
    """Copy only regular source files; never materialize tar links or devices."""
    destination = destination.resolve()
    with tarfile.open(archive, "r:gz") as bundle:
        packages = [item.name for item in bundle.getmembers() if item.name.endswith("/src/uvm_pkg.sv") and "/docs/" not in item.name]
        if len(packages) != 1:
            raise ValueError("UVM archive must contain one src/uvm_pkg.sv")
        prefix = packages[0].removesuffix("uvm_pkg.sv")
        members = [item for item in bundle.getmembers() if item.name.startswith(prefix)]
        if sum(item.size for item in members) > 128 * 1024 * 1024:
            raise ValueError("UVM source subtree exceeds 128 MiB")
        checked = []
        for item in members:
            name = item.name.removeprefix(prefix)
            posix, windows = PurePosixPath(name), PureWindowsPath(name)
            target = (destination / name).resolve()
            if posix.is_absolute() or windows.drive or windows.is_absolute() or ".." in posix.parts or ".." in windows.parts or not target.is_relative_to(destination):
                raise ValueError(f"Unsafe UVM archive path: {item.name}")
            if not (item.isfile() or item.isdir()):
                raise ValueError(f"UVM archive links/devices are not supported: {item.name}")
            checked.append((item, target))
        for item, target in checked:
            if item.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with bundle.extractfile(item) as source:
                    target.write_bytes(source.read())
    return destination


def find_uvm_source(explicit: Path | None) -> Path:
    if explicit is None and os.environ.get("UVM_HOME"):
        explicit = Path(os.environ["UVM_HOME"])
    if explicit:
        for path in (explicit / "src", explicit):
            if (path / "uvm_pkg.sv").is_file() and (path / "uvm_macros.svh").is_file():
                return path.resolve()
        raise FileNotFoundError(f"Cannot find uvm_pkg.sv and uvm_macros.svh under {explicit}")
    official_archive = ROOT / ".tools" / "uvm-1.2.tar.gz"
    official_source = ROOT / ".tools" / "uvm-1.2-src"
    if (official_source / "uvm_pkg.sv").is_file():
        return official_source.resolve()
    if official_archive.is_file():
        return extract_uvm_tar_source(official_archive, official_source)
    destination = ROOT / ".tools" / "uvm-src"
    if not (destination / "uvm_pkg.sv").is_file():
        archive = ROOT / ".tools" / "uvm.zip"
        if not archive.is_file():
            raise FileNotFoundError("Set --uvm-home / UVM_HOME, or provide the official UVM 1.2 archive at .tools/uvm-1.2.tar.gz")
        extract_uvm_source(archive, destination)
    return destination.resolve()


def quote_arg(value: str | Path) -> str:
    value = Path(value)
    try:
        # slang's Windows argument parser cannot round-trip some Unicode
        # absolute paths. Relative project paths avoid its code-page conversion.
        value = os.path.relpath(value.resolve(), ROOT)
    except ValueError:  # A UVM installation on another Windows drive.
        value = str(value)
    value = str(value).replace("\\", "/")
    if any(character in value for character in ('"', "\r", "\n")):
        raise ValueError("Source and include paths cannot contain quotes or newlines")
    return '"' + value + '"'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--syntax-only", action="store_true", help="Preprocess and parse only; do not elaborate or type-check")
    parser.add_argument("--uvm-home", type=Path)
    parser.add_argument("--file-list", type=Path, default=ROOT / "sim" / "files.f")
    args = parser.parse_args(argv)
    sys.path.insert(0, str(ROOT / ".tools" / "python"))
    try:
        import pyslang
        from pyslang.driver import Driver
        uvm_src = find_uvm_source(args.uvm_home)
        if not args.file_list.is_file():
            raise FileNotFoundError(f"Missing source file list: {args.file_list}")
    except (ImportError, OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as error:
        print(f"STATIC_CHECK_ERROR: {error}", file=sys.stderr)
        return 2
    includes = [uvm_src, ROOT / "tb"]
    includes.extend(ROOT / "tb" / name for name in (
        "apb_agent", "uart_agent", "scoreboard", "coverage", "env", "seq", "test"
    ))
    command = "slang --single-unit --timescale=1ns/1ps -DUVM_NO_DPI "
    command += " ".join("-I" + quote_arg(path) for path in includes)
    command += " " + quote_arg(uvm_src / "uvm_pkg.sv")
    command += " -f " + quote_arg(args.file_list.resolve())
    if not args.syntax_only:
        command += " --top tb_top"
    driver = Driver()
    driver.addStandardArgs()
    driver.setTerminalColorsEnabled(False)
    previous_cwd = Path.cwd()
    try:
        os.chdir(ROOT)  # sim/files.f paths are project-root relative, as in simulation.
        if not driver.parseCommandLine(command) or not driver.processOptions():
            return 1
        parsed = driver.parseAllSources()
        if args.syntax_only:
            success = driver.reportParseDiags() and parsed
            success = driver.reportDiagnostics(False) and success
        else:
            success = driver.runFullCompilation() and parsed
    finally:
        os.chdir(previous_cwd)
    mode = "syntax" if args.syntax_only else "semantic compilation"
    print(f"STATIC_CHECK_{'PASS' if success else 'FAIL'}: {mode}; pyslang {getattr(pyslang, '__version__', 'unknown')}; no RTL simulation performed.")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
