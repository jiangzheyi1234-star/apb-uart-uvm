# APB UART UVM

[![Verification](https://github.com/jiangzheyi1234-star/apb-uart-uvm/actions/workflows/verification.yml/badge.svg?branch=main)](https://github.com/jiangzheyi1234-star/apb-uart-uvm/actions/workflows/verification.yml)

[中文](README.md) · [Documentation](docs/README.md) · [Verification reports](https://jiangzheyi1234-star.github.io/apb-uart-uvm/) · [Releases](https://github.com/jiangzheyi1234-star/apb-uart-uvm/releases/latest)

A SystemVerilog/UVM verification environment for a pinned PULP APB UART, with independent APB/UART agents, bidirectional checking, a cycle-level FIFO model, bank-aware register access, assertions, coverage and automated regression.

## Features

- APB setup/access driving, completed-transaction monitoring and protocol assertions.
- Independent RX stimulus and TX/RX pin decoding; the scoreboard does not inspect DUT memories or state machines.
- TX capacity prediction, retained RX frame 17, empty reads, mirrored addresses, erroneous frames and reset during traffic.
- Four-register RAL for IER/LCR/DLL/DLM: separate maps, locked frontdoors, exact LCR restoration and passive bank prediction.
- Four selected boundary faults with clean before/after controls to check error detection.
- Pinned tools, seeds, source snapshots, native coverage databases and real UVM simulation in GitHub Actions.

## Requirements and setup

Validated with Ubuntu 24.04 Linux/WSL, Python 3.12, Verilator 5.054 and Accellera UVM 2020.3.1. Source archives are SHA-256 pinned. Questa/VCS entry points are provided; dynamic commercial-simulator results are not available.

```bash
git clone https://github.com/jiangzheyi1234-star/apb-uart-uvm.git
cd apb-uart-uvm
sudo apt-get update
sudo apt-get install -y --no-install-recommends build-essential autoconf \
  flex bison libfl-dev zlib1g-dev help2man ca-certificates z3
bash scripts/bootstrap_verilator.sh
```

## Run verification

```bash
python3 py/verify_rtl.py
python3 -m unittest discover -s tests -v
bash scripts/run_full_regression.sh --out results/core
python3 py/run_linux_regression.py --rtl fixed --test uart_ral_test \
  --seeds 1 2 3 --coverage --trace --out results/ral
python3 py/run_mutation.py --baseline-report results/core/report.json \
  --out results/checker_controls
```

Use a fresh output directory for each invocation. The staging helper verifies source bytes and uses an ASCII Linux build path, including for Unicode Windows workspaces.

Reproduce the original-RTL requirement failures separately:

```bash
RTL_VARIANT=upstream bash scripts/run_full_regression.sh --out results/upstream
# The upstream command should exit 1. Run acceptance separately, without &&.
python3 py/validate_acceptance.py --fixed results/core/report.json \
  --upstream results/upstream/report.json --out results/acceptance.json
```

## Recorded results

| Scope | Measured result |
| --- | --- |
| Fixed core suite | 45/45 PASS; 1,039 TX + 1,216 RX frames |
| RAL suite | 3/3 PASS; 168 writes and 291 mirror reads |
| Core + RAL | 48/48 PASS; 16 scenarios and 2,261 frames |
| Checker controls | 4/4 intended detections; 6/6 clean PASS controls |
| Core functional bins | 272/277, 98.19% |
| Frame-format / baud cross | 96/96 |
| RTL LCOV lines / branches | 453/474, 95.57% / 1,670/2,120, 78.77% |

The 48-run denominator comprises core 45 plus RAL 3. The ten checker-control processes are separate. Original-RTL results retain 33 PASS and 12 strict-requirement FAILs. Coverage comes from the 45-run fixed core suite; five invalid-pending diagnostic bins remain unhit. See [validation](docs/validation.md) for provenance and metric definitions.

## Documentation and distributions

[Architecture](docs/architecture.md) · [Registers](docs/registers.md) · [Verification plan](docs/verification_plan.md) · [RTL findings](docs/rtl_findings.md) · [Local fixes](docs/rtl_fixes.md) · [RAL](tb/ral/README.md) · [Coverage analysis](docs/coverage_analysis.md) · [Checker controls](docs/checker_sensitivity.md)

`rtl/` retains the original import; `rtl_fixed/` contains documented local changes. `tb/`, `sim/`, `py/`, `scripts/` and `tests/` contain the verification environment, simulator integration and tools.

Releases provide separate source, evidence and raw CI archives with `SHA256SUMS`. Source archives exclude generated simulation output and downloaded tools. Overlay the evidence archive at the source root for offline reports; the two archives use distinct per-file manifests.

[Release procedure](RELEASE.md) · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md)

## Scope and licensing

The DUT is [pulp-platform/apb_uart_sv](https://github.com/pulp-platform/apb_uart_sv) at `dfad6e04d19cc9481d3cd2750b45b970dc61271b`. Register offsets are bytes 0–7; the bit period is divisor + 1 clocks. TX has 16 FIFO entries plus a serializer; RX can retain one additional waiting frame.

Scope excludes complete 16550 compatibility, arbitrary baud mismatch, active TX FIFO clear, continuous RX overrun, configuration changes during traffic and four-state signoff.

The original and derived RTL retain Solderpad Hardware License 0.51. Original verification code, tools and documentation use MIT. See [LICENSE](LICENSE), [NOTICE](NOTICE.md) and the [upstream manifest](third_party/apb_uart_sv/manifest.json).
