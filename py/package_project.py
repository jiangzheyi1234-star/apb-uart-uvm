#!/usr/bin/env python3
"""Create a reproducible source/evidence ZIP with an internal SHA-256 manifest.

Run from any directory: python py/package_project.py --out dist/apb-uart-uvm.zip
Only the project source/documentation allowlist is included. Downloaded tools,
simulator output directories, unrelated workspaces, Git internals and caches
are excluded. Curated evidence saved under docs/ is included.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRECTORIES = (
    "rtl", "rtl_fixed", "tb", "sim", "py", "tests", "docs", "scripts", "third_party"
)
ROOT_FILES = ("README.md", ".gitignore", ".gitattributes")
EXCLUDED_DIRECTORIES = frozenset({
    ".git", ".hg", ".svn", ".tools", "results", "dist", "build", "builds",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache",
    "cache", "node_modules", ".venv", "venv", "obj_dir", "work", "csrc",
    "simv.daidir", "apb-uart-uvm",
})
EXCLUDED_SUFFIXES = frozenset({".pyc", ".pyo", ".tmp", ".swp", ".swo"})
MANIFEST_NAME = "MANIFEST.sha256"
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def is_link(path: Path) -> bool:
    """Do not traverse symlinks or Windows junctions into another directory."""
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def collect_files(root: Path, output: Path) -> list[Path]:
    root = root.resolve()
    output = output.resolve()
    selected: dict[str, Path] = {}

    def add(path: Path) -> None:
        if (path.name.casefold() in EXCLUDED_DIRECTORIES or is_link(path)
                or not path.is_file() or path.suffix.lower() in EXCLUDED_SUFFIXES):
            return
        resolved = path.resolve()
        if resolved == output or not resolved.is_relative_to(root):
            return
        relative = path.relative_to(root).as_posix()
        selected[relative] = path

    for filename in ROOT_FILES:
        add(root / filename)
    for directory in SOURCE_DIRECTORIES:
        starting_path = root / directory
        if is_link(starting_path) or not starting_path.is_dir():
            continue
        for current, directories, filenames in os.walk(starting_path, topdown=True, followlinks=False):
            current_path = Path(current)
            directories[:] = sorted(
                name for name in directories
                if name.casefold() not in EXCLUDED_DIRECTORIES and not is_link(current_path / name)
            )
            for filename in sorted(filenames):
                add(current_path / filename)
    return [selected[name] for name in sorted(selected)]


def zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=ZIP_TIMESTAMP)
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def package_project(root: Path, output: Path) -> dict[str, int | str]:
    root, output = root.resolve(), output.resolve()
    # Reject accidental replacement of a source file even though output itself
    # is omitted from collection. Normal archives use a .zip filename.
    if output.suffix.casefold() != ".zip":
        raise ValueError("--out must name a .zip file")
    paths = collect_files(root, output)
    if not paths:
        raise ValueError("No project source files were found")
    output.parent.mkdir(parents=True, exist_ok=True)
    payloads = [(path.relative_to(root).as_posix(), path.read_bytes()) for path in paths]
    manifest = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in payloads
    ).encode("utf-8")
    entries = sorted(payloads + [(MANIFEST_NAME, manifest)])
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix=output.name + ".", suffix=".tmp", dir=output.parent, delete=False) as temporary:
            temporary_path = Path(temporary.name)
        with zipfile.ZipFile(temporary_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, data in entries:
                archive.writestr(zip_info(name), data, compresslevel=9)
        # Read every entry before replacing any previous deliverable.
        with zipfile.ZipFile(temporary_path) as archive:
            if archive.testzip() is not None:
                raise ValueError("ZIP integrity check failed")
            for name, data in payloads:
                if hashlib.sha256(archive.read(name)).digest() != hashlib.sha256(data).digest():
                    raise ValueError(f"ZIP checksum check failed: {name}")
        os.replace(temporary_path, output)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return {
        "archive": str(output),
        "source_files": len(payloads),
        "archive_entries": len(entries),
        "uncompressed_bytes": sum(len(data) for _, data in entries),
        "zip_bytes": output.stat().st_size,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, default=Path("dist/apb-uart-uvm.zip"))
    args = parser.parse_args(argv)
    output = args.out if args.out.is_absolute() else ROOT / args.out
    try:
        result = package_project(ROOT, output)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"PACKAGE_ERROR: {error}", file=sys.stderr)
        return 1
    print(f"PACKAGE_PASS: {result['source_files']} source/evidence files + SHA-256 manifest = {result['archive_entries']} ZIP entries")
    print(f"Archive: {result['archive']}")
    print(f"Bytes: {result['zip_bytes']}; SHA256: {result['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
