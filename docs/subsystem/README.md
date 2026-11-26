# Audited RAM / MBIST UVM evidence

This bundle contains twelve completed Verilator/UVM subsystem runs: four tests at seeds 1/2/3. No simulator or compiler was run to create the archive. Each run has its own transcript and byte-identical VCD.

[Runner report](report.json), [input hashes](inputs.json), and [normalization provenance](provenance.json) preserve the measured scope and distinguish raw from distributed SHA-256 values. Private local project-root prefixes in logs/JSON are replaced by `/project`; packaged log/VCD references are relative. Execution-record checksums such as `origin_map_sha256` still identify the raw, unnormalized records; use `inputs.json` for the public files. VCDs have not been normalized.

The four tests cover APB/RAM access, clean March C-minus, selected read-bit fault diagnosis and recovery, and reset interruption. A fault-test UVM PASS means the expected MBIST failure and recovery were checked. It does not mean the injected memory passed self-test or that all memory fault classes were covered.

The build-time source snapshot was checked against the working project and pinned UVM sources before archival. Executable and tool directories, native coverage databases and the full LCOV export are omitted. The coverage summary is a recorded summary; the omitted databases are not downloadable links.

Rebuild this directory into a fresh output with `python py/archive_subsystem_evidence.py --report results/subsystem_acceptance/report.json --out <fresh-directory>`. The original local execution and identical captured sources must be available.
