# APB UART UVM

[![Verification](https://github.com/jiangzheyi1234-star/apb-uart-uvm/actions/workflows/verification.yml/badge.svg?branch=main)](https://github.com/jiangzheyi1234-star/apb-uart-uvm/actions/workflows/verification.yml)

[中文](README.md) · [Documentation](docs/README.md) · [Verification workbench](https://jiangzheyi1234-star.github.io/apb-uart-uvm/) · [Releases](https://github.com/jiangzheyi1234-star/apb-uart-uvm/releases/latest)

A SystemVerilog/UVM verification environment for a pinned PULP APB UART, with independent APB/UART agents, bidirectional checking, a cycle-level FIFO model, bank-aware register access, assertions, coverage and automated regression.

## Features

- APB setup/access driving, completed-transaction monitoring and protocol assertions.
- Independent RX stimulus and TX/RX pin decoding; the scoreboard does not inspect DUT memories or state machines.
- TX capacity prediction, retained RX frame 17, empty reads, mirrored addresses, erroneous frames and reset during traffic.
- Four-register RAL for IER/LCR/DLL/DLM: separate maps, locked frontdoors, exact LCR restoration and passive bank prediction.
- Four selected boundary faults with clean before/after controls to check error detection.
- Independent APB agent qualification against a programmable peripheral with waits, error responses, reset cancellation and timeout recovery.
- An offline diagnostic workbench with run filters, coverage gaps, interactive real VCD traces, APB-event navigation and original log/source links.
- Pinned tools, seeds, source snapshots, native coverage databases and real UVM simulation in GitHub Actions.

### APB peripheral subsystem

The subsystem places the fixed PULP UART and an original 64 × 32-bit RAM / MBIST controller in one APB address space. The controller owns single-port RAM arbitration, the March C− sequence, and first-failure diagnostics. The `subsystem` UVM suite reuses the APB and UART agents for address, fault, recovery and reset checks. See the [subsystem specification and verification plan](docs/subsystem.md).

The subsystem passed **12/12 runs** across four tests and three seeds. The workbench links each run to its log, report and same-run VCD. Its implementation view compares the baseline controller and a one-buffer hold ECO under the same 10 ns pre-layout constraints. Worst hold slack moves from **−0.00636 ns** to **+0.00375 ns**, with setup worst slack at **+4.88060 ns**. The comparison links gate simulation and 58-cell scan evidence for both versions. [Verification plan](https://jiangzheyi1234-star.github.io/apb-uart-uvm/#plan) · [Implementation and DFT](https://jiangzheyi1234-star.github.io/apb-uart-uvm/#frontend)

## Requirements and setup

The toolchain uses Python 3.12, Verilator 5.054 and Accellera UVM 2020.3.1 with SHA-256-pinned source archives. [Full CI run 45321619200](https://github.com/jiangzheyi1234-star/apb-uart-uvm/actions/runs/45321619200) completed UART, RAL, upstream-baseline and independent APB protocol verification on GitHub Ubuntu 24.04 at source revision `127f21e0d695cd0e6aa32b46541b158196058679`. Questa/VCS entry points are provided; dynamic commercial-simulator results are not available.

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

### Independent APB protocol qualification

The UART DUT always drives `PREADY=1`. The reusable agent's wait and cancellation paths are exercised against an independent peripheral using `--suite apb_protocol` and `sim/files_protocol.f`. The default suite remains `uart`; the staging/build caches and test platforms are separate.

```bash
# Audit matrix: 9 positive runs, 3 expected raw timeout FAILs, 3 clean recovery controls
python3 py/run_protocol_checks.py --trace --out results/protocol

# One positive protocol class
python3 py/run_linux_regression.py --suite apb_protocol \
  --test apb_wait_state_test --seeds 1 --trace --out results/protocol_wait
```

Positive protocol runs require `APB_AGENT_TEST_PASS`; UART runs retain `UART_UVM_TEST_PASS`. A timeout is classified as `DETECTED` only with exactly one `APB_TIMEOUT`, activation and recovery-completion markers, normal exit, zero fatals, completed recovery traffic and matching binary/source identity. Its raw status remains `FAIL`. Protocol counts do not contribute to UART frame totals or functional coverage. See the [protocol contract](docs/apb_protocol.md).

Reproduce the original-RTL requirement failures separately:

```bash
RTL_VARIANT=upstream bash scripts/run_full_regression.sh --out results/upstream
# The upstream command should exit 1. Run acceptance separately, without &&.
python3 py/validate_acceptance.py --fixed results/core/report.json \
  --upstream results/upstream/report.json --out results/acceptance.json
```

## Current measured results

These results come from the completed CI run above. UART, upstream defect reproduction, checker controls and APB protocol checks retain separate scopes and raw outcomes. See [validation](docs/validation.md) for provenance and metric definitions.

| Scope | Measured result |
| --- | --- |
| Fixed core suite | 45/45 PASS; 1,039 TX + 1,216 RX frames |
| RAL suite | 3/3 PASS; 168 writes and 291 mirror reads |
| Core + RAL | 48/48 PASS; 16 scenarios and 2,261 frames |
| Upstream core baseline | 33/45 PASS; 12/45 strict-requirement raw FAILs |
| Checker controls | 4/4 intended raw FAILs classified DETECTED; 6/6 clean PASS controls |
| Independent APB protocol | 9/9 positive PASS; 3/3 raw timeout FAILs classified DETECTED; 3/3 clean recovery PASS |
| Linux Python tool tests | 74/74 PASS |
| Two-core-matrix acceptance | 100/100 checks passed |
| Core functional bins | 272/277, 98.19% |
| Frame-format / baud cross | 96/96 |
| RTL LCOV lines / branches | 453/474, 95.57% / 1,670/2,120, 78.77% |

The CI run executed 118 simulation processes: fixed core 45, RAL 3, upstream core 45, checker controls 10 and APB protocol 15. **48/48** refers only to the fixed UART core and RAL. Expected faulty runs retain raw FAIL; the 118 processes are not an all-PASS regression. Coverage comes only from the 45-run fixed core suite, without merging RAL or protocol measurements; five invalid-pending diagnostic bins remain unhit.

All three RAL seeds have zero `RegModel` warnings. Each run still records two UVM library warnings. The evidence archive retains the full logs and corresponding source identity.

## Interactive workbench

Choose a verification item to see its mapped UVM tests and recorded outcomes. Select a FAIL to inspect its diagnostic excerpt, full log and same-run waveform when archived. [Plan and regressions](https://jiangzheyi1234-star.github.io/apb-uart-uvm/#plan)

The report homepage uses the [verification workbench](https://jiangzheyi1234-star.github.io/apb-uart-uvm/). UART core, RAL, checker controls and APB qualification retain separate scopes and raw outcomes. Real VCD traces support a cursor, zoom, pan and APB-event navigation. APB responses use values immediately before the rising clock edge, preserving sampled read data when the peripheral updates its outputs after the edge. Trace decoding is diagnostic; it does not replace the UVM checker.

Static evidence pages remain available for [UART regression](docs/release/index.html), [RAL/checker controls](docs/features/index.html) and [APB protocol checks](docs/protocol/index.html). The [workbench documentation](docs/dashboard.md) explains generation, input validation and offline use.

## Documentation and distributions

[Architecture](docs/architecture.md) · [Registers](docs/registers.md) · [Verification plan](docs/verification_plan.md) · [RTL findings](docs/rtl_findings.md) · [Local fixes](docs/rtl_fixes.md) · [RAL](tb/ral/README.md) · [Coverage analysis](docs/coverage_analysis.md) · [Checker controls](docs/checker_sensitivity.md) · [APB protocol](docs/apb_protocol.md) · [Workbench](docs/dashboard.md)

`rtl/` retains the original import; `rtl_fixed/` contains documented local changes. `tb/`, `sim/`, `py/`, `scripts/` and `tests/` contain the verification environment, simulator integration and tools.

Releases provide separate source, evidence and raw CI archives with `SHA256SUMS`. The source archive contains the `web/dashboard/` templates and excludes generated simulation output and downloaded tools. The evidence archive supplies `docs/index.html`, `docs/assets/`, `docs/data/` and the `release/features/protocol` reports. Overlay matching archives at the source root, then open `docs/index.html` directly for offline use without a server or CDN. The two archives use distinct per-file manifests.

[Release procedure](RELEASE.md) · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md)

## Scope and licensing

The DUT is [pulp-platform/apb_uart_sv](https://github.com/pulp-platform/apb_uart_sv) at `dfad6e04d19cc9481d3cd2750b45b970dc61271b`. Register offsets are bytes 0–7; the bit period is divisor + 1 clocks. TX has 16 FIFO entries plus a serializer; RX can retain one additional waiting frame.

Scope excludes complete 16550 compatibility, arbitrary baud mismatch, active TX FIFO clear, continuous RX overrun, configuration changes during traffic and four-state signoff.

The original and derived RTL retain Solderpad Hardware License 0.51. Original verification code, tools and documentation use MIT. See [LICENSE](LICENSE), [NOTICE](NOTICE.md) and the [upstream manifest](third_party/apb_uart_sv/manifest.json).
