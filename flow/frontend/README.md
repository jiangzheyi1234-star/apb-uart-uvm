# APB RAM/MBIST controller mapping, STA and scan checks

This flow executes real Yosys technology mapping, OpenSTA analysis and Icarus
RTL/gate comparisons for `rtl_subsystem/apb_ram_mbist.sv`. The 64×32 RAM is an
external synchronous interface. Area and timing measurements cover the mapped
controller and its interface ports.

## Reproduce

On Ubuntu 24.04, install `yosys`, `iverilog`, `build-essential`, `cmake`,
`tcl-dev`, `swig`, `libeigen3-dev`, `zlib1g-dev`, `flex` and `bison`. Run the
following commands from the repository root.

```bash
python3 scripts/frontend/bootstrap.py --build --jobs 2
python3 scripts/frontend/run_flow.py --out results/frontend_controller_new
```

Use a new output directory. The current constraints expose a real hold
violation, so the second command returns **1** and records
`status: TIMING_VIOLATION`. The report also records the results of tool
execution, gate simulation and scan checks.

The bootstrap can download and verify inputs on Windows without `--build`.
Use these commands with the existing WSL Ubuntu environment.

```powershell
python scripts/frontend/bootstrap.py
wsl --distribution Ubuntu --cd $PWD --exec python3 scripts/frontend/bootstrap.py --build --jobs 2
wsl --distribution Ubuntu --cd $PWD --exec python3 scripts/frontend/run_flow.py --out results/frontend_controller_new
```

Tool builds and actual EDA execution use ASCII `/var/tmp/` paths. The flow
copies complete records into the requested output directory, including the
original source, constraints, generated scripts, mapped/scan netlists,
Liberty-derived zero-delay models, scan order, min/max paths, simulation logs,
VCD and SHA-256 artifact manifest.

## Pinned inputs and licenses

[`toolchain.lock.json`](toolchain.lock.json) fixes source commits, URLs, sizes
and SHA-256 for official OpenSTA, CUDD and the public Nangate45 typical Liberty
from OpenROAD-flow-scripts. OpenSTA is GPL-3.0-or-later; CUDD retains its
source license. The original Nangate Liberty copyright/header is retained in
derived cell models, and the platform `LICENSE` is copied as `NANGATE_LICENSE`.
Bootstrap caches keep complete tool source licenses and build the OpenSTA
binary locally. The report records the Ubuntu Yosys and Icarus versions used
for each execution.

## Measured controller result

The initial complete run used Yosys 0.33 (`2584903a060`), OpenSTA 3.2.0 built
from the locked commit, and Icarus 12.0.

| Item | Actual result |
| --- | --- |
| Original mapped controller | 559 cells, including 58 `DFFR_X1` |
| Original mapped cell area | 829.388 µm² for the controller logic |
| Functional differential checks | 2,711 checked cycles and 877 APB transactions; RTL, mapped logic and scan logic agree |
| Clean March C− | 640 native operations, split into 320 reads and 320 writes |
| Selected stuck-bit case | Address 63, bit 3 stuck at zero; first failure at March step 2, expected `0xffffffff`, actual `0xfffffff7` |
| Logical scan insertion | One chain with 58 mapped `SDFFR_X1` cells |
| Shift checks | 232 bits checked with all-zero, all-one, first-position-one and alternating patterns |
| Functional capture/shift-out | 32 `actual_q` bits checked against independent expected response `0xfffffff7` |
| Setup worst slack | +4.88060 ns |
| Hold worst slack | −0.00636 ns, reported as a violation |

`scan_chain.json` lists every chain index, original/scan cell and original Q
net. A deterministic transform replaces and connects the cells in the mapped
netlist. The experiment covers directed scan transport and a functional capture
followed by shift-out of the MBIST diagnostic. The testbench inhibits external
RAM accesses while `SCAN_EN=1` because shifting can toggle the controller RAM
controls. ATPG fault grading, physical chain ordering, production RAM isolation
and scan/reset distribution would require a wider DFT flow.

## Timing assumptions and remaining boundary

[`controller.sdc`](controller.sdc) uses one 10 ns ideal clock, 0.1 ns clock
uncertainty, 2 ns maximum and 0.2 ns minimum I/O delays, 50 ps input
transition, and 10 fF output load. The external RAM interface uses the same
explicit I/O budget. The budget models the external boundary for this run.

The library corner is typical process, 1.1 V, 25 °C. Reset is deasserted for
functional analysis and its path is explicitly excluded. Reset distribution,
release synchronization and recovery/removal are outside this run. The analysis
uses ideal clocks, nominal cell timing and the declared external loads.

The measured worst hold path is `_1039_/QN` → `_0769_` (`NAND2_X1`) →
`_0770_` (`NOR4_X1`) → `_1039_/D`. The arrival is 0.09633 ns and the required
time is 0.10268 ns. Full paths and constraints remain in `sta.log`. Timing
closure requires a separately measured optimization and physical flow.

Gate simulation uses zero-delay cell models generated from the same Liberty,
three separate RAM models and the recorded smoke stimuli. The comparisons
cover functional behavior exercised by the selected APB and scan scenarios.

## Guarded hold repair

The optional repair flow inserts one non-inverting `BUF_X1` on the D input of
the mapped `apb_read_pending_q` flop. It keeps the RTL, Liberty, SDC, 10 ns
clock and 0.1 ns uncertainty unchanged. The ordinary command above continues
to run the unrepaired baseline and report its real timing violation.

```bash
python3 -m unittest discover -s scripts/frontend -p test_hold_repair.py -v
python3 scripts/frontend/run_flow.py --hold-repair --out results/frontend_hold_new
```

The flow finds the unique logical Q net and checks its clock/reset, QN-to-NAND
feedback, NOR next-state driver, sole D consumer and actual worst hold path.
It rejects changed or ambiguous topology instead of applying a buffer solely
by a generated cell number. `hold_eco.json` records the original/new nets,
cell/pin edits, before/after netlist SHA-256, unchanged RTL/library/SDC hashes
and measured buffer delay. Yosys structural checking confirms one added cell
and unchanged flip-flop count. The complete gate/scan tests run on the repaired
netlist, followed by global setup/hold analysis and a targeted report of the
repaired path.

| Measured typical pre-layout result | Baseline | One-buffer ECO |
| --- | ---: | ---: |
| Standard cells | 559 | 560 |
| Flip-flops | 58 | 58 |
| Controller area | 829.388 µm² | 830.186 µm² |
| Global setup slack | +4.88060 ns | +4.88060 ns |
| Global hold slack | −0.00636 ns | +0.00375 ns |
| Original pending-read path hold slack | −0.00636 ns | +0.01728 ns |

The original short path is the synchronous-read pending flag's QN-to-D
feedback. The buffer contributes 0.02395 ns on the measured repaired path.
The global minimum then moves to `_1017_`; the flow checks the new global
worst path rather than stopping at the repaired endpoint. These positive
slacks apply to the same single typical, ideal-clock, pre-layout assumptions;
they do not establish physical or multicorner signoff.

Outputs preserve `baseline_mapped.v`, `baseline_synthesis_statistics.txt`,
`baseline_sta.log`, readable before/after min/max paths, `timing_paths.json`
and the original gate/VCD evidence. The repaired report's `synthesis`, `sta`,
`gate_simulation` and `scan` describe the repaired implementation; its
`baseline` section retains the measured violation. Old published baseline
evidence remains unchanged.
