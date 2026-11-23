# Contributing

Keep `rtl/` byte-identical to the pinned upstream import. Submit design changes under `rtl_fixed/`, describe the behavior change, and add a strict requirement that fails on the old behavior and passes after the fix.

Run `python -m unittest discover -s tests -v` and `python py/verify_rtl.py` before submitting changes. A Linux/WSL setup with the pinned Verilator and UVM sources can run `bash scripts/run_full_regression.sh --out results/<new-directory>`.

Retain raw FAIL results for negative controls and upstream defect reproductions. Do not edit old logs, coverage counters, or source snapshots to match a later implementation. Generate new reports in a new output directory. Coverage must identify its denominator, source scope, exclusions, and tool version.

Changes to register handling should exercise both DLAB banks, preserve LCR framing bits, and test passive mirror prediction. Changes to checkers should include a passing control and a measured injected-fault detection case.

The public repository does not contain personal resumes, tool installation caches, simulator build caches, account credentials, or unrelated workspace files. Keep those outside tracked paths.
