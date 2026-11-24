#!/usr/bin/env python3
"""Create separate reproducible source and verification-evidence distributions.

The default source profile contains implementation, tools, tests and explicitly
selected technical documentation. The evidence profile contains only curated
current evidence, its HTML entry point and licensing. Their distinct manifests
allow both archives to be extracted into the same directory.
"""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import sys
import tempfile
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIRECTORIES = (
    "rtl", "rtl_fixed", "tb", "sim", "py", "tests", "scripts", "third_party", ".github", "web"
)
ROOT_FILES = (
    "README.md", "README.en.md", "LICENSE", "NOTICE", "NOTICE.md",
    "CONTRIBUTING", "CONTRIBUTING.md", "CHANGELOG", "CHANGELOG.md",
    "RELEASE.md", ".gitignore", ".gitattributes",
)
SOURCE_DOCUMENTS = (
    "docs/README.md", "docs/architecture.md", "docs/registers.md",
    "docs/verification_plan.md", "docs/rtl_findings.md", "docs/rtl_fixes.md",
    "docs/coverage_analysis.md", "docs/checker_sensitivity.md", "docs/validation.md",
    "docs/apb_protocol.md", "docs/dashboard.md",
)
EVIDENCE_DIRECTORIES = ("docs/release", "docs/features", "docs/ci", "docs/protocol", "docs/assets", "docs/data")
EVIDENCE_FILES = ("docs/index.html", "docs/.nojekyll", "LICENSE", "NOTICE", "NOTICE.md", "third_party/apb_uart_sv/LICENSE")
PROFILES = ("source", "evidence")
EXCLUDED_DIRECTORIES = frozenset({
    ".git", ".hg", ".svn", ".tools", "results", "dist", "build", "builds",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache",
    "cache", "node_modules", ".venv", "venv", "obj_dir", "work", "csrc",
    "simv.daidir", "apb-uart-uvm", ".private", "private", ".resume_work",
    "resume", "career", "personal", ".aws", ".codex", ".agents",
})
EXCLUDED_SUFFIXES = frozenset({".pyc", ".pyo", ".tmp", ".swp", ".swo"})
SOURCE_GENERATED_SUFFIXES = frozenset({
    ".log", ".vcd", ".fst", ".wlf", ".ucdb", ".vdb", ".dat",
    ".o", ".obj", ".a", ".lib", ".so", ".dll", ".exe", ".zip", ".gz", ".tgz",
})
NON_ENGINEERING_NAMES = frozenset({
    "industry_benchmark.md", "guangzhou_interview.md", "interview_guide.md", "optimization_rounds.md",
})
NON_ENGINEERING_NAME = re.compile(
    r"resume|interview|career|job[_ -]?search|optimization[_ -]?round|求职|面试|简历|优化轮次|(?:^|[._ -])cv(?:[._ -]|$)",
    re.IGNORECASE,
)
MANIFEST_NAMES = {"source": "MANIFEST.source.sha256", "evidence": "MANIFEST.evidence.sha256"}
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def is_link(path: Path) -> bool:
    """Do not traverse symlinks or Windows junctions into another directory."""
    return path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())


def collect_files(root: Path, output: Path, profile: str = "source") -> list[Path]:
    if profile not in PROFILES:
        raise ValueError(f"Unknown distribution profile: {profile}")
    root = root.resolve()
    output = output.resolve()
    selected: dict[str, Path] = {}

    def allowed_path(path: Path) -> bool:
        # Check ancestors as well as the file itself: explicit documentation
        # paths must not bypass a linked docs/ directory or Windows junction.
        current = root
        for component in path.relative_to(root).parts:
            current /= component
            if (component.casefold() in EXCLUDED_DIRECTORIES
                    or NON_ENGINEERING_NAME.search(component) or is_link(current)):
                return False
        return True

    def add(path: Path) -> None:
        if (not allowed_path(path)
                or not path.is_file() or path.suffix.lower() in EXCLUDED_SUFFIXES):
            return
        if path.name.casefold() in NON_ENGINEERING_NAMES or NON_ENGINEERING_NAME.search(path.name):
            return
        if profile == "source" and path.suffix.lower() in SOURCE_GENERATED_SUFFIXES:
            return
        resolved = path.resolve()
        if resolved == output or not resolved.is_relative_to(root):
            return
        relative = path.relative_to(root).as_posix()
        selected[relative] = path

    files = ROOT_FILES + SOURCE_DOCUMENTS if profile == "source" else EVIDENCE_FILES
    directories_to_collect = SOURCE_DIRECTORIES if profile == "source" else EVIDENCE_DIRECTORIES
    for filename in files:
        add(root / filename)
    for directory in directories_to_collect:
        starting_path = root / directory
        if not allowed_path(starting_path) or not starting_path.is_dir():
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


def package_project(root: Path, output: Path, profile: str = "source") -> dict[str, int | str]:
    root, output = root.resolve(), output.resolve()
    # Reject accidental replacement of a source file even though output itself
    # is omitted from collection. Normal archives use a .zip filename.
    if output.suffix.casefold() != ".zip":
        raise ValueError("--out must name a .zip file")
    paths = collect_files(root, output, profile)
    if not paths:
        raise ValueError(f"No {profile} distribution files were found")
    output.parent.mkdir(parents=True, exist_ok=True)
    payloads = [(path.relative_to(root).as_posix(), path.read_bytes()) for path in paths]
    manifest = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in payloads
    ).encode("utf-8")
    manifest_name = MANIFEST_NAMES[profile]
    entries = sorted(payloads + [(manifest_name, manifest)])
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
        "profile": profile,
        "manifest": manifest_name,
        "packaged_files": len(payloads),
        # Retained for callers of the original source-packaging API.
        "source_files": len(payloads),
        "archive_entries": len(entries),
        "uncompressed_bytes": sum(len(data) for _, data in entries),
        "zip_bytes": output.stat().st_size,
        "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--profile", choices=PROFILES, default="source")
    parser.add_argument("--out", type=Path, help="Output ZIP; defaults to dist/apb-uart-uvm-<profile>.zip")
    args = parser.parse_args(argv)
    requested = args.out or Path(f"dist/apb-uart-uvm-{args.profile}.zip")
    output = requested if requested.is_absolute() else ROOT / requested
    try:
        result = package_project(ROOT, output, args.profile)
    except (OSError, ValueError, zipfile.BadZipFile) as error:
        print(f"PACKAGE_ERROR: {error}", file=sys.stderr)
        return 1
    print(f"PACKAGE_PASS: {result['packaged_files']} {result['profile']} files + {result['manifest']} = {result['archive_entries']} ZIP entries")
    print(f"Archive: {result['archive']}")
    print(f"Bytes: {result['zip_bytes']}; SHA256: {result['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
