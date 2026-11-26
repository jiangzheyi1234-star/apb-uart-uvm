"""Validate separately executed TRACE reproductions without changing old results.

All paths in a reproduction index resolve inside its own bundle. Original
reports, transcripts and source snapshots must match the sealed evidence still
shipped beside it. Binary identities describe recorded executions; validation
does not reopen Linux executables or run simulations.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re

from run_mutation import CASES, assess_control, assess_mutation
from run_protocol_checks import assess_run
from run_regression import SIM_ERROR


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(value, dict), "Expected a reproduction evidence object")
    return value


def _sha(value) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def _digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def _inside(base: Path, relative: str) -> Path:
    _require(isinstance(relative, str) and bool(relative) and ":" not in relative and "\\" not in relative
             and not relative.startswith("/") and all(part not in ("", ".", "..") for part in relative.split("/")),
             "Reproduction evidence paths must be safe relative POSIX paths")
    path = (base / relative).resolve()
    _require(path.is_relative_to(base) and path.is_file(), "Reproduction evidence is missing or escapes its bundle")
    return path


def _checked(base: Path, relative: str, checksum: str, size: int | None = None) -> Path:
    _require(_sha(checksum), "A reproduction artifact SHA-256 is missing")
    path = _inside(base, relative)
    _require(_digest(path) == checksum and (size is None or type(size) is int and size > 0 and path.stat().st_size == size),
             "Reproduction artifact digest or size differs from its record")
    return path


def _snapshot(value: dict) -> str:
    _require(value.get("captured_before_compile") is True and bool(value.get("project_files"))
             and bool(value.get("uvm_files")), "A build-time source snapshot is required")
    stable = {key: value.get(key) for key in ("project_files", "uvm_files", "rtl_variant")}
    measured = hashlib.sha256(json.dumps(stable, sort_keys=True).encode("utf-8")).hexdigest()
    _require(value.get("snapshot_sha256") == measured, "Source snapshot stable digest is inconsistent")
    return measured


def staged_project_root(report: dict) -> str:
    """Resolve a recorded ASCII stage from its wrapper or absolute file list."""
    filelist = report.get("source_file_list")
    _require(isinstance(filelist, str) and "\\" not in filelist, "Compiler report has no POSIX source file list")
    filelist_path = PurePosixPath(filelist)
    _require(filelist_path.is_absolute() and ".." not in filelist_path.parts and filelist_path.parent.name == "sim",
             "Cannot derive compiler stage from its source file list")
    inferred = filelist_path.parent.parent.as_posix()
    stage = (report.get("source_origin") or {}).get("staged_project_root") or inferred
    _require(isinstance(stage, str) and stage == inferred, "Compiler wrapper stage differs from its file list")
    relative = filelist_path.relative_to(PurePosixPath(stage)).as_posix()
    entries = [item for item in report.get("source_manifest", {}).get("project_files", []) if item.get("path") == relative]
    _require(len(entries) == 1 and _sha(entries[0].get("sha256")) and type(entries[0].get("bytes")) is int and entries[0]["bytes"] > 0,
             "Compiler source file list is not uniquely recorded in its source snapshot")
    commands = [build.get("command", []) for build in report.get("build", []) if "--binary" in build.get("command", [])]
    _require(len(commands) == 1 and commands[0].count("-f") == 1 and commands[0].index("-f") + 1 < len(commands[0])
             and commands[0][commands[0].index("-f") + 1] == filelist,
             "Compiler -f argument differs from its captured source file list")
    return stage


def normalized_build_command(report: dict) -> list[str]:
    """Preserve semantic compiler options while normalizing locations and jobs."""
    builds = report.get("build") or []
    _require(bool(builds) and all(build.get("returncode") == 0 and build.get("timed_out") is False for build in builds),
             "Reproduction compiler did not complete normally")
    candidates = [build for build in builds if "--binary" in build.get("command", [])]
    _require(len(candidates) == 1, "One actual Verilator compiler command is required")
    build = candidates[0]
    command = build.get("command") or []
    _require(isinstance(command, list) and command and all(isinstance(arg, str) for arg in command),
             "Recorded compiler arguments are missing")
    _require(Path(command[0].replace("\\", "/")).name in ("verilator", "verilator_bin"),
             "Reproduction compiler is not Verilator")
    snapshot = report.get("source_manifest") or {}
    stage = staged_project_root(report)
    uvm = snapshot.get("uvm_source_root")
    replacements = [(value.replace("\\", "/").rstrip("/"), label)
                    for value, label in ((stage, "<STAGE>"), (uvm, "<UVM>")) if isinstance(value, str) and value]
    _require(len(replacements) == 2, "Compiler normalization requires stage and UVM roots")
    replacements.sort(key=lambda item: len(item[0]), reverse=True)
    result, index = ["<VERILATOR>"], 1
    while index < len(command):
        arg = command[index]
        if arg in ("-j", "--build-jobs"):
            _require(index + 1 < len(command) and command[index + 1].isdigit(), "Invalid compiler jobs option")
            index += 2
            continue
        if re.fullmatch(r"-j[0-9]+", arg):
            index += 1
            continue
        if arg in ("--Mdir", "-Mdir", "-o"):
            _require(index + 1 < len(command), "Compiler output option has no value")
            result.extend(["--Mdir" if arg in ("--Mdir", "-Mdir") else arg, "<OUTPUT>"])
            index += 2
            continue
        arg = arg.replace("\\", "/")
        for source, target in replacements:
            arg = re.sub(re.escape(source) + r"(?=/|$)", lambda _: target, arg)
        result.append(arg)
        index += 1
    return result


def _runtime_command(command: list) -> list:
    _require(isinstance(command, list) and command and all(isinstance(arg, str) for arg in command),
             "Recorded reproduction runtime arguments are missing")
    return ["<BINARY>"] + [arg for arg in command[1:] if arg != "+TRACE"
                           and not arg.startswith(("+VCD_FILE=", "+verilator+coverage+file+"))]


def _logged_command(text: str, expected: list) -> None:
    first = text.splitlines()[0] if text else ""
    _require(first.startswith("COMMAND "), "Reproduction transcript lacks its recorded subprocess command")
    _require(json.loads(first[len("COMMAND "):]) == expected, "Transcript command differs from its process record")


def _archive(base: Path):
    manifest = json.loads((base / "inputs.json").read_text(encoding="utf-8"))
    _require(isinstance(manifest, list), "Original evidence manifest must be a list")
    entries = {}
    for entry in manifest:
        relative = entry.get("bundled_path")
        if relative:
            _require(relative not in entries, "Duplicate original evidence path")
            entries[relative] = entry

    def artifact(relative: str) -> Path:
        _require(relative in entries, "Original evidence path is absent from its sealed manifest")
        entry = entries[relative]
        return _checked(base, relative, entry.get("sha256"), entry.get("bytes"))

    return artifact


def _original_records(root: Path) -> dict[str, dict]:
    result = {}
    features = root / "features"
    artifact = _archive(features)
    summary = _read(features / "summary.json")["checker_sensitivity"]
    original_report_path = artifact(summary["raw_report"])
    original_report = _read(original_report_path)
    baseline_path = artifact(summary["baseline_raw_report"])
    baseline = _read(baseline_path)
    source_path = artifact(summary["baseline_provenance"]["snapshot_input"])
    source = _read(source_path)
    source_sha = _snapshot(source)
    _require(source == baseline.get("source_manifest")
             and source_sha == original_report.get("baseline", {}).get("source_snapshot_sha256"),
             "Original fault controls do not share their baseline source identity")
    binary = baseline.get("compiled_binary") or {}
    _require(_sha(binary.get("sha256")) and binary["sha256"] == original_report.get("baseline", {}).get("binary_sha256"),
             "Original fault-control binary identity is inconsistent")
    for case in CASES:
        matches = [run for run in original_report["runs"] if run.get("phase") == "mutation"
                   and run.get("test") == case["test"] and run.get("mutation") == case["mutation"] and run.get("seed") == 1]
        saved = [run for run in summary["runs"] if run.get("phase") == "mutation"
                 and run.get("test") == case["test"] and run.get("mutation") == case["mutation"] and run.get("seed") == 1]
        _require(len(matches) == len(saved) == 1, "Original mutation identity is ambiguous")
        actual, row = matches[0], saved[0]
        log = artifact(row["transcript"])
        text = log.read_text(encoding="utf-8")
        _logged_command(text, actual["command"])
        assessment = assess_mutation(text, actual.get("returncode"), actual.get("timed_out"), case)
        _require(actual.get("raw_simulation_status") == row.get("raw_simulation_status") == assessment["raw_simulation_status"] == "FAIL"
                 and actual.get("status") == row.get("classification") == assessment["status"] == "DETECTED"
                 and _digest(log) == actual.get("log_sha256") == row.get("transcript_sha256"),
                 "Original mutation failure is not backed by its recorded transcript")
        run_id = f"fault_control:mutation:{case['test']}:{case['mutation']}:1"
        result[run_id] = {"suite_id": "fault_control", "test": case["test"], "seed": 1, "phase": "mutation",
                          "mutation": case["mutation"], "variant": "fixed", "expected_error_id": case["expected_id"],
                          "report": original_report_path, "log": log, "snapshot": source_path, "snapshot_data": source,
                          "source_snapshot_sha256": source_sha, "binary_sha256": binary["sha256"],
                          "build_report": baseline, "build_report_path": baseline_path, "command": actual["command"]}
    protocol = root / "protocol"
    artifact = _archive(protocol)
    summary = _read(protocol / "summary.json")
    provenance = [record for record in summary["provenance"] if record.get("phase") == "negative"]
    _require(len(provenance) == 1, "Original protocol negative profile is ambiguous")
    provenance = provenance[0]
    original_report_path = artifact(provenance["raw_report"])
    original_report = _read(original_report_path)
    source_path = artifact(provenance["snapshot_input"])
    source = _read(source_path)
    source_sha = _snapshot(source)
    binary = original_report.get("compiled_binary") or {}
    _require(source == original_report.get("source_manifest") and source_sha == summary.get("identity", {}).get("source_snapshot_sha256")
             and _sha(binary.get("sha256")) and binary["sha256"] == summary.get("identity", {}).get("binary_sha256"),
             "Original protocol source or binary identity is inconsistent")
    for seed in (2, 3):
        test = "apb_timeout_requirement_test"
        matches = [run for run in original_report["runs"] if run.get("test") == test and run.get("seed") == seed]
        saved = [run for run in summary["runs"] if run.get("phase") == "negative" and run.get("test") == test and run.get("seed") == seed]
        _require(len(matches) == len(saved) == 1, "Original protocol timeout identity is ambiguous")
        actual, row = matches[0], saved[0]
        log = artifact(row["log"])
        text = log.read_text(encoding="utf-8")
        _logged_command(text, actual["command"])
        assessment = assess_run(text, actual.get("returncode"), actual.get("timed_out"), test, True)
        _require(actual.get("status") == row.get("raw_status") == assessment["raw_status"] == "FAIL"
                 and row.get("classification") == assessment["classification"] == "DETECTED"
                 and _digest(log) == row.get("log_sha256"), "Original APB timeout failure is not backed by its transcript")
        run_id = f"apb_protocol:negative:{test}:{seed}"
        result[run_id] = {"suite_id": "apb_protocol", "test": test, "seed": seed, "phase": "negative", "mutation": None,
                          "variant": "agent", "expected_error_id": "APB_TIMEOUT", "report": original_report_path,
                          "log": log, "snapshot": source_path, "snapshot_data": source, "source_snapshot_sha256": source_sha,
                          "binary_sha256": binary["sha256"], "build_report": original_report, "command": actual["command"]}
        result[run_id]["build_report_path"] = original_report_path
    return result


def reproduction_evidence(base: Path, root: Path) -> tuple[list[dict], list[dict]]:
    """Return separate reproduction metadata and hash-checked dashboard inputs.

    ``base`` is normally ``docs/reproductions`` and ``root`` is ``docs``. An
    absent index is an older bundle and returns empty lists. A present index
    must audit exactly the four selected mutations and protocol seeds 2/3.
    Metadata never adds or reclassifies an original run.
    """
    base, root = base.resolve(), root.resolve()
    _require(base.is_relative_to(root), "Reproduction bundle must be inside the dashboard URL root")
    index_path = base / "index.json"
    if not index_path.exists():
        return [], []
    index_path = _inside(base, "index.json")
    index = _read(index_path)
    _require(index.get("schema_version") == 1 and index.get("status") == "PASS"
             and isinstance(index.get("started_utc"), str) and bool(index["started_utc"])
             and isinstance(index.get("entries"), list) and len(index["entries"]) == 6,
             "Only a completed six-run reproduction audit can be displayed")
    originals = _original_records(root)
    records, inputs, seen_originals, seen_ids = [], {}, set(), set()

    def remember(path: Path):
        relative = path.relative_to(root).as_posix()
        measured = {"path": relative, "sha256": _digest(path), "bytes": path.stat().st_size}
        _require(relative not in inputs or inputs[relative] == measured, "Conflicting reproduction input identity")
        inputs[relative] = measured
        return relative

    remember(index_path)
    for entry in index["entries"]:
        _require(isinstance(entry, dict), "Malformed reproduction entry")
        original_id, reproduction_id = entry.get("original_run_id"), entry.get("reproduction_id")
        _require(isinstance(original_id, str) and original_id in originals and original_id not in seen_originals,
                 "Reproduction targets an unsupported or duplicate original run")
        _require(isinstance(reproduction_id, str) and reproduction_id.startswith("reproduction:")
                 and reproduction_id.endswith(":" + original_id) and reproduction_id not in seen_ids,
                 "Reproduction requires its own unique session-qualified identity")
        seen_originals.add(original_id)
        seen_ids.add(reproduction_id)
        original = originals[original_id]
        for key in ("suite_id", "test", "seed", "variant", "phase", "mutation", "expected_error_id"):
            _require(entry.get(key) == original[key], "Reproduction differs from its exact original target: " + key)
        _require(type(entry.get("seed")) is int, "Reproduction seed must be an integer")
        artifacts = {}
        for key, checksum_key in (("original_report_path", "original_report_sha256"), ("original_log_path", "original_log_sha256"),
                                  ("original_source_snapshot_path", "original_source_snapshot_file_sha256"),
                                  ("source_snapshot_path", "source_snapshot_file_sha256"), ("build_report_path", "build_report_sha256"),
                                  ("raw_report_path", "raw_report_sha256"), ("raw_log_path", "raw_log_sha256"),
                                  ("waveform_path", "waveform_sha256")):
            artifacts[key] = _checked(base, entry.get(key), entry.get(checksum_key), entry.get("waveform_bytes") if key == "waveform_path" else None)
            remember(artifacts[key])
        for kind, path_key in (("report", "original_report_path"), ("log", "original_log_path"), ("snapshot", "original_source_snapshot_path")):
            _require(artifacts[path_key].read_bytes() == original[kind].read_bytes(), "Copied original evidence differs from the current sealed " + kind)
        if "original_build_report_path" in entry:
            copied_build = _checked(base, entry["original_build_report_path"], entry.get("original_build_report_sha256"))
            _require(copied_build.read_bytes() == original["build_report_path"].read_bytes(), "Copied original compiler report differs from its sealed record")
            remember(copied_build)
        _require(entry.get("original_command") == original["command"]
                 and entry.get("original_source_snapshot_sha256") == original["source_snapshot_sha256"]
                 and entry.get("original_binary_sha256") == original["binary_sha256"], "Original execution identity was changed")
        build = _read(artifacts["build_report_path"])
        snapshot = _read(artifacts["source_snapshot_path"])
        snapshot_sha = _snapshot(snapshot)
        _require(build.get("simulator") == "verilator" and build.get("suite") == original["build_report"].get("suite")
                 and build.get("rtl_variant") == original["build_report"].get("rtl_variant"),
                 "Reproduction build targets a different execution suite or RTL variant")
        _require(snapshot == build.get("source_manifest") and snapshot_sha == original["source_snapshot_sha256"] == entry.get("source_snapshot_sha256"),
                 "Reproduction does not use the original compiled source snapshot")
        _require(normalized_build_command(build) == normalized_build_command(original["build_report"]),
                 "Reproduction compilation options differ from the original build")
        _require(isinstance(build.get("tool_version"), str) and bool(build["tool_version"])
                 and build["tool_version"] == original["build_report"].get("tool_version"),
                 "Reproduction simulator version differs from its original build")
        binary = build.get("compiled_binary") or {}
        _require(_sha(entry.get("binary_sha256")) and type(entry.get("binary_bytes")) is int and entry["binary_bytes"] > 0
                 and binary.get("sha256") == entry["binary_sha256"] and binary.get("bytes") == entry["binary_bytes"],
                 "Reproduction binary execution identity is inconsistent")
        compile_command = next(process["command"] for process in build["build"] if "--binary" in process["command"])
        _require(compile_command.count("-o") == 1 and compile_command.index("-o") + 1 < len(compile_command)
                 and compile_command[compile_command.index("-o") + 1] == binary.get("path"),
                 "Recorded reproduction executable is not the compiler output")
        same_binary = entry["binary_sha256"] == original["binary_sha256"]
        _require(type(entry.get("binary_matches_original")) is bool and entry["binary_matches_original"] == same_binary,
                 "Reproduction misstates whether its binary matches the original")
        sidecars = entry.get("build_evidence", [])
        _require(isinstance(sidecars, list) and (same_binary or bool(sidecars)),
                 "A different reproduction executable requires its actual compiler and preflight evidence")
        sidecar_texts = []
        for sidecar in sidecars:
            path = _checked(base, sidecar.get("path"), sidecar.get("sha256"), sidecar.get("bytes"))
            remember(path)
            sidecar_texts.append(path.read_text(encoding="utf-8"))
        if sidecar_texts:
            def process_text(command):
                matches = []
                for candidate in sidecar_texts:
                    first = candidate.splitlines()[0] if candidate else ""
                    if first.startswith("COMMAND ") and json.loads(first[len("COMMAND "):]) == command:
                        matches.append(candidate)
                _require(len(matches) == 1, "Build or preflight process is not uniquely backed by its own transcript")
                return matches[0]

            for process in build["build"]:
                _require(not SIM_ERROR.search(process_text(process["command"])), "Reproduction compiler transcript contains an error")
            _require(build.get("status") == "PASS" and bool(build.get("runs")), "A rebuilt executable needs completed positive preflight controls")
            for run in build["runs"]:
                preflight_command = run.get("command") or []
                _require(run.get("status") == "PASS" and preflight_command and preflight_command[0] == binary["path"],
                         "Reproduction preflight run differs from the recorded executable")
                preflight_text = process_text(preflight_command)
                checked = (assess_control(preflight_text, run.get("returncode"), run.get("timed_out"))
                           if original["suite_id"] == "fault_control" else
                           assess_run(preflight_text, run.get("returncode"), run.get("timed_out"), run.get("test"), False))
                _require(checked.get("status", checked.get("classification")) == "PASS", "Reproduction preflight control is not a clean PASS")
            version_process = build.get("tool_version_process") or {}
            _require(version_process.get("returncode") == 0 and version_process.get("timed_out") is False
                     and build["tool_version"] in process_text(version_process.get("command")),
                     "Reproduction simulator version lacks its actual subprocess transcript")
        command = entry.get("command")
        _require(_runtime_command(command) == _runtime_command(original["command"])
                 and command[0] == binary.get("path") and command.count("+TRACE") == 1
                 and len([arg for arg in command if arg.startswith("+VCD_FILE=") and len(arg) > len("+VCD_FILE=")]) == 1,
                 "Reproduction runtime command differs from its selected test, seed or mutation")
        raw = _read(artifacts["raw_report_path"])
        for key in ("original_run_id", "reproduction_id", "test", "seed", "phase", "mutation", "command", "raw_status", "classification"):
            _require(raw.get(key) == entry.get(key), "Reproduction raw process record disagrees with its index: " + key)
        _require(raw.get("log") == entry["raw_log_path"] and raw.get("returncode") == 0 and raw.get("timed_out") is False,
                 "Reproduction raw process did not complete normally with its own log")
        for key in ("waveform_path", "waveform_sha256", "waveform_bytes", "binary_sha256", "source_snapshot_sha256"):
            _require(raw.get(key) == entry[key], "Reproduction raw process provenance differs from its index: " + key)
        text = artifacts["raw_log_path"].read_text(encoding="utf-8")
        _logged_command(text, command)
        if original["suite_id"] == "fault_control":
            case = next(case for case in CASES if case["mutation"] == original["mutation"])
            assessment = assess_mutation(text, raw["returncode"], raw["timed_out"], case)
            raw_status, classification = assessment["raw_simulation_status"], assessment["status"]
            error_ids = assessment.get("observed_error_ids")
            stats = None
        else:
            assessment = assess_run(text, raw["returncode"], raw["timed_out"], original["test"], True)
            raw_status, classification = assessment["raw_status"], assessment["classification"]
            error_ids, stats = assessment.get("error_ids"), assessment.get("stats")
        _require(raw_status == entry.get("raw_status") == "FAIL" and classification == entry.get("classification") == "DETECTED"
                 and raw.get("uvm_errors") == entry.get("uvm_errors") == assessment.get("uvm_errors")
                 and raw.get("uvm_fatals") == entry.get("uvm_fatals") == assessment.get("uvm_fatals"),
                 "Reproduction log does not independently demonstrate its intended checker")
        record = {"id": reproduction_id, "reproduction_id": reproduction_id, "waveform_id": reproduction_id,
                  "kind": "new_execution", "original_run_id": original_id, "original_raw_status": "FAIL",
                  **{key: original[key] for key in ("suite_id", "test", "seed", "variant", "phase", "mutation", "expected_error_id")},
                  "raw_status": raw_status, "classification": classification, "uvm_errors": assessment["uvm_errors"],
                  "uvm_fatals": assessment["uvm_fatals"], "error_ids": error_ids, "stats": stats,
                  "log_url": remember(artifacts["raw_log_path"]), "report_url": remember(artifacts["raw_report_path"]),
                  "waveform_url": remember(artifacts["waveform_path"]), "waveform_sha256": entry["waveform_sha256"],
                  "waveform_bytes": entry["waveform_bytes"], "original_log_url": original["log"].relative_to(root).as_posix(),
                  "original_report_url": original["report"].relative_to(root).as_posix(),
                  "source_snapshot_url": remember(artifacts["source_snapshot_path"]), "source_snapshot_sha256": snapshot_sha,
                  "original_source_snapshot_sha256": original["source_snapshot_sha256"],
                  "binary_sha256": entry["binary_sha256"], "binary_bytes": entry["binary_bytes"],
                  "original_binary_sha256": original["binary_sha256"], "binary_matches_original": same_binary,
                  "tool_version": build["tool_version"],
                  "started_utc": index["started_utc"], "index_url": index_path.relative_to(root).as_posix()}
        records.append(record)
    _require(seen_originals == set(originals), "The reproduction audit omits an original failure target")
    return records, list(inputs.values())
