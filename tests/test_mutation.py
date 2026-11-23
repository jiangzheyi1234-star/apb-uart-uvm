"""Negative-control tool tests use explicit temporary subprocess fixtures."""

import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("uart_mutation", ROOT / "py" / "run_mutation.py")
mutation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mutation)
CLEAN = "UVM_INFO @ 1 [UART_UVM_TEST_PASS] fixture completed\nUVM_ERROR : 0\nUVM_FATAL : 0\n"


def failed(case, *, active=True, error_id=None, fatal=0):
    activation = f"UVM_INFO @ 0 [MUTATION_ACTIVE] {case['mutation']}\n" if active else ""
    return activation + f"UVM_ERROR @ 1 [{error_id or case['expected_id']}] fixture comparison failure\nUVM_ERROR : 1\nUVM_FATAL : {fatal}\n"


def make_baseline(directory):
    binary = directory / "fixture_binary"
    binary.write_bytes(b"Explicit unit-test fixture, not a Verilator executable\n")
    snapshot = {"captured_before_compile": True, "rtl_variant": "fixed",
                "project_files": [{"path": "tb/fixture.sv", "sha256": "a" * 64}],
                "uvm_files": [{"path": "uvm_pkg.sv", "sha256": "b" * 64}]}
    stable = {key: snapshot[key] for key in ("project_files", "uvm_files", "rtl_variant")}
    snapshot["snapshot_sha256"] = hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()
    runs = []
    for test in mutation.CONTROL_TESTS:
        log = directory / (test + ".log")
        log.write_text(CLEAN, encoding="utf-8")
        runs.append({"test": test, "seed": 1, "status": "PASS", "returncode": 0, "timed_out": False, "log": str(log)})
    report = {"status": "PASS", "rtl_variant": "fixed", "simulator": "verilator", "tool_version": "explicit test fixture",
              "build": [{"returncode": 0, "timed_out": False, "command": ["fixture-compiler"]}],
              "compiled_binary": {"path": str(binary), "sha256": mutation.digest(binary), "bytes": binary.stat().st_size},
              "source_manifest": snapshot, "runs": runs}
    path = directory / "baseline.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path, binary


class MutationClassificationTests(unittest.TestCase):
    def test_only_specific_activated_functional_errors_are_detected(self):
        for case in mutation.CASES:
            result = mutation.assess_mutation(failed(case), 0, False, case)
            self.assertEqual(result["status"], "DETECTED")
            self.assertEqual(result["raw_simulation_status"], "FAIL")

    def test_missing_activation_or_wrong_fault_never_counts(self):
        case = mutation.CASES[0]
        for text in (failed(case, active=False), failed(case).replace("tx_data_xor", "rx_data_xor")):
            self.assertEqual(mutation.assess_mutation(text, 0, False, case)["status"], "INVALID")

    def test_unrelated_failure_and_pass_marker_do_not_count(self):
        case = mutation.CASES[0]
        self.assertEqual(mutation.assess_mutation(failed(case, error_id="UNRELATED"), 0, False, case)["status"], "INVALID")
        self.assertEqual(mutation.assess_mutation(failed(case) + CLEAN, 0, False, case)["status"], "NOT_DETECTED")

    def test_mixed_intended_and_unrelated_errors_invalidate_detection(self):
        case = mutation.CASES[0]
        text = failed(case) + "UVM_ERROR @ 2 [UNRELATED] independent environment failure\n"
        result = mutation.assess_mutation(text, 0, False, case)
        self.assertEqual(result["status"], "INVALID")
        self.assertEqual(result["observed_error_ids"], ["TX_MISMATCH", "UNRELATED"])

    def test_crashes_timeouts_fatals_and_simulator_errors_are_invalid(self):
        case = mutation.CASES[0]
        for text, code, timeout in ((failed(case), 1, False), (failed(case), 0, True),
                                    (failed(case, fatal=1), 0, False),
                                    (failed(case) + "UVM_FATAL @ 2 [BROKEN] fatal despite stale zero summary\n", 0, False),
                                    (failed(case) + "%Error: simulator failure\n", 0, False)):
            self.assertEqual(mutation.assess_mutation(text, code, timeout, case)["status"], "INVALID")

    def test_clean_control_rejects_any_activation(self):
        self.assertEqual(mutation.assess_control(CLEAN, 0, False)["status"], "PASS")
        self.assertEqual(mutation.assess_control("UVM_INFO @ 0 [MUTATION_ACTIVE] tx_data_xor\n" + CLEAN, 0, False)["status"], "FAIL")


class ProvenanceAndExecutionTests(unittest.TestCase):
    def test_baseline_rejects_changed_binary_and_missing_test(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            baseline, binary = make_baseline(directory)
            mutation.validate_baseline(baseline, None, 1)
            binary.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "differs"):
                mutation.validate_baseline(baseline, None, 1)
            baseline, binary = make_baseline(directory)
            report = json.loads(baseline.read_text())
            report["runs"].pop()
            baseline.write_text(json.dumps(report))
            with self.assertRaisesRegex(ValueError, "one PASS"):
                mutation.validate_baseline(baseline, None, 1)

    def test_actual_fixture_processes_run_controls_before_and_after_all_faults(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            baseline, binary = make_baseline(directory)
            output = directory / "out"
            actual_run = mutation.regression.run_process
            calls = []

            def fixture_process(command, cwd, log, timeout):
                calls.append(command)
                requested = next((arg.removeprefix("+MUTATION=") for arg in command if arg.startswith("+MUTATION=")), None)
                case = next((case for case in mutation.CASES if case["mutation"] == requested), None)
                transcript = failed(case) if case else CLEAN
                # Exercise real process capture and exit handling while keeping
                # the fake UVM transcript explicitly inside a temporary fixture.
                return actual_run([sys.executable, "-c", "print(" + repr(transcript) + ",end='')"], cwd, log, timeout)

            with patch.object(mutation.regression, "run_process", side_effect=fixture_process), contextlib.redirect_stdout(io.StringIO()):
                status = mutation.main(["--baseline-report", str(baseline), "--out", str(output)])
            report = json.loads((output / "mutation_report.json").read_text(encoding="utf-8"))
            self.assertEqual(status, 0)
            self.assertEqual(len(calls), 10)
            self.assertEqual(report["metrics"]["clean_control_passes"], 6)
            self.assertEqual(report["metrics"]["mutations_detected"], 4)
            self.assertEqual(report["metrics"]["mutation_score_percent"], 100.0)
            self.assertEqual([row["phase"] for row in report["runs"]], ["control_before"] * 3 + ["mutation"] * 4 + ["control_after"] * 3)
            self.assertTrue(report["binary_unchanged_after_controls"])


if __name__ == "__main__":
    unittest.main()
