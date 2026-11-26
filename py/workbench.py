#!/usr/bin/env python3
"""Build a portable, offline verification workbench from a manifest or JUnit XML."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import sys
from tempfile import TemporaryDirectory
from urllib.parse import quote
from xml.etree import ElementTree

from build_dashboard import ROOT, bind_verification_plan, require, write_dashboard
from package_project import is_link
from run_regression import file_digest
from waveform_data import read_interface_vcd


RUN_STATUSES = {"PASS", "FAIL", "ERROR", "SKIP", "TIMEOUT", "DRY_RUN"}
ARTIFACT_FIELDS = {"log": "log_url", "report": "report_url", "vcd": "vcd_url"}
JUNIT_RESULTS = {"failure": "FAIL", "error": "ERROR", "skipped": "SKIP"}
JUNIT_ATTACHMENT = re.compile(r"\[\[ATTACHMENT\|([^\r\n]*?)\]\]")


def string(value, field: str) -> str:
    require(isinstance(value, str) and bool(value.strip()), f"{field} must be a nonempty string")
    return value


def objects(value, field: str) -> list[dict]:
    require(isinstance(value, list) and all(isinstance(item, dict) for item in value),
            f"{field} must be an array of objects")
    return value


@contextmanager
def new_directory(output: Path):
    output = output.absolute()
    require(not output.exists() and not is_link(output), f"Output directory already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".workbench-", dir=output.parent) as temporary:
        staging = Path(temporary) / "site"
        staging.mkdir()
        yield staging
        require(not output.exists() and not is_link(output), f"Output directory already exists: {output}")
        staging.rename(output)


def artifact_path(base: Path, name: str, *, location: str = "manifest directory") -> Path:
    parts = name.split("/")
    require(not any(part in ("", "..") for part in parts) and not re.search(r"[\\:\x00-\x1f]", name),
            f"Artifact must be relative to the {location}: {name}")
    path = base
    for part in parts:
        path /= part
        require(not is_link(path), f"Artifact path traverses a link: {name}")
    require(path.is_file() and path.resolve().is_relative_to(base), f"Artifact file is missing or outside its input directory: {name}")
    return path


def stage_artifact(base: Path, source: Path, staging: Path, inputs: dict, *, directory: str) -> dict:
    relative = f"{directory}/{source.resolve().relative_to(base).as_posix()}"
    if relative not in inputs:
        target = staging / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        inputs[relative] = {"path": relative, "url": quote(relative), "sha256": file_digest(target),
                            "bytes": target.stat().st_size}
    return inputs[relative]


def build(manifest: dict, base: Path, output: Path, *, attachments_root: Path | None = None) -> dict:
    require(isinstance(manifest, dict) and type(manifest.get("schema_version")) is int and manifest["schema_version"] == 1,
            "Expected workbench manifest schema_version 1")
    meta = manifest.get("project")
    require(isinstance(meta, dict), "project must be an object")
    project = {"title": string(meta.get("title"), "project.title"),
               "generated_utc": datetime.now(timezone.utc).isoformat()}
    for field in ("version", "commit", "source_note"):
        if field in meta:
            project[field] = string(meta[field], f"project.{field}")

    suites = [{"id": string(item.get("id"), "suite.id"), "title": string(item.get("title"), "suite.title")}
              for item in objects(manifest.get("suites"), "suites")]
    suite_ids = {suite["id"] for suite in suites}
    require(suite_ids and len(suite_ids) == len(suites), "Expected one or more suites with unique IDs")

    base = base.resolve()
    if attachments_root is not None:
        require(not is_link(attachments_root) and attachments_root.is_dir(),
                f"Attachment root must be a real directory: {attachments_root}")
        attachments_root = attachments_root.resolve()
    runs, waves, inputs = [], [], {}
    run_ids = set()
    with new_directory(output) as staging:
        for item in objects(manifest.get("runs"), "runs"):
            run_id = string(item.get("id"), "run.id")
            suite = string(item.get("suite_id"), f"{run_id}.suite_id")
            status = string(item.get("raw_status"), f"{run_id}.raw_status")
            require(run_id not in run_ids, f"Duplicate run ID: {run_id}")
            require(suite in suite_ids, f"Unknown suite for {run_id}: {suite}")
            require(status in RUN_STATUSES, f"Unsupported status for {run_id}: {status}")
            run_ids.add(run_id)
            seed = item.get("seed")
            require(seed is None or (type(seed) is int and 0 <= seed < 2**53), f"Invalid seed for {run_id}")
            row = {"id": run_id, "suite_id": suite, "test": string(item.get("test"), f"{run_id}.test"),
                   "seed": seed, "raw_status": status}
            for field in ("variant", "phase"):
                if field in item:
                    row[field] = string(item[field], f"{run_id}.{field}")
            if "failure_excerpt" in item:
                excerpt = item["failure_excerpt"]
                require(isinstance(excerpt, list), f"{run_id}.failure_excerpt must be an array of strings")
                row["failure_excerpt"] = [string(line, f"{run_id}.failure_excerpt") for line in excerpt]

            vcd_path = None
            for field, key in ARTIFACT_FIELDS.items():
                if field not in item:
                    continue
                name = string(item[field], f"{run_id}.{field}")
                source = artifact_path(base, name)
                record = stage_artifact(base, source, staging, inputs, directory="evidence")
                row[key] = record["url"]
                if field == "vcd":
                    vcd_path = staging / record["path"]

            if attachments_root is not None and item.get("attachments"):
                artifacts = []
                seen = set()
                for raw_name in item["attachments"]:
                    name = string(raw_name, f"{run_id} JUnit attachment path")
                    try:
                        source = artifact_path(attachments_root, name, location="attachment root")
                        record = stage_artifact(attachments_root, source, staging, inputs,
                                                directory="evidence/attachments")
                    except (ValueError, OSError) as error:
                        raise ValueError(f"{run_id} JUnit attachment: {error}") from error
                    if record["path"] in seen:
                        continue
                    seen.add(record["path"])
                    artifacts.append({"name": name, "path": record["path"], "url": record["url"]})
                    primary = {".log": "log_url", ".vcd": "vcd_url"}.get(source.suffix.lower())
                    if primary:
                        row.setdefault(primary, record["url"])
                row["artifacts"] = artifacts

            if "signals" in item:
                requested = item["signals"]
                require(vcd_path is not None and isinstance(requested, list) and bool(requested),
                        f"{run_id}.signals needs a VCD and a nonempty array of names")
                names = [string(name, f"{run_id}.signals") for name in requested]
                require(len(set(names)) == len(names), f"Duplicate VCD signal name for {run_id}")
                try:
                    trace = read_interface_vcd(vcd_path, signal_names=names)
                except (ValueError, OSError, IndexError) as error:
                    raise ValueError(f"VCD for {run_id}: {error}") from error
                require(trace["range"][1] > trace["range"][0],
                        f"VCD for {run_id} has no advancing time; omit signals to archive it without a preview")
                signals = [{key: trace["signals"][name][key] for key in ("id", "label", "width", "events")}
                           for name in names]
                waves.append({"id": f"vcd:{run_id}", "run_id": run_id, "title": row["test"], "kind": "generic",
                              "unit": trace["unit"], "range": trace["range"], "signals": signals,
                              "source": {"url": row["vcd_url"], "sha256": trace["sha256"]}})
            runs.append(row)

        data = {"schema_version": 1, "mode": "portable", "project": project, "suites": suites,
                "runs": runs, "waveforms": waves, "inputs": list(inputs.values())}
        if "verification_plan" in manifest:
            plan = bind_verification_plan(manifest["verification_plan"], runs)
            for group in plan["groups"]:
                for item in group["items"]:
                    require(all(check["suite_id"] in suite_ids for check in item["checks"]),
                            f"Unknown suite in verification plan item: {item['id']}")
            data["verification_plan"] = plan
        write_dashboard(staging, ROOT / "web/dashboard", data)
    return data


def read_junit(path: Path, title: str | None, *, include_attachments: bool = False) -> dict:
    root = ElementTree.parse(path).getroot()
    require(root.tag in {"testsuite", "testsuites"}, "Expected a JUnit <testsuite> or <testsuites> root")
    suites, runs = [], []
    for suite in root.iter("testsuite"):
        cases = suite.findall("testcase")
        if not cases:
            continue
        suite_id = f"suite-{len(suites) + 1}"
        suites.append({"id": suite_id, "title": suite.get("name") or suite_id})
        for case in cases:
            name = string(case.get("name"), "JUnit testcase name")
            test = ".".join(filter(None, (case.get("classname"), name)))
            outcomes = [child for child in case if child.tag in JUNIT_RESULTS]
            require(len({child.tag for child in outcomes}) <= 1, f"Conflicting JUnit results for {test}")
            run = {"id": f"junit:{len(runs) + 1}", "suite_id": suite_id, "test": test,
                   "raw_status": JUNIT_RESULTS[outcomes[0].tag] if outcomes else "PASS", "report": path.name}
            excerpt = [child.get("message") or (child.text or "").strip() for child in outcomes]
            if any(excerpt):
                run["failure_excerpt"] = [message for message in excerpt if message][:3]
            if include_attachments:
                run["attachments"] = [name.replace("\\", "/") for output in case.findall("system-out")
                                      for name in JUNIT_ATTACHMENT.findall("".join(output.itertext()))]
            runs.append(run)
    require(runs, "JUnit report has no testcase records")
    return {"schema_version": 1, "project": {"title": title or path.stem}, "suites": suites, "runs": runs}


def init_demo(output: Path) -> None:
    """Write a small, explicitly synthetic sample without simulator dependencies."""
    manifest = {"schema_version": 1,
                "project": {"title": "Counter Demo", "source_note": "合成接入示例 / Synthetic example. No simulator was run."},
                "suites": [{"id": "counter", "title": "Counter checks"}],
                "runs": [{"id": "reset:7", "suite_id": "counter", "test": "reset", "seed": 7,
                          "raw_status": "PASS", "log": "reset.txt"},
                         {"id": "overflow:11", "suite_id": "counter", "test": "overflow", "seed": 11,
                          "raw_status": "FAIL", "log": "overflow.txt", "vcd": "overflow.vcd",
                          "failure_excerpt": ["10 ns: expected count=0, observed count=3"],
                          "signals": ["counter_tb.count", "counter_tb.clk"]}],
                "verification_plan": {"groups": [{"id": "counter-plan", "title": "Counter behavior", "items": [
                    {"id": "reset-plan", "title": "Reset", "summary": "Reset clears the count.",
                     "checks": [{"suite_id": "counter", "tests": ["reset"]}]},
                    {"id": "wrap-plan", "title": "Wraparound", "summary": "Overflow wraps the count to zero.",
                     "checks": [{"suite_id": "counter", "tests": ["overflow"]}]}]}]}}
    with new_directory(output) as staging:
        (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (staging / "reset.txt").write_text("Synthetic example\n0 ns: reset count matched 0\n", encoding="utf-8")
        (staging / "overflow.txt").write_text("Synthetic example\n10 ns: expected count=0, observed count=3\n", encoding="utf-8")
        (staging / "overflow.vcd").write_text(
            "$comment Synthetic example $end\n$timescale 1 ns $end\n$scope module counter_tb $end\n"
            "$var wire 2 v count [1:0] $end\n$var wire 1 c clk $end\n$upscope $end\n$enddefinitions $end\n"
            "#0\nb00 v\n0c\n#5\n1c\nb11 v\n#10\n0c\n#15\n1c\n#20\n0c\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("init", help="write a synthetic counter example and editable manifest")
    demo.add_argument("--out", type=Path, required=True, help="new input directory")
    generate = commands.add_parser("build", help="generate a self-contained site from recorded results")
    source = generate.add_mutually_exclusive_group(required=True)
    source.add_argument("manifest", type=Path, nargs="?", help="versioned JSON manifest")
    source.add_argument("--junit", type=Path, help="JUnit XML test results")
    generate.add_argument("--title", help="project title for --junit (defaults to the file stem)")
    generate.add_argument("--attachments-root", type=Path,
                          help="local directory for paths declared by JUnit testcase attachment markers")
    generate.add_argument("--out", type=Path, required=True, help="new output directory")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            init_demo(args.out)
            print(f"Demo manifest: {args.out / 'manifest.json'}")
        else:
            path = (args.junit or args.manifest).absolute()
            if args.junit:
                with TemporaryDirectory(prefix="workbench-junit-") as temporary:
                    snapshot = Path(temporary) / path.name
                    shutil.copyfile(path, snapshot)
                    manifest = read_junit(snapshot, args.title, include_attachments=args.attachments_root is not None)
                    data = build(manifest, snapshot.parent, args.out, attachments_root=args.attachments_root)
            else:
                require(args.title is None, "--title applies only to --junit")
                require(args.attachments_root is None, "--attachments-root applies only to --junit")
                manifest = json.loads(path.read_text(encoding="utf-8-sig"))
                data = build(manifest, path.parent, args.out)
            print(f"Workbench: {args.out / 'index.html'} ({len(data['runs'])} run records, "
                  f"{len(data['waveforms'])} previews, {len(data['inputs'])} evidence files)")
    except (OSError, ValueError, ElementTree.ParseError) as error:
        print(f"WORKBENCH_ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
