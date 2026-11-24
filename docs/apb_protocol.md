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
Actual measured results must be taken from the protocol runner's generated
report and logs; this document does not assert an unexecuted PASS.
