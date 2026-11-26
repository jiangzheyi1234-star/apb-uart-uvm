#!/usr/bin/env python3
"""Archive completed subsystem runs with explicit private-path normalization.

No simulator or compiler is invoked. The directory is reproducible from the
selected raw report and unchanged sources; an existing nonempty output is never
overwritten. VCD bytes are preserved exactly. Logs and recorded JSON may replace
private project-root prefixes with /project; each transformation records both
the original and distributed SHA-256 in provenance.json.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys

from build_evidence import reference
from run_regression import classify_log, SIM_ERROR, SUITE_PASS_MARKERS
from waveform_data import waveform


ROOT = Path(__file__).resolve().parents[1]
TESTS = ("subsystem_apb_test", "subsystem_mbist_test", "subsystem_mbist_fault_test", "subsystem_mbist_reset_test")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), "Expected a JSON evidence object")
    return value


def encoded(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def source_file(root: Path, relative: str) -> Path:
    require(isinstance(relative, str) and bool(relative) and "\\" not in relative and ":" not in relative
            and not relative.startswith("/") and all(part not in ("", ".", "..") for part in relative.split("/")),
            "Source snapshot contains an unsafe relative path")
    result = (root / relative).resolve()
    require(result.is_relative_to(root) and result.is_file(), "Captured source is missing or escapes its root")
    return result


def verify_sources(snapshot: dict, project: Path) -> None:
    require(snapshot.get("suite") == "subsystem" and snapshot.get("rtl_variant") == "fixed"
            and snapshot.get("captured_before_compile") is True, "Expected a pre-build subsystem source snapshot")
    stable = {key: snapshot.get(key) for key in ("project_files", "uvm_files", "rtl_variant")}
    require(sha(json.dumps(stable, sort_keys=True).encode("utf-8")) == snapshot.get("snapshot_sha256"), "Source snapshot digest is invalid")
    roots = [(project, snapshot.get("project_files"))]
    uvm = snapshot.get("uvm_source_root", "").replace("\\", "/")
    require("/.tools/" in uvm, "Cannot locate the captured UVM source under the project tool cache")
    roots.append(((project / ".tools" / uvm.split("/.tools/", 1)[1]).resolve(), snapshot.get("uvm_files")))
    for root, records in roots:
        require(isinstance(records, list) and bool(records), "Captured source set is empty")
        seen = set()
        for item in records:
            require(item["path"] not in seen, "Duplicate captured source")
            seen.add(item["path"])
            path = source_file(root, item["path"])
            require(path.stat().st_size == item["bytes"] and sha(path.read_bytes()) == item["sha256"],
                    "Working source differs from the actual compiled snapshot: " + item["path"])


def recorded_command(text: str, command: list) -> None:
    first = text.splitlines()[0] if text else ""
    require(first.startswith("COMMAND ") and json.loads(first[len("COMMAND "):]) == command,
            "Transcript command differs from its recorded process")


def normalization(project: Path, report: dict, origin: dict):
    # Do not publish the prefixes themselves. Handle JSON-escaped COMMAND lines
    # as well as ordinary UTF-8 text and recorded Windows/WSL spellings.
    prefixes = {str(project), project.as_posix(), report.get("source_origin", {}).get("original_project_root"),
                origin.get("original_project_root")}
    drive = re.match(r"^([A-Za-z]):/(.*)$", project.as_posix())
    if drive:
        prefixes.add("/mnt/" + drive[1].lower() + "/" + drive[2])
    replacements = set()
    for prefix in prefixes - {None, ""}:
        for spelling in (prefix, prefix.replace("\\", "/"), prefix.replace("/", "\\")):
            replacements.add(spelling)
            replacements.add(json.dumps(spelling, ensure_ascii=True)[1:-1])
            replacements.add(json.dumps(spelling, ensure_ascii=False)[1:-1])
    ordered = sorted(replacements, key=len, reverse=True)

    def text(value: str) -> str:
        for prefix in ordered:
            value = value.replace(prefix, "/project")
        return value

    def tree(value):
        if isinstance(value, str):
            return text(value)
        if isinstance(value, list):
            return [tree(item) for item in value]
        if isinstance(value, dict):
            return {key: tree(item) for key, item in value.items()}
        return value

    return text, tree, ordered


def archive(report_path: Path, output: Path, project: Path = ROOT) -> dict:
    report_path, output, project = report_path.resolve(), output.resolve(), project.resolve()
    require(not output.exists() or output.is_dir() and not any(output.iterdir()), "Output must be a fresh or empty directory")
    require(not report_path.is_relative_to(output), "Output cannot contain the original execution record")
    raw_report = report_path.read_bytes()
    report = read(report_path)
    require(report.get("status") == "PASS" and report.get("simulator") == "verilator"
            and report.get("suite") == "subsystem" and report.get("rtl_variant") == "fixed"
            and report.get("completion_marker") == SUITE_PASS_MARKERS["subsystem"], "Expected a completed real subsystem PASS report")
    expected = {(test, seed) for test in TESTS for seed in (1, 2, 3)}
    runs = report.get("runs", [])
    require(len(runs) == 12 and {(run.get("test"), run.get("seed")) for run in runs} == expected,
            "Expected exactly four subsystem tests at seeds 1, 2 and 3")
    snapshot_path = reference(report["source_manifest_file"], report_path, project)
    snapshot = read(snapshot_path)
    require(snapshot == report.get("source_manifest"), "Standalone source snapshot differs from its runner record")
    verify_sources(snapshot, project)
    origin_path = reference(report["source_origin_map"], report_path, project)
    origin = read(origin_path)
    require(sha(origin_path.read_bytes()) == report.get("source_origin", {}).get("origin_map_sha256")
            and origin.get("all_staged_files_byte_equal") is True
            and origin.get("verified_files") == len(origin.get("files", [])), "Stage-origin evidence is incomplete or has changed")
    stage_files = {item["path"]: item for item in origin["files"]}
    require(len(stage_files) == len(origin["files"])
            and all(item.get("source_sha256") == item.get("staged_sha256") for item in stage_files.values()), "Stage contains unequal or duplicate files")
    for item in snapshot["project_files"]:
        require(stage_files.get(item["path"], {}).get("staged_sha256") == item["sha256"], "Snapshot source differs from the verified stage")
    require(not any(any(term in path.lower() for term in (".private/", ".resume_work/", "career/", "credentials", "身份证", "简历"))
                    for path in stage_files), "Stage-origin record includes private material")
    clean_text, clean_tree, private_prefixes = normalization(project, report, origin)
    payloads, provenance = {}, []

    def add(relative: str, data: bytes, role: str, raw: bytes | None = None, raw_reference: str | None = None,
            transformation: str = "byte-identical") -> None:
        require(relative not in payloads, "Duplicate public artifact path")
        payloads[relative] = data
        entry = {"bundled_path": relative, "role": role, "sha256": sha(data), "bytes": len(data), "transformation": transformation}
        if raw is not None:
            entry.update(raw_sha256=sha(raw), raw_bytes=len(raw), raw_reference=raw_reference or relative)
        provenance.append(entry)

    def normalized_file(path: Path, relative: str, role: str) -> None:
        raw = path.read_bytes()
        public = clean_text(raw.decode("utf-8")).encode("utf-8")
        add(relative, public, role, raw, relative,
            "private project-root prefixes replaced with /project" if public != raw else "byte-identical")

    normalized_file(snapshot_path, "source_snapshot.json", "build_time_source_snapshot")
    normalized_file(origin_path, "stage_origin.json", "recorded_stage_origin")
    public_report = clean_tree(copy.deepcopy(report))
    public_report["source_manifest_file"] = "source_snapshot.json"
    public_report["source_origin_map"] = "stage_origin.json"
    binary = report.get("compiled_binary") or {}
    require(isinstance(binary.get("sha256"), str) and re.fullmatch(r"[a-f0-9]{64}", binary["sha256"])
            and type(binary.get("bytes")) is int and binary["bytes"] > 0, "Compiled binary execution identity is missing")
    builds = report.get("build") or []
    require(bool(builds), "Actual compiler process is missing")
    for index, process in enumerate(builds):
        require(process.get("returncode") == 0 and process.get("timed_out") is False, "Compiler did not complete successfully")
        path = reference(process["log"], report_path, project)
        text = path.read_text(encoding="utf-8")
        recorded_command(text, process["command"])
        require(not SIM_ERROR.search(text), "Compiler transcript contains simulator errors")
        relative = f"compiler/build_{index}.log"
        normalized_file(path, relative, "compiler_transcript")
        public_report["build"][index]["log"] = relative
    version = report.get("tool_version_process") or {}
    version_path = reference(report["tool_version_log"], report_path, project)
    recorded_command(version_path.read_text(encoding="utf-8"), version.get("command"))
    require(version.get("returncode") == 0 and version.get("timed_out") is False
            and report["tool_version"] in version_path.read_text(encoding="utf-8"), "Simulator version is not backed by its transcript")
    normalized_file(version_path, "compiler/version.log", "simulator_version_transcript")
    public_report["tool_version_log"] = "compiler/version.log"
    public_report["tool_version_process"]["log"] = "compiler/version.log"
    metrics = {key: 0 for key in ("runs", "apb_completed", "ram_reads", "expected_slverr", "mbist_starts", "mbist_passes", "mbist_faults", "reset_aborts")}
    for index, run in enumerate(runs):
        test, seed = run["test"], run["seed"]
        directory = f"{test}_seed_{seed}"
        log = reference(run["log"], report_path, project)
        vcd = reference(run["waveform_file"], report_path, project)
        require(log == (report_path.parent / directory / "simulation.log").resolve()
                and vcd == (report_path.parent / directory / "waves.vcd").resolve(), "Log or VCD belongs to a different run")
        command = run.get("command") or []
        require(command and command[0] == binary.get("path") and command.count(f"+UVM_TESTNAME={test}") == 1
                and command.count(f"+verilator+seed+{seed}") == 1 and command.count("+TRACE") == 1
                and command.count("+VCD_FILE=" + run["waveform_file"]) == 1, "Runtime command does not bind the selected test, seed and VCD")
        text = log.read_text(encoding="utf-8")
        recorded_command(text, command)
        outcome = classify_log(text, run.get("returncode"), run.get("timed_out"), SUITE_PASS_MARKERS["subsystem"])
        require(run.get("status") == outcome.status == "PASS" and run.get("returncode") == 0
                and run.get("timed_out") is False and outcome.uvm_errors == outcome.uvm_fatals == 0,
                "Run is not a clean, normally completed subsystem PASS")
        markers = re.findall(r"(?m)^\s*(?:#\s*)?UVM_INFO\b[^\r\n]*\[SUBSYSTEM_UVM_TEST_PASS\]\s+(\w+)\b", text)
        require(markers == [test], "Exact test completion marker is missing or duplicated")
        summaries = re.findall(r"(?m)^\s*(?:#\s*)?UVM_INFO\b[^\r\n]*\[SUBSYSTEM_STATS\] ([^\r\n]+)", text)
        require(len(summaries) == 1, "Independent monitor statistics are missing or duplicated")
        stats = dict(re.findall(r"\b([a-z]\w*)=(\w+)", summaries[0]))
        require(stats.get("test") == test, "Monitor statistics refer to a different test")
        decoded = waveform(vcd, id=f"subsystem:{test}:{seed}", title=test, run_id=f"subsystem:{test}:{seed}",
                           url=f"{directory}/waves.vcd", uart_registers=False, subsystem=True)
        completed = [event for event in decoded["apb_events"] if event["status"] in ("OK", "SLVERR")]
        require(len(completed) == int(stats["apb_completed"])
                and sum(event["wait_cycles"] == 1 for event in completed) == int(stats["wait1"])
                and sum(event["status"] == "SLVERR" for event in completed) == int(stats["errors"]), "APB VCD does not match the independent monitor")
        march = decoded["mbist_runs"]
        require(len(march) == int(stats["mbist_starts"]) and all(event["march_sequence_matches"] for event in march), "Native RAM sequence does not match March C-minus")
        for status, key in (("PASS", "mbist_passes"), ("FAIL", "mbist_faults"), ("RESET_ABORT", "reset_aborts")):
            require(sum(event["status"] == status for event in march) == int(stats[key]), "MBIST terminal state differs between VCD and monitor")
        normalized_file(log, directory + "/simulation.log", "same_run_transcript")
        raw_vcd = vcd.read_bytes()
        add(directory + "/waves.vcd", raw_vcd, "same_run_vcd", raw_vcd)
        public_run = public_report["runs"][index]
        public_run["log"] = directory + "/simulation.log"
        public_run["waveform_file"] = directory + "/waves.vcd"
        public_run["log_sha256"] = sha(payloads[public_run["log"]])
        public_run["waveform_sha256"] = sha(raw_vcd)
        metrics["runs"] += 1
        for key in ("apb_completed", "ram_reads", "mbist_starts", "mbist_passes", "mbist_faults", "reset_aborts"):
            metrics[key] += int(stats[key])
        metrics["expected_slverr"] += int(stats["errors"])
    coverage_path = report_path.parent / "coverage" / "coverage_summary.json"
    if coverage_path.is_file():
        normalized_file(coverage_path, "coverage/coverage_summary.json", "recorded_coverage_summary")
    public_report["public_evidence"] = {
        "scope": "Completed 12-run subsystem execution; no simulation or compilation performed during archival",
        "provenance": "provenance.json", "inputs": "inputs.json", "raw_report_sha256": sha(raw_report),
        "private_path_normalization": "Private project-root prefixes replaced with /project; download references relocated within this bundle",
        "raw_checksum_scope": "Existing execution-record checksums, including origin_map_sha256, refer to raw records; distributed hashes are in inputs.json and provenance.json",
        "omitted_artifacts": ["executable and tool directories", "per-run and merged native coverage databases", "full LCOV export"],
        "coverage_summary": "coverage/coverage_summary.json" if coverage_path.is_file() else None,
        "metrics": metrics,
    }
    add("report.json", encoded(public_report), "path_normalized_runner_report", raw_report, "report.json",
        "private project-root prefixes normalized and local artifact references relocated; runner outcomes preserved")
    provenance_data = {
        "schema_version": 1, "status": "PASS", "execution_started_utc": report["started_utc"],
        "scope": public_report["public_evidence"]["scope"], "source_snapshot_sha256": snapshot["snapshot_sha256"],
        "working_project_sources_verified": len(snapshot["project_files"]), "working_uvm_sources_verified": len(snapshot["uvm_files"]),
        "compiled_binary": clean_tree(binary), "metrics": metrics, "artifacts": sorted(provenance, key=lambda item: item["bundled_path"]),
    }
    payloads["provenance.json"] = encoded(provenance_data)
    payloads["README.md"] = (
        "# Audited RAM / MBIST UVM evidence\n\n"
        "This bundle contains twelve completed Verilator/UVM subsystem runs: four tests at seeds 1/2/3. "
        "No simulator or compiler was run to create the archive. Each run has its own transcript and byte-identical VCD.\n\n"
        "[Runner report](report.json), [input hashes](inputs.json), and [normalization provenance](provenance.json) "
        "preserve the measured scope and distinguish raw from distributed SHA-256 values. Private local project-root "
        "prefixes in logs/JSON are replaced by `/project`; packaged log/VCD references are relative. "
        "Execution-record checksums such as `origin_map_sha256` still identify the raw, unnormalized records; "
        "use `inputs.json` for the public files. VCDs have not been normalized.\n\n"
        "The four tests cover APB/RAM access, clean March C-minus, selected read-bit fault diagnosis and recovery, "
        "and reset interruption. A fault-test UVM PASS means the expected MBIST failure and recovery were checked. "
        "It does not mean the injected memory passed self-test or that all memory fault classes were covered.\n\n"
        "The build-time source snapshot was checked against the working project and pinned UVM sources before archival. "
        "Executable and tool directories, native coverage databases and the full LCOV export are omitted. "
        "The coverage summary is a recorded summary; the omitted databases are not downloadable links.\n\n"
        "Rebuild this directory into a fresh output with `python py/archive_subsystem_evidence.py "
        "--report results/subsystem_acceptance/report.json --out <fresh-directory>`. "
        "The original local execution and identical captured sources must be available.\n"
    ).encode("utf-8")
    # Defense in depth: no drive/home/mounted-user paths may leak through an
    # alternate JSON spelling. Generic /var/tmp execution/tool references remain.
    for relative, data in payloads.items():
        text = data.decode("utf-8")
        require(not any(prefix in text for prefix in private_prefixes), "A private project prefix remains in public evidence")
        require(not re.search(r"(?i)(?<![a-z0-9])(?:[a-z]:[\\/]|/mnt/[a-z]/|/users/)", text),
                "A local user path remains in public evidence: " + relative)
    payloads["inputs.json"] = encoded([{"bundled_path": relative, "sha256": sha(data), "bytes": len(data)}
                                        for relative, data in sorted(payloads.items())])
    # Validate everything before writing. Stable input order and execution time
    # metadata make a repeat archive byte-for-byte reproducible from this report.
    output.mkdir(parents=True, exist_ok=True)
    for relative, data in sorted(payloads.items()):
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    return {"status": "PASS", "runs": 12, "logs": 12, "waveforms": 12, "files": len(payloads),
            "metrics": metrics, "source_snapshot_sha256": snapshot["snapshot_sha256"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    try:
        result = archive(args.report, args.out, args.project_root)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print("SUBSYSTEM_ARCHIVE_ERROR: " + str(error), file=sys.stderr)
        return 1
    print("SUBSYSTEM_ARCHIVED: " + json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
