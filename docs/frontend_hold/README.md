# Measured controller hold repair

The original published baseline in `../frontend/` is unchanged. This bundle records an actual single-BUF_X1 mapped-netlist ECO at the APB read-pending flop D pin, with unchanged RTL, original 10 ns SDC and pinned Nangate45 typical library.

`inputs/baseline_sta.log` and `inputs/baseline_mapped.v` are the same-run pre-ECO records. `inputs/sta.log`, mapped/scan netlists, gate log and `inputs/gate_smoke.vcd` belong to the repaired execution. `timing_paths.json` and the precise path text distinguish the repaired endpoint from the new global worst endpoint. The original gate/scan viewer remains an independent archived baseline execution. Optional `repeat/` and `fresh_baseline/` records identify their own executions and do not replace the primary VCD.

The API checks hashes, same-source/constraint/library assumptions, exact one-buffer connectivity, actual STA paths, gate/scan counters and actual VCD samples. Scope remains one typical pre-layout corner with ideal clock and external RAM I/O budgets, zero-delay gate comparison and logical scan checks; this is not multi-corner physical signoff.

Validate: `python py/hold_evidence.py --check docs/frontend_hold --baseline docs/frontend`. Regenerate into a fresh directory using `--report results/frontend_hold_final/report.json --repeat results/frontend_hold_repeat/report.json --fresh-baseline results/frontend_hold_baseline_current/report.json --baseline docs/frontend --out <fresh-directory>`. No EDA process runs during publication.
