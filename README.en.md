# APB UART UVM Verification

[![UART verification](https://github.com/jiangzheyi1234-star/apb-uart-uvm/actions/workflows/verification.yml/badge.svg)](https://github.com/jiangzheyi1234-star/apb-uart-uvm/actions/workflows/verification.yml)

[中文](README.md) · [Measured core evidence](https://jiangzheyi1234-star.github.io/apb-uart-uvm/release/) · [RAL and checker evidence](https://jiangzheyi1234-star.github.io/apb-uart-uvm/features/)

A SystemVerilog/UVM project built around a pinned PULP APB UART, with independent serial observation, a cycle-level FIFO reference model, bank-aware register access, and auditable before/after RTL defect evidence.

## What you can inspect

- **Two-way independent checking:** observed THR writes predict TX frames; a separate pin decoder checks the actual serial output. RX pin observations predict subsequent RBR reads. The scoreboard does not inspect internal DUT memories or state machines.
- **A scoped bank-aware RAL:** IER, LCR, DLL and DLM use normal/banked maps, an APB adapter, a sequencer-locked frontdoor that restores the actual LCR, and passive prediction from completed APB transactions. Destructive FIFO ports are handled by transaction checks.
- **Measured negative controls:** four selected faults corrupt TX data, RX readback, PE status or IRQ. Each reaches its intended checker; six clean before/after controls pass. This tests sensitivity to those faults, not exhaustive mutation coverage.
- **Reproducible evidence:** raw failures, logs, VCDs, native coverage databases, tool versions, source snapshots, SHA-256 manifests and a real GitHub workflow are retained.

## Measured local results

| Check | Result |
| --- | --- |
| Core suite | 45/45 PASS, 15 tests × 3 seeds |
| Additional RAL suite | 3/3 PASS, one test × 3 seeds |
| Core + RAL feature runs | 48/48, 16 scenarios, 2,261 compared TX/RX frames |
| RAL operations | 168 frontdoor writes and 291 checked mirror reads |
| Negative controls | 4/4 intended detections, 6/6 clean controls |
| Core functional bins | 272/277, 98.19% unweighted hit ratio |
| Frame-format / baud cross | 96/96 |
| RTL LCOV lines / branches | 453/474, 95.57% / 1,670/2,120, 78.77% |

These are actual Verilator 5.054 / Accellera UVM 2020.3.1 runs. The original RTL produces 12 genuine functional failures in four strict requirements at three seeds; the corresponding fixed runs pass. Failures remain FAIL in raw reports. Five invalid-pending diagnostic bins remain uncovered on correct RTL; no new exclusions were introduced to raise the result.

The 48 runs comprise core 45 (2,255 frames) plus RAL 3 (6 frames). The separate checker campaign runs 4 intended raw FAILs and 6 clean PASS controls; these 10 processes are outside that denominator. The coverage figures come from the 45-run core suite.

The CI badge links to the observed remote workflow status. Questa/VCS entry points and UVM 1.2 static compatibility are provided, but no commercial-simulator dynamic results are claimed.

## Quick start on Linux or WSL

```bash
git clone https://github.com/jiangzheyi1234-star/apb-uart-uvm.git
cd apb-uart-uvm

sudo apt-get update
sudo apt-get install -y --no-install-recommends build-essential autoconf \
  flex bison libfl-dev zlib1g-dev help2man ca-certificates z3

bash scripts/bootstrap_verilator.sh
bash scripts/run_full_regression.sh --out results/my_core
python3 py/run_mutation.py --baseline-report results/my_core/report.json \
  --out results/my_checker_controls
python3 py/run_linux_regression.py --rtl fixed --test uart_ral_test \
  --seeds 1 2 3 --coverage --trace --out results/my_ral
```

Use a fresh output directory for every run. The staging helper verifies copied source bytes and uses an ASCII Linux path, including when the original Windows workspace contains Unicode characters.

For the original-RTL defect reproduction, preserve its real failing exit code:

```bash
RTL_VARIANT=upstream bash scripts/run_full_regression.sh --out results/my_upstream
python3 py/validate_acceptance.py --fixed results/my_core/report.json \
  --upstream results/my_upstream/report.json --out results/my_acceptance.json
```

The acceptance audit checks the exact core matrices, intended functional failures, source identity, seed replay, real logs and measured native coverage. Additional RAL and fault-sensitivity reports have their own independent checks.

## Review the engineering

[Architecture and test matrix](README.md) · [Register semantics](docs/registers.md) · [RTL findings](docs/rtl_findings.md) · [Local RTL fixes](docs/rtl_fixes.md) · [RAL implementation](tb/ral/README.md) · [Controlled faults](docs/checker_sensitivity.md) · [Open-source comparison](docs/industry_benchmark.md)

The design uses byte offsets 0–7, not word-strided offsets; the bit period is divisor + 1 clocks. TX has 16 FIFO entries plus a serializer, and RX can hold a 17th frame waiting for FIFO space. Those behaviors are explicitly modeled and tested.

Scope excludes complete 16550 compatibility, arbitrary baud mismatch, active TX FIFO clear, continuous RX overrun, configuration changes during active traffic, and four-state signoff.

## Attribution

`rtl/` is the unmodified PULP import at commit `dfad6e04d19cc9481d3cd2750b45b970dc61271b`. `rtl_fixed/` contains documented local changes. The derived RTL keeps Solderpad Hardware License 0.51. Original verification code, tools, CI and documentation use MIT. See [NOTICE](NOTICE.md) and [LICENSE](LICENSE).
