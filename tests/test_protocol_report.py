"""Protocol audit rejection/identity tests. Fixture transcripts are not RTL evidence."""

import contextlib
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("protocol_checks", ROOT / "py" / "run_protocol_checks.py")
protocol = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = protocol
SPEC.loader.exec_module(protocol)


def transcript(test="apb_wait_state_test"):
    values = {
        "apb_wait_state_test": "completed=11 reads=6 writes=5 wait0=3 wait1=3 wait3=3 wait7=2 max_wait=7 reset_aborts=0 timeout_aborts=0",
        "apb_reset_abort_test": "completed=4 reads=2 writes=2 wait0=1 wait1=1 wait3=1 wait7=1 max_wait=7 reset_aborts=1 timeout_aborts=0",
        "apb_timeout_control_test": "completed=2 reads=1 writes=1 wait0=0 wait1=0 wait3=0 wait7=2 max_wait=7 reset_aborts=0 timeout_aborts=0",
        protocol.NEGATIVE_TEST: "completed=3 reads=2 writes=1 wait0=1 wait1=1 wait3=1 wait7=0 max_wait=3 reset_aborts=0 timeout_aborts=1",
    }
    negative = test == protocol.NEGATIVE_TEST
    events = ("UVM_INFO @ 0 [APB_TIMEOUT_ARMED] test=" + test + "\n"
              "UVM_ERROR @ 80 [APB_TIMEOUT] PREADY remained low\n"
              "UVM_INFO @ 200 [APB_TIMEOUT_SCENARIO_COMPLETE] test=" + test + " timeout_wait_cycles=8 recovery_completed=3\n") if negative else ""
    completion = "" if negative else "UVM_INFO @ 250 [APB_AGENT_TEST_PASS] completed\n"
    return events + "UVM_INFO @ 250 [APB_AGENT_STATS] test=" + test + " " + values[test] + "\n" + completion + f"UVM_ERROR : {int(negative)}\nUVM_FATAL : 0\n"


class TranscriptTests(unittest.TestCase):
    def test_all_positive_classes_and_negative_timeout(self):
        for test in (*protocol.POSITIVE_TESTS, protocol.NEGATIVE_TEST):
            negative = test == protocol.NEGATIVE_TEST
            with self.subTest(test=test):
                result = protocol.assess_run(transcript(test), 0, False, test, negative)
                self.assertEqual(result["classification"], "DETECTED" if negative else "PASS", result)
                self.assertEqual(result["raw_status"], "FAIL" if negative else "PASS")

    def test_negative_rejects_abnormal_exit_timeout_fatal_unrelated_or_multiple_errors(self):
        text = transcript(protocol.NEGATIVE_TEST)
        variants = (
            (text, 1, False), (text, 0, True),
            (text.replace("UVM_FATAL : 0", "UVM_FATAL : 1"), 0, False),
            (text.replace("[APB_TIMEOUT]", "[WRONG_CHECKER]"), 0, False),
            ("UVM_ERROR @ 1 [UNRELATED] bad\n" + text, 0, False),
            ("UVM_ERROR @ 1 missing_error_id\n" + text, 0, False),
            (text.replace("UVM_ERROR : 1", "UVM_ERROR : 2"), 0, False),
            (text.replace("UVM_ERROR @ 80", "UVM_ERROR @ 79 [APB_TIMEOUT] duplicate\nUVM_ERROR @ 80"), 0, False),
            ("%Error: bad simulation\n" + text, 0, False),
            ("Segmentation fault\n" + text, 0, False),
        )
        for value, returncode, timeout in variants:
            with self.subTest(text=value, returncode=returncode, timeout=timeout):
                self.assertEqual(protocol.assess_run(value, returncode, timeout, protocol.NEGATIVE_TEST, True)["classification"], "INVALID")

    def test_negative_requires_exact_ordered_markers_recovery_and_no_pass(self):
        text = transcript(protocol.NEGATIVE_TEST)
        for bad in (
            text.replace("[APB_TIMEOUT_ARMED]", "[MISSING]"),
            text.replace("[APB_TIMEOUT_SCENARIO_COMPLETE]", "[MISSING]"),
            text.replace("UVM_INFO @ 0 [APB_TIMEOUT_ARMED]", "COMMAND [APB_TIMEOUT_ARMED]"),
            text.replace("timeout_wait_cycles=8", "timeout_wait_cycles=7"),
            text.replace("recovery_completed=3", "recovery_completed=2"),
            text.replace("recovery_completed=3", "recovery_completed=9"),
            "UVM_INFO @ 999 [APB_AGENT_TEST_PASS] false pass\n" + text,
            "UVM_INFO @ 999 [UART_UVM_TEST_PASS] false pass\n" + text,
            text.replace("[APB_TIMEOUT_ARMED]", "[APB_TIMEOUT_SCENARIO_COMPLETE]"),
            text.replace("UVM_FATAL : 0", ""),
        ):
            with self.subTest(text=bad):
                self.assertEqual(protocol.assess_run(bad, 0, False, protocol.NEGATIVE_TEST, True)["classification"], "INVALID")

    def test_stats_must_be_real_consistent_and_sufficient(self):
        text = transcript()
        for bad in (
            text.replace("[APB_AGENT_STATS]", "[OTHER]"),
            text.replace("test=apb_wait_state_test", "test=wrong_test"),
            text.replace("completed=11", "completed=12"),
            text.replace("reads=6", "reads=-6"),
            text.replace("wait7=2", "wait7=1"),
            text.replace("max_wait=7", "max_wait=3"),
            text.replace("reset_aborts=0", "reset_aborts=1"),
            text.replace("timeout_aborts=0", "timeout_aborts=1"),
            text.replace("writes=5", "writes=5 writes=5"),
            text.replace("[APB_AGENT_TEST_PASS]", "[UART_UVM_TEST_PASS]"),
            "UVM_INFO @ 1 [APB_TIMEOUT_ARMED] unexpected\n" + text,
        ):
            with self.subTest(text=bad):
                self.assertEqual(protocol.assess_run(bad, 0, False, "apb_wait_state_test")["classification"], "INVALID")


class IdentityTests(unittest.TestCase):
    def make_report(self, root, phase="positive"):
        source = root / "project"
        uvm = root / "uvm"
        out = root / phase
        source.mkdir(exist_ok=True)
        uvm.mkdir(exist_ok=True)
        out.mkdir()
        for name, content in (("sim/files_protocol.f", "tb/protocol.sv\n"), ("tb/protocol.sv", "module tb_top; endmodule\n")):
            path = source / name
            path.parent.mkdir(exist_ok=True)
            path.write_text(content, encoding="utf-8")
        (uvm / "uvm_pkg.sv").write_text("// unit-test dependency fixture\n", encoding="utf-8")
        binary = root / "Vtb_top"
        binary.write_bytes(b"unit-test binary identity fixture, not a simulator")
        def entry(path, parent):
            return {"path": path.relative_to(parent).as_posix(), "bytes": path.stat().st_size, "sha256": protocol.regression.file_digest(path)}
        snapshot = {"captured_before_compile": True, "suite": "apb_protocol", "rtl_variant": None,
                    "project_files": [entry(source / name, source) for name in ("sim/files_protocol.f", "tb/protocol.sv")],
                    "uvm_files": [entry(uvm / "uvm_pkg.sv", uvm)], "uvm_source_root": str(uvm)}
        stable = {key: snapshot[key] for key in ("project_files", "uvm_files", "rtl_variant")}
        snapshot["snapshot_sha256"] = hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()
        sidecar = out / "source_snapshot.json"
        sidecar.write_text(json.dumps(snapshot), encoding="utf-8")
        build_log = out / "build.log"
        build_log.write_text("Fixture compiler transcript\n", encoding="utf-8")
        tests = protocol.POSITIVE_TESTS if phase == "positive" else (protocol.NEGATIVE_TEST,) if phase == "negative" else (protocol.POSITIVE_TESTS[0],)
        runs = []
        for test in tests:
            log = out / (test + ".log")
            log.write_text(transcript(test), encoding="utf-8")
            runs.append({"test": test, "seed": 1, "status": "FAIL" if phase == "negative" else "PASS",
                         "returncode": 0, "timed_out": False, "uvm_errors": int(phase == "negative"), "uvm_fatals": 0,
                         "command": [str(binary), "+UVM_TESTNAME=" + test, "+verilator+seed+1"], "log": str(log)})
        report = {"status": "FAIL" if phase == "negative" else "PASS", "suite": "apb_protocol", "rtl_variant": None,
                  "simulator": "verilator", "completion_marker": "APB_AGENT_TEST_PASS", "runs": runs,
                  "build": [{"returncode": 0, "timed_out": False,
                             "command": ["fixture-verilator", "--binary", "--top-module", "tb_top", "-f", str(source / "sim/files_protocol.f")], "log": str(build_log)}],
                  "compiled_binary": {"path": str(binary), "bytes": binary.stat().st_size, "sha256": protocol.regression.file_digest(binary)},
                  "source_manifest": snapshot, "source_manifest_file": str(sidecar)}
        path = out / "report.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        return source, path, report

    def test_valid_profiles_keep_raw_fail_separate_from_detected(self):
        for phase in ("positive", "negative", "recovery"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temp:
                source, path, report = self.make_report(Path(temp), phase)
                identity, runs = protocol.audit_profile(path, phase, [1], source)
                self.assertTrue(identity["current_project_sources_match"])
                self.assertEqual(runs[0]["classification"], "DETECTED" if phase == "negative" else "PASS")
                self.assertEqual(json.loads(path.read_text()), report)

    def test_source_binary_or_uvm_drift_invalidates_evidence(self):
        for changed in ("source", "binary", "uvm", "sidecar"):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temp:
                source, path, report = self.make_report(Path(temp))
                targets = {"source": source / "tb/protocol.sv", "binary": Path(report["compiled_binary"]["path"]),
                           "uvm": Path(report["source_manifest"]["uvm_source_root"]) / "uvm_pkg.sv",
                           "sidecar": Path(report["source_manifest_file"])}
                targets[changed].write_text("changed\n", encoding="utf-8")
                with self.assertRaises(ValueError):
                    protocol.audit_profile(path, "positive", [1], source)

    def test_wrong_suite_partial_matrix_wrong_seed_flags_and_dry_run_are_rejected(self):
        for mode in ("suite", "matrix", "seed", "rtl_flag", "coverage", "dry_run", "build"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp:
                source, path, original = self.make_report(Path(temp))
                report = copy.deepcopy(original)
                if mode == "suite": report["suite"] = "uart"
                if mode == "matrix": report["runs"].pop()
                if mode == "seed": report["runs"][0]["command"][-1] = "+verilator+seed+2"
                if mode == "rtl_flag": report["runs"][0]["command"].append("+RTL_FIXED=1")
                if mode == "coverage": report["runs"][0]["coverage_file"] = "uart_coverage.dat"
                if mode == "dry_run": report["status"] = "DRY_RUN"
                if mode == "build": report["build"] = []
                path.write_text(json.dumps(report), encoding="utf-8")
                with self.assertRaises(ValueError):
                    protocol.audit_profile(path, "positive", [1], source)

    def test_audit_entry_has_no_dry_run_pass_mode(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            protocol.main(["--out", "unused", "--dry-run"])
        self.assertEqual(error.exception.code, 2)

    def test_orchestrator_separates_profiles_and_requires_same_binary(self):
        for change_binary in (False, True):
            with self.subTest(change_binary=change_binary), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                project = root / "project"
                project.mkdir()
                output = root / "out"

                def fixture_process(command, cwd, log, timeout):
                    phase = Path(command[command.index("--out") + 1]).name
                    _, old_path, report = self.make_report(root, phase)
                    if change_binary and phase == "negative":
                        binary = Path(report["compiled_binary"]["path"])
                        binary.write_bytes(b"different compiled binary")
                        report["compiled_binary"].update(sha256=protocol.regression.file_digest(binary), bytes=binary.stat().st_size)
                    requested = output / phase
                    requested.mkdir()
                    (requested / "report.json").write_text(json.dumps(report), encoding="utf-8")
                    log.write_text("Wrapper fixture, not an RTL run\n", encoding="utf-8")
                    return protocol.regression.ProcessResult(command, int(phase == "negative"), False, 0, str(log))

                with patch.object(protocol, "ROOT", project), patch.object(protocol, "os", SimpleNamespace(name="posix")), \
                        patch.object(protocol.regression, "run_process", side_effect=fixture_process), \
                        contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    result = protocol.main(["--out", str(output), "--seeds", "1"])
                audited = json.loads((output / "protocol_report.json").read_text(encoding="utf-8"))
                self.assertEqual(result, 1 if change_binary else 0, audited)
                self.assertEqual(audited["status"], "FAIL" if change_binary else "PASS")
                if not change_binary:
                    self.assertEqual(audited["metrics"]["raw_simulations"], 5)
                    self.assertEqual(audited["metrics"]["positive_passes"], 3)
                    self.assertEqual(audited["metrics"]["timeouts_detected"], 1)
                    self.assertEqual(audited["metrics"]["recovery_passes"], 1)
                    self.assertEqual([entry["phase"] for entry in audited["raw_reports"]], ["positive", "negative", "recovery"])
                    self.assertEqual(json.loads((output / "negative/report.json").read_text())["status"], "FAIL")
                    self.assertTrue(audited["identity"]["same_binary_all_profiles"])


if __name__ == "__main__":
    unittest.main()
