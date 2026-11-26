#!/usr/bin/env python3
"""Fetch pinned public EDA inputs and build OpenSTA in an ASCII Linux prefix.

Ubuntu dependencies: yosys iverilog build-essential cmake tcl-dev swig
libeigen3-dev zlib1g-dev flex bison. No sudo or package-manager invocation here.
Downloads work on Windows; --build requires Linux. All source licenses remain
inside the extracted source directories. No tool binaries are redistributed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()


def extract(archive, target):
    if target.exists():
        return
    with tarfile.open(archive) as stream:
        entries = stream.getmembers()
        root_names = {entry.name.split("/", 1)[0] for entry in entries}
        if len(root_names) != 1:
            raise ValueError("Expected one archive root")
        source_root = next(iter(root_names))
        staging = target.parent / (target.name + ".extract")
        staging.mkdir(exist_ok=False)
        for entry in entries:
            name = Path(entry.name)
            if name.is_absolute() or ".." in name.parts or not (entry.isfile() or entry.isdir()):
                raise ValueError("Unsafe tool source archive member")
        stream.extractall(staging, members=entries, filter="data")
        (staging / source_root).rename(target)
        staging.rmdir()


def run(command, cwd, log):
    print("RUN", json.dumps([str(arg) for arg in command]), flush=True)
    with log.open("w", encoding="utf-8") as stream:
        stream.write("COMMAND " + json.dumps([str(arg) for arg in command]) + "\n")
        stream.flush()
        subprocess.run(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT, check=True)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--downloads", type=Path, default=ROOT / "results/frontend_downloads")
    p.add_argument("--prefix", type=Path, default=Path("/var/tmp/apb-frontend-tools"))
    p.add_argument("--build", action="store_true")
    p.add_argument("--jobs", type=int, default=2)
    a = p.parse_args()
    lock_path = ROOT / "flow/frontend/toolchain.lock.json"
    lock = json.loads(lock_path.read_text())
    a.downloads.mkdir(parents=True, exist_ok=True)
    for item in lock["artifacts"]:
        path = a.downloads / item["file"]
        if not path.exists():
            with urllib.request.urlopen(item["url"], timeout=120) as response:
                temporary = path.with_suffix(path.suffix + ".partial")
                with temporary.open("wb") as output:
                    shutil.copyfileobj(response, output)
                temporary.rename(path)
        if path.stat().st_size != item["bytes"] or digest(path) != item["sha256"]:
            raise ValueError("Pinned artifact differs: " + item["file"])
        print("VERIFIED", item["file"], item["sha256"], flush=True)
    if not a.build:
        return
    if os.name == "nt" or not str(a.prefix.resolve()).isascii() or a.jobs < 1:
        raise ValueError("Build requires Linux, an ASCII prefix, and positive jobs")
    prefix = a.prefix.resolve()
    prefix.mkdir(parents=True, exist_ok=True)
    for item in lock["artifacts"]:
        if not item["file"].endswith(".tar.gz"):
            shutil.copy2(a.downloads / item["file"], prefix / item["file"])
    cudd, sta = prefix / "cudd-src", prefix / "opensta-src"
    extract(a.downloads / "cudd.tar.gz", cudd)
    extract(a.downloads / "opensta.tar.gz", sta)
    run(["./configure", "--enable-shared=no", "--enable-dddmp=no", "--enable-obj=no", "--prefix=" + str(prefix / "cudd")], cudd, prefix / "cudd-configure.log")
    run(["make", "-j", str(a.jobs)], cudd, prefix / "cudd-build.log")
    run(["make", "install"], cudd, prefix / "cudd-install.log")
    build = prefix / "opensta-build"
    run(["cmake", "-S", str(sta), "-B", str(build), "-DCUDD_DIR=" + str(prefix / "cudd"),
         "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_INSTALL_PREFIX=" + str(prefix / "opensta")], prefix, prefix / "opensta-configure.log")
    run(["cmake", "--build", str(build), "--parallel", str(a.jobs)], prefix, prefix / "opensta-build.log")
    run([str(build / "sta"), "-version"], prefix, prefix / "opensta-version.log")
    result = {"lock_sha256": digest(lock_path), "prefix": str(prefix), "opensta": str(build / "sta"),
              "opensta_binary_sha256": digest(build / "sta"), "artifacts": lock["artifacts"]}
    (prefix / "installed.json").write_text(json.dumps(result, indent=2) + "\n")
    print("READY", build / "sta", flush=True)


if __name__ == "__main__":
    main()
