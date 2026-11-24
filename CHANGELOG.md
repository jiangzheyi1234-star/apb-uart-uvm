# Changelog

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
