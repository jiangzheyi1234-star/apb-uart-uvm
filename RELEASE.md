# Release procedure

Release tags use semantic versioning. A published tag identifies a fixed source revision. Changes to distribution or documentation use a new patch version rather than replacing an archive under an existing public version.

## Distribution contents

| Asset | Contents |
| --- | --- |
| `apb-uart-uvm-<version>-source.zip` | RTL, testbench, simulation integration, Python tools/tests, authored workbench UI under `web/`, pinned setup scripts, technical documentation and licenses. Excludes generated simulation reports, tool downloads and build caches. |
| `apb-uart-uvm-<version>-evidence.zip` | Measured reports, archived logs, VCDs, coverage databases, LCOV, source snapshots and CI metadata under `docs/`. Includes the APB protocol, RAM/MBIST, baseline and hold-repair frontend evidence alongside the workbench. |
| `apb-uart-uvm-<version>-ci.zip` | Original files downloaded from the release verification workflow artifact, plus a per-file manifest. The run identity is recorded in `ci_context.json`. |
| `SHA256SUMS` | SHA-256 hashes for the three ZIP assets. |

The source and evidence archives retain project-relative paths. Extract both into the same directory to open `docs/index.html`, `docs/release/index.html`, `docs/features/index.html` and `docs/protocol/index.html` offline. Their manifests are named `MANIFEST.source.sha256` and `MANIFEST.evidence.sha256`, so extraction does not overwrite either manifest. Extract the raw CI archive into a separate directory; its own manifest is `MANIFEST.sha256`.

The evidence records the source revision at simulation time. Original upstream failures and injected-fault failures remain FAIL. `DETECTED` describes an expected checker response, not a passing DUT simulation. Reported local results and a later CI run retain their own provenance.

## Prepare a release

1. Update `CHANGELOG.md` and review the RTL/verification scope.
2. Run the Python suite and verify the pinned upstream import.
3. Execute GitHub verification. For a complete acceptance release, dispatch the workflow with `full_regression=true` and require the upstream comparison and acceptance step to succeed.
4. Build both distribution profiles from the reviewed checkout.
5. Download the successful run's artifact without editing its raw contents. Archive it with its run context and a SHA-256 manifest.
6. Check all archive manifests, source/evidence boundaries, licenses and report links. Generate `SHA256SUMS`.
7. Create the version tag and Release, upload the three archives and checksums, then verify the tag SHA and the downloaded assets.

```bash
python3 -m unittest discover -s tests -v
python3 py/verify_rtl.py
python3 py/package_project.py --profile source \
  --out dist/apb-uart-uvm-1.2.0-source.zip
python3 py/package_project.py --profile evidence \
  --out dist/apb-uart-uvm-1.2.0-evidence.zip
```

Download a released version from [GitHub Releases](https://github.com/jiangzheyi1234-star/apb-uart-uvm/releases/latest). Linux can verify assets with `sha256sum -c SHA256SUMS`; Windows PowerShell can compare `Get-FileHash -Algorithm SHA256` with that file.

## Verification requirements

- PASS requires normal process completion, the explicit UVM completion marker, a complete UVM summary and zero UVM_ERROR/UVM_FATAL counts.
- Upstream acceptance requires the exact expected functional failure set. An arbitrary failure, timeout or crash does not qualify.
- Fault controls must activate the requested injection and trigger exactly the intended checker ID, with clean controls before and after.
- APB timeout qualification requires the exact intended error, normal process completion, same-binary provenance and clean recovery. Its deliberately failing runs remain FAIL.
- Generate the workbench from hash-verified bundles. VCD event reconstruction is diagnostic evidence; it does not replace the independent monitor or protocol checker.
- Functional bins and RTL line/branch coverage are separate metrics. Keep their denominators and remaining coverage gaps visible.
- Preserve original third-party licenses and byte-identical upstream files.
