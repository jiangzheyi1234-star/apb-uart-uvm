"""Offline protocol packaging and tamper tests; generated fixtures are not RTL evidence."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("protocol_evidence", ROOT / "py" / "build_protocol_evidence.py")
evidence = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = evidence
SPEC.loader.exec_module(evidence)
from test_protocol_report import transcript


class ProtocolEvidenceTests(unittest.TestCase):
    def fixture(self, root):
        project = root / "project"
        session = project / "results" / "protocol_fixture"
        session.mkdir(parents=True)
        stage = "/var/tmp/offline-apb-protocol-stage"
        binary = "/var/tmp/offline-apb-protocol-build/Vtb_top"
        source_entries = []
        for name, data in (("sim/files_protocol.f", b"tb/protocol.sv\n"), ("tb/protocol.sv", b"module tb_top; endmodule\n")):
            path = project / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(data)
            source_entries.append({"path": name, "sha256": evidence.digest(path), "bytes": len(data)})
        uvm_data = b"// Official dependency identity fixture, not a UVM library\n"
        uvm_entry = {"path": "uvm_pkg.sv", "sha256": evidence.hashlib.sha256(uvm_data).hexdigest(), "bytes": len(uvm_data)}
        snapshot = {"suite": "apb_protocol", "rtl_variant": None, "captured_before_compile": True,
                    "project_files": source_entries, "uvm_files": [uvm_entry], "uvm_version": "unit-test fixture",
                    "uvm_source_root": stage + "/.tools/uvm-core-2020.3.1/src"}
        stable = {key: snapshot[key] for key in ("project_files", "uvm_files", "rtl_variant")}
        snapshot["snapshot_sha256"] = evidence.hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()
        # Deliberately absent Linux paths must resolve through results/ on either OS.
        def recorded(path):
            return "/mnt/z/archived-project/" + path.relative_to(project).as_posix()
        common = {"binary": binary, "binary_sha256": "a" * 64, "binary_bytes": 12345,
                  "source_snapshot_sha256": snapshot["snapshot_sha256"],
                  "current_project_sources_match": True, "current_uvm_sources_match": True}
        audit = {"status": "PASS", "suite": "apb_protocol", "rtl_variant": None, "seeds": [1, 2, 3],
                 "metrics": dict(evidence.METRICS), "raw_reports": [], "runs": [],
                 "identity": {**common, "binary_unchanged_after_controls": True,
                              "same_binary_all_profiles": True, "same_source_snapshot_all_profiles": True}}
        profiles = {}
        for phase, tests in (("positive", evidence.POSITIVE_TESTS), ("negative", (evidence.NEGATIVE_TEST,)), ("recovery", (evidence.POSITIVE_TESTS[0],))):
            directory = session / phase
            directory.mkdir()
            sidecar = directory / "source_snapshot.json"
            sidecar.write_text(json.dumps(snapshot), encoding="utf-8")
            origin_path = directory / "stage_origin.json"
            entries = [{"path": entry["path"], "bytes": entry["bytes"], "source_sha256": entry["sha256"], "staged_sha256": entry["sha256"]} for entry in source_entries]
            entries.append({"path": ".tools/uvm-core-2020.3.1/src/uvm_pkg.sv", "bytes": uvm_entry["bytes"],
                            "source_sha256": uvm_entry["sha256"], "staged_sha256": uvm_entry["sha256"]})
            origin = {"all_staged_files_byte_equal": True, "verified_files": len(entries), "files": entries,
                      "original_project_root": "/mnt/z/archived-project", "staged_project_root": stage,
                      "runner_command": ["python3", stage + "/py/run_regression.py", "--suite", "apb_protocol"]}
            origin_path.write_text(json.dumps(origin), encoding="utf-8")
            build_log, version_log = directory / "build.log", directory / "version.log"
            build_log.write_text("Compiler fixture; not an actual RTL build\n", encoding="utf-8")
            version_log.write_text("COMMAND [fixture-verilator, --version]\nVersion fixture\n", encoding="utf-8")
            build = {"returncode": 0, "timed_out": False, "log": recorded(build_log),
                     "command": ["fixture-verilator", "--binary", "--top-module", "tb_top", "-f", stage + "/sim/files_protocol.f"]}
            report = {"status": "FAIL" if phase == "negative" else "PASS", "suite": "apb_protocol", "rtl_variant": None,
                      "simulator": "verilator", "completion_marker": "APB_AGENT_TEST_PASS", "build": [build],
                      "compiled_binary": {"path": binary, "sha256": common["binary_sha256"], "bytes": common["binary_bytes"]},
                      "source_manifest": snapshot, "source_manifest_file": recorded(sidecar), "source_origin_map": recorded(origin_path),
                      "source_origin": {key: origin[key] for key in ("all_staged_files_byte_equal", "verified_files", "original_project_root", "staged_project_root", "runner_command")},
                      "tool_version_log": recorded(version_log), "tool_version": "Version fixture",
                      "tool_version_process": {"returncode": 0, "timed_out": False, "log": recorded(version_log)}, "runs": []}
            report["source_origin"]["origin_map_sha256"] = evidence.digest(origin_path)
            for test in tests:
                for seed in (1, 2, 3):
                    log, wave = directory / f"{test}_{seed}.log", directory / f"{test}_{seed}.vcd"
                    log.write_text(transcript(test), encoding="utf-8")
                    wave.write_bytes(b"$timescale 1ns $end\n$enddefinitions $end\n#0\n0!\n#1\n1!\n")
                    assessed = evidence.assess_run(transcript(test), 0, False, test, phase == "negative")
                    command = [binary, "+UVM_TESTNAME=" + test, f"+verilator+seed+{seed}"]
                    report["runs"].append({"test": test, "seed": seed, "status": assessed["raw_status"],
                                           "uvm_errors": assessed["uvm_errors"], "uvm_fatals": 0, "returncode": 0, "timed_out": False,
                                           "command": command, "log": recorded(log), "waveform_file": recorded(wave)})
                    audit["runs"].append({"phase": phase, "test": test, "seed": seed, **assessed,
                                          "command": command, "returncode": 0, "timed_out": False, "log": recorded(log),
                                          "log_sha256": evidence.digest(log), "waveform_file": recorded(wave)})
            raw = directory / "report.json"
            raw.write_text(json.dumps(report), encoding="utf-8")
            wrapper_log = session / f"{phase}_runner.log"
            wrapper_log.write_text("Wrapper fixture, not an actual RTL run\n", encoding="utf-8")
            audit["raw_reports"].append({"phase": phase, "path": recorded(raw), "sha256": evidence.digest(raw),
                                         "raw_status": report["status"],
                                         "source_identity": {**common, "source_snapshot_file": recorded(sidecar)},
                                         "runner_process": {"returncode": int(phase == "negative"), "timed_out": False, "log": recorded(wrapper_log)}})
            profiles[phase] = (raw, report, origin_path)
        audit["identity"]["source_snapshot_file"] = audit["raw_reports"][0]["source_identity"]["source_snapshot_file"]
        audit_path = session / "protocol_report.json"
        audit_path.write_text(json.dumps(audit), encoding="utf-8")
        return project, audit_path, audit, profiles

    def package(self, root, project, audit_path):
        output = root / "evidence"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = evidence.main(["--report", str(audit_path), "--out", str(output), "--project-root", str(project)])
        return result, output

    def test_portable_bundle_preserves_payloads_raw_fail_and_all_local_links(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project, audit_path, audit, _ = self.fixture(root)
            result, output = self.package(root, project, audit_path)
            self.assertEqual(result, 0)
            summary = evidence.read_json(output / "summary.json")
            self.assertEqual(summary["status"], "PASS")
            self.assertEqual(summary["metrics"], evidence.METRICS)
            self.assertEqual(len(summary["runs"]), 15)
            negative = [run for run in summary["runs"] if run["phase"] == "negative"]
            self.assertEqual({run["raw_status"] for run in negative}, {"FAIL"})
            self.assertEqual({run["classification"] for run in negative}, {"DETECTED"})
            self.assertEqual(sum(bool(run["waveform_file"]) for run in summary["runs"]), 3)
            inputs = json.loads((output / "inputs.json").read_text(encoding="utf-8"))
            self.assertEqual(sum(item["role"] == "protocol_simulation_log" for item in inputs), 15)
            self.assertEqual(sum(item["role"] == "protocol_representative_vcd" for item in inputs), 3)
            for item in inputs:
                source, copied = Path(item["original_path"]), output / item["bundled_path"]
                self.assertEqual(source.read_bytes(), copied.read_bytes())
                self.assertEqual(evidence.digest(copied), item["sha256"])
            html = (output / "index.html").read_text(encoding="utf-8")
            for href in re.findall(r'href="([^"]+)"', html):
                self.assertTrue((output / href).is_file(), href)
            self.assertEqual(evidence.read_json(output / summary["raw_audit"]), audit)
            self.assertIn("does not reopen", summary["identity"]["scope"])

    def test_log_tamper_even_with_updated_log_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project, path, audit, _ = self.fixture(root)
            run = next(run for run in audit["runs"] if run["phase"] == "negative")
            log = evidence.reference(run["log"], path, project)
            log.write_text(log.read_text().replace("[APB_TIMEOUT]", "[UNRELATED]"), encoding="utf-8")
            run["log_sha256"] = evidence.digest(log)
            path.write_text(json.dumps(audit), encoding="utf-8")
            with self.assertRaises(SystemExit) as error:
                self.package(root, project, path)
            self.assertEqual(error.exception.code, 2)

    def test_stats_classification_and_identity_tamper_are_rejected(self):
        for mode in ("stats", "classification", "identity", "matrix", "audit_status"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                project, path, audit, _ = self.fixture(root)
                if mode == "stats": audit["runs"][0]["stats"]["completed"] += 1
                if mode == "classification": audit["runs"][0]["classification"] = "DETECTED"
                if mode == "identity": audit["raw_reports"][1]["source_identity"]["binary_sha256"] = "b" * 64
                if mode == "matrix": audit["runs"].pop()
                if mode == "audit_status": audit["status"] = "DRY_RUN"
                path.write_text(json.dumps(audit), encoding="utf-8")
                with self.assertRaises(SystemExit):
                    self.package(root, project, path)

    def test_snapshot_and_stage_tamper_remain_invalid_after_outer_hashes_are_updated(self):
        for mode in ("snapshot", "stage_sha", "stage_bytes", "duplicate_stage"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                project, path, audit, profiles = self.fixture(root)
                raw, report, origin_path = profiles["positive"]
                if mode == "snapshot":
                    report["source_manifest"]["snapshot_sha256"] = "b" * 64
                    sidecar = evidence.reference(report["source_manifest_file"], raw, project)
                    sidecar.write_text(json.dumps(report["source_manifest"]), encoding="utf-8")
                else:
                    origin = evidence.read_json(origin_path)
                    if mode == "stage_sha": origin["files"][0]["staged_sha256"] = "b" * 64
                    if mode == "stage_bytes": origin["files"][0]["bytes"] += 1
                    if mode == "duplicate_stage":
                        origin["files"].append(origin["files"][0])
                        origin["verified_files"] += 1
                        report["source_origin"]["verified_files"] += 1
                    origin_path.write_text(json.dumps(origin), encoding="utf-8")
                    report["source_origin"]["origin_map_sha256"] = evidence.digest(origin_path)
                raw.write_text(json.dumps(report), encoding="utf-8")
                audit["raw_reports"][0]["sha256"] = evidence.digest(raw)
                path.write_text(json.dumps(audit), encoding="utf-8")
                with self.assertRaises(SystemExit):
                    self.package(root, project, path)

    def test_existing_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project, path, _, _ = self.fixture(root)
            output = root / "evidence"
            output.mkdir()
            (output / "keep.txt").write_text("keep", encoding="utf-8")
            with self.assertRaises(SystemExit):
                self.package(root, project, path)
            self.assertEqual((output / "keep.txt").read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
