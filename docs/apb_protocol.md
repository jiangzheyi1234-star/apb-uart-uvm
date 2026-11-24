# Independent APB agent protocol verification

This suite verifies the reusable APB master driver and passive monitor against
an independent programmable peripheral. The UART always drives `PREADY=1`, so
the UART's core tests alone cannot demonstrate wait-state or timeout behavior.
This suite has a separate file list, test package, top and result denominator;
its transfers are not added to the UART core 45 runs or RAL three runs.

The peripheral implements sixteen word-addressed 32-bit locations, reset to
zero. It captures a programmed wait count during SETUP, can hold PREADY low,
and can complete with PSLVERR. Its defined error-write behavior is no commit;
this is a peripheral contract, not a claim that every APB peripheral has the
same error side effects.

| Test | Required behavior | Completed observations |
| --- | --- | ---: |
| `apb_wait_state_test` | Read/write at 0/1/3/7 waits, valid read sampling, error responses and error-write no commit | 11 |
| `apb_reset_abort_test` | Reset during wait, immediate driver cancellation, no false monitor completion, memory reset and recovery | 4 |
| `apb_timeout_control_test` | Seven waits succeed with an eight-stall timeout limit | 2 |
| `apb_timeout_requirement_test` | Deliberately held PREADY triggers exactly one real APB_TIMEOUT, followed by bus reset and recovery | 3 after reset |

Driver requests now expose additive `completed` and `timed_out` fields. Existing
`aborted` remains true for reset/timeout cancellation; a PSLVERR handshake is
completed, not aborted. `timeout_cycles` is configurable with `uvm_config_db`
and retains the UART environment's default of 64. A reset after an accepted
handshake does not retroactively turn that handshake into an abort.

Wait count means the number of sampled ACCESS cycles with PREADY low before
the accepted beat. The passive checker compares planned transfers against
monitor observations, and separately checks raw SETUP/access ordering and
stable address/direction/write data. Read data is valid at completion; the
slave can deliberately return poisoned read data during wait cycles. This
exposes early driver/monitor sampling without imposing a non-standard demand
that PRDATA remain constant before PREADY.

The reset test checks bus deassertion 1 ps after reset, before another clock
edge. The timeout control deliberately differs: timing out is a diagnostic,
not an APB-defined successful transaction. Its test resets the bus before the
next rising sample and proves later traffic works. The checker rejects access
withdrawal without reset. There is no report catcher or severity demotion.

Positive runs require `APB_AGENT_TEST_PASS` and a clean UVM summary. Every run
prints `APB_AGENT_STATS` with completed/read/write counts, wait-length counts,
maximum wait and reset/timeout abort counts. The explicit timeout run prints
`APB_TIMEOUT_ARMED` and `APB_TIMEOUT_SCENARIO_COMPLETE`, must remain raw FAIL,
must have only the `APB_TIMEOUT` error ID, zero fatals, normal process exit and
three independently checked recovery transfers. Crashes, watchdog exits,
missing activation/completion, or unrelated errors do not count as detection.

The file list is `sim/files_protocol.f`, with independent top `tb_top` in
`tb/protocol/tb_protocol_top.sv`. The runtime UART-fixed plusarg is not used.

## Executed results

[Complete CI run 45321619200](https://github.com/jiangzheyi1234-star/apb-uart-uvm/actions/runs/45321619200)
executed the suite on GitHub Ubuntu 24.04 using Verilator 5.054 and Accellera
UVM 2020.3.1, at source revision
`127f21e0d695cd0e6aa32b46541b158196058679`.

| Phase | Test/seed matrix | Raw simulation result | Independent audit |
| --- | --- | --- | --- |
| Positive | The three positive classes, seeds 1/2/3 | 9 PASS, zero errors/fatals | 9/9 PASS |
| Negative | `apb_timeout_requirement_test`, seeds 1/2/3 | 3 FAIL, exactly one APB_TIMEOUT each, zero fatals, normal exit | 3/3 DETECTED |
| Recovery control | `apb_wait_state_test`, seeds 1/2/3 | 3 PASS, zero errors/fatals | 3/3 PASS |

The fifteen simulations recorded 93 completed APB transfers in total: 51 in
the positive matrix, 9 after the three negative timeouts, and 33 in the clean
recovery controls. Reset/timeout cancellations were recorded separately and
did not become false completions. All phases used the same recorded binary
and source-snapshot identity; the audit rechecked current source bytes and
the binary after the controls.

`protocol_report.json` has audit status PASS while the three negative runs
retain raw FAIL. These 15 processes are separate from the UART's **48/48**
normal core/RAL runs and its 2,261 checked frames. The complete CI contained
118 simulation processes across the UART variants, RAL, fault controls and
this protocol suite. See [verification results](validation.md), the
[protocol report](protocol/index.html) and [machine-readable evidence](protocol/summary.json).

## Reproduce and inspect

From Linux/WSL with the pinned project tools installed:

```bash
python3 py/run_protocol_checks.py --trace --out results/protocol_new
python3 py/build_protocol_evidence.py \
  --report results/protocol_new/protocol_report.json --out results/protocol_evidence_new
```

Both output directories must be new or empty. The runner selects
`--suite apb_protocol`, uses a separate ASCII stage/build cache, and invokes
the compiler for each profile with incremental reuse allowed. The audit
requires unchanged binary and source identities across the profiles. It
rejects missing markers, unrelated errors, abnormal exits and incomplete
recovery. UART functional coverage export is disabled for this suite.

The evidence packager copies raw reports, source snapshots, stage-equality
maps, build/version logs and all 15 simulation logs without changing their
bytes. Three seed-1 VCDs cover wait states, reset cancellation and the timeout
negative. Packaging rechecks transcripts and recorded provenance; it does
not require the Linux executable to remain available on another computer.
The [offline workbench](dashboard.md) reconstructs diagnostic APB observations
from real pre-edge VCD values and links back to these original inputs.

## Limits

The suite qualifies selected agent behaviors against this peripheral model;
it does not establish wait-state behavior inside the UART, which always has
PREADY high. Error writes without side effects are the test peripheral's
contract, not a universal requirement on APB slaves. Timeout is a driver
diagnostic and requires reset before cancelling a stalled transfer; it is
not a successful APB completion. No claim is made for every wait length,
reset phase, arbitration combination, APB extension or four-state/X-propagation
case. Functional bins and UART RTL line/branch coverage remain separately
scoped, as documented in [coverage analysis](coverage_analysis.md).
