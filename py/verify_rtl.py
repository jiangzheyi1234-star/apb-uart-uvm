#!/usr/bin/env python3
"""Verify imported upstream files against their pinned Git blob IDs (offline)."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    manifest = json.loads((ROOT / "third_party/apb_uart_sv/manifest.json").read_text(encoding="utf-8"))
    failures = []
    for item in manifest["files"]:
        path = ROOT / item["path"]
        if not path.is_file():
            failures.append(item["path"] + " (missing)")
            continue
        # Git hashes bytes, including line endings. Vendored files are kept LF.
        content = path.read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(content)).encode("ascii") + b"\0" + content).hexdigest()
        if actual != item["git_blob_sha1"]:
            failures.append(item["path"] + " (modified)")
    if failures:
        print("RTL_INTEGRITY_FAIL: " + ", ".join(failures))
        return 1
    print(f"RTL_INTEGRITY_PASS: {len(manifest['files'])} files match commit {manifest['commit']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
