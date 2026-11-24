# Scoped APB UART register model

This independently authored SystemVerilog RAL model covers the implemented
stored RW registers **IER, LCR, DLL and DLM**. It does not claim a complete UART
register model or full register coverage.

| Map | Register | Byte offset | Required DLAB |
| --- | --- | ---: | ---: |
| normal_map | IER | 1 | 0 |
| normal_map | LCR | 3 | either |
| banked_map | DLL | 0 | 1 |
| banked_map | DLM | 1 | 1 |
| banked_map | LCR | 3 | either |

IER/DLL/DLM have a custom frontdoor that locks the APB sequencer, reads the
actual LCR, changes only DLAB if needed, performs the target access, and restores
the exact previous LCR before unlocking. LCR itself uses the normal map adapter.
Each register has its own frontdoor object so independent accesses can contend
without sharing a mutable frontdoor operation.

The block creates/configures each frontdoor before calling
`add_reg(register, offset, "RW", 0, frontdoor)`. The fourth argument remains zero
so the register retains a physical byte offset for passive prediction. The test
then calls `lock_model()` after `build()`, and connects the APB sequencer/adapter
after locking. Connection checks query the three installed frontdoors only after
map initialization. No report severity, warning action or UVM library code is
changed.

This order follows the local official Accellera UVM 2020.3.1 implementation:
`src/reg/uvm_reg_map.svh` declares the frontdoor as the fifth `add_reg` argument,
and stores it directly in the map entry. In contrast,
`uvm_reg::set_frontdoor()` calls `get_reg_map_info()`, which warns if queried before
`lock_model()` initializes the address maps. UVM 1.2 provides the same `add_reg`
signature and lifecycle. These source files can be checked under the official
source trees selected by `py/check_sv.py --uvm-home`; they are dependencies, not
modified project sources.

`uart_bank_predictor` extends the UVM explicit predictor. It tracks DLAB from
observed, completed APB transactions, canonicalizes high address aliases, selects
exactly one map, and resets mirrors on hardware reset. Both maps have
auto-prediction disabled. Thus mirror assertions cannot pass merely because a
RAL write predicted itself.

RBR/THR FIFO ports, FCR/IIR read/write aliases, LSR status and the unimplemented
MCR/MSR/SCR registers are outside automatic mirroring. The existing agents and
transaction scoreboard retain responsibility for their side effects. The model
has no HDL backdoor and no new covergroups; the existing 277-bin coverage plan
remains unchanged. Reset is exercised while RAL operations are idle; cancellation
and restart of an active RAL sequence during reset are not claimed here.

`uart_ral_test` checks reset mirrors, 12 randomized RW iterations in alternating
DLAB states, exact bank/format restoration, concurrent normal/banked accesses,
raw APB prediction including high aliases, and a final bidirectional data exchange.
The concurrent check uses LCR `0xF3` (DLAB=1, stored format bits `[6:4]=111`, active
8N1 format), then reads LCR through raw APB and compares the full returned word
with the expected value independently of the RAL mirror. This adds one APB read
per test without changing the 56 RAL writes, 97 mirror reads, 12 randomized
iterations or two final data frames. The passive banked prediction count includes
that additional read. The read also passes through the existing transaction
Scoreboard; it does not add side-effect registers to the RAL model.

Include these declarations after the APB classes, in this order:

1. `ral/uart_apb_reg_adapter.sv`
2. `ral/uart_dlab_frontdoor.sv`
3. `ral/uart_reg_block.sv`
4. `ral/uart_bank_predictor.sv`

Include `test/uart_ral_test.sv` after `test/base_test.sv`. The optional test builds
and connects its own register model/predictor; existing test and environment
classes need no changes.
