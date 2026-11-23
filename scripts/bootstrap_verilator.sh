#!/usr/bin/env bash
# Reproducible local tools. Linux/WSL prerequisites: build-essential autoconf
# flex bison libfl-dev zlib1g-dev help2man ca-certificates (Python 3.12+).
set -euo pipefail
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
mkdir -p .tools
python3 - <<'PY'
import hashlib, tarfile, urllib.request
from pathlib import Path
assets = [
 ('verilator-v5.054.tar.gz','https://codeload.github.com/verilator/verilator/tar.gz/refs/tags/v5.054','18658731b46922ef660bcb650be0aa503d751e5c17eb9d4644fdfabb11835198'),
 ('uvm-core-2020.3.1.tar.gz','https://codeload.github.com/accellera-official/uvm-core/tar.gz/refs/tags/2020.3.1','f55bdbc02cc500d4a2f41b31bad127653289eb2073f806ce156fb82662b362b8'),
]
for name,url,expected in assets:
    p=Path('.tools')/name
    if not p.is_file():
        print('Downloading',name,flush=True)
        p.write_bytes(urllib.request.urlopen(url,timeout=60).read())
    if hashlib.sha256(p.read_bytes()).hexdigest()!=expected:
        raise SystemExit('Archive checksum mismatch: '+str(p))
    print('SHA256 OK:',name,flush=True)
p=Path('.tools/uvm-core-2020.3.1/src/uvm_pkg.sv')
if not p.is_file():
    with tarfile.open('.tools/uvm-core-2020.3.1.tar.gz') as t:
        t.extractall('.tools',filter='data')
PY
if [[ -x .tools/verilator/bin/verilator ]] && .tools/verilator/bin/verilator --version | grep -q '5.054'; then
  .tools/verilator/bin/verilator --version
  exit 0
fi
build_dir=""
if [[ -f .tools/verilator_build_dir.txt ]]; then
  previous_build_dir="$(cat .tools/verilator_build_dir.txt)"
  if [[ "$previous_build_dir" == /var/tmp/apb-uart-verilator-5.054.* || "$previous_build_dir" == /tmp/apb-uart-verilator-5.054.* ]] && [[ -f "$previous_build_dir/verilator-5.054/configure.ac" ]]; then
    build_dir="$previous_build_dir"
  fi
fi
if [[ -z "$build_dir" ]]; then
  build_dir="$(mktemp -d /var/tmp/apb-uart-verilator-5.054.XXXXXX)"
  printf '%s\n' "$build_dir" > .tools/verilator_build_dir.txt
  tar -xzf .tools/verilator-v5.054.tar.gz -C "$build_dir"
fi
cd "$build_dir/verilator-5.054"
if [[ ! -f src/Makefile_obj ]]; then
  autoconf
  ./configure --prefix="$project_dir/.tools/verilator"
fi
# 2 jobs fits the small WSL memory allocation; override when more is available.
make -C src -j"${BUILD_JOBS:-2}" opt
make install-all VL_INST_PUBLIC_BIN_FILES="verilator_bin verilator_coverage_bin"
"$project_dir/.tools/verilator/bin/verilator" --version
