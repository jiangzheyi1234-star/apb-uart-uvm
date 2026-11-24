# Changelog

## Unreleased

- Open raw failures, the APB timeout trace and core coverage gaps directly from the dashboard overview.
- Jump to recorded APB wait or exception events. Open the matching run, log and report from a trace, and return to the previous regression filters and page.
- Fit all six navigation entries on narrow screens.

## 1.2.0 — 2026-11-24

### Added

- Independent APB agent qualification with a programmable slave, 0/1/3/7 wait states, completion-time data, PSLVERR/no-commit checks, asynchronous reset cancellation, bounded timeout detection and recovery controls.
- A 15-process protocol campaign: nine positive runs, three deliberate timeout failures detected by the intended checker, and three clean recovery runs. Raw FAIL results remain unchanged.
- An offline diagnostic workbench with regression filters/CSV export, separate coverage scopes and gaps, interactive VCD waveforms, reconstructed APB events, source-linked architecture and upstream/fixed defect comparisons.
- Evidence generation that verifies source snapshots, log counters, native coverage databases and input hashes before publishing 118 measured runs, eight traces and 230 hashed inputs.

### Fixed

- Bind RAL frontdoors during register-map construction, before locking the model; verify full LCR restoration independently on APB. The three measured RAL runs have no RegModel warnings.
- Cancel in-flight APB waits promptly on asynchronous reset, preserve completed handshakes, and expose completed/aborted/timed-out transaction outcomes explicitly.

### Verified

- [Full verification run](https://github.com/jiangzheyi1234-star/apb-uart-uvm/actions/runs/45321619200): 74 Python tests, 100 acceptance checks, UART core 45/45 and RAL 3/3 PASS; upstream 33 PASS/12 strict functional FAIL; checker controls six PASS/four detected failures; protocol controls twelve PASS/three detected failures.
- UART coverage remains 272/277 functional bins, 453/474 RTL lines and 1670/2120 RTL branches. Protocol qualification and negative controls have separate scopes.

## 1.1.2 — 2026-11-24

### Fixed

- Use explicit HTML filenames for report navigation so the evidence archive opens correctly without an HTTP server.

RTL, SystemVerilog verification and distribution-tool behavior are unchanged from 1.1.1.

## 1.1.1 — 2026-11-24

### Changed

- Organize the public documentation around setup, architecture, register semantics, verification scope and reproducible results.
- Separate source and generated verification evidence into distinct release archives with independent SHA-256 manifests.
- Restrict source distribution to engineering files and an explicit technical-document allowlist.
- Retain a single current report set; remove superseded generated reports from the default branch.
- Document release verification, archive contents and offline report extraction.

### Added

- Distribution tests for archive boundaries, reproducibility, checksum manifests, offline links and symlink traversal.

The UART RTL and SystemVerilog verification behavior are unchanged from 1.1.0.

## 1.1.0 — 2026-11-24

- APB/UART agents, independent serial scoreboard, cycle-level FIFO model, assertions and functional coverage.
- DLAB-aware four-register RAL with locked frontdoors and passive bank prediction.
- Four checker fault controls and six clean before/after controls.
- Pinned Verilator/UVM tool setup, multi-seed regression and GitHub Actions verification.
- Original-RTL defect reproduction and a separately maintained local RTL fix set.

[Compare 1.1.0…1.1.1](https://github.com/jiangzheyi1234-star/apb-uart-uvm/compare/v1.1.0...v1.1.1)
