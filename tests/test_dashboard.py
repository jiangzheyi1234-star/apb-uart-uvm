"""Dashboard ingestion integrity tests; fixture logs are not RTL evidence."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "py"))
SPEC = importlib.util.spec_from_file_location("dashboard_builder", ROOT / "py/build_dashboard.py")
dashboard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(dashboard)


class DashboardInputTests(unittest.TestCase):
    def fixture(self, root, raw_status="PASS"):
        base = root / "release"
        (base / "inputs").mkdir(parents=True)
        log = ("UVM_INFO @ 1 [SB_COUNTS] TX=1 RX=2 resets=1 max_tx=1 max_rx=1\n"
               "UVM_INFO @ 1 [UART_UVM_TEST_PASS] done\n"
               "UVM_WARNING : 2\nUVM_ERROR : 0\nUVM_FATAL : 0\n")
        (base / "inputs/log.txt").write_text(log, encoding="utf-8")
        raw = {"status": raw_status, "simulator": "verilator", "runs": [
            {"test": "uart_parity_requirement_test", "seed": 1, "status": raw_status, "returncode": 0, "timed_out": False}
        ]}
        (base / "inputs/report.json").write_text(json.dumps(raw), encoding="utf-8")
        row = {"test": "uart_parity_requirement_test", "seed": 1, "status": raw_status, "transcript": "inputs/log.txt",
               "uvm": {"error": 0, "fatal": 0, "warning": 2},
               "scoreboard": {"tx": 1, "rx": 2, "resets": 1, "max_tx": 1, "max_rx": 1}, "waveform": None}
        summary = {"reports": [{"rtl_variant": "upstream", "report_input": "inputs/report.json", "runs": [row], "coverage": None,
                                "tool_version": "unit fixture", "build_source_snapshot": {"uvm_version": "unit fixture"}}]}
        (base / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
        return base, summary

    def test_missing_metrics_are_not_invented_and_clean_fail_is_not_expected_defect(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base, _ = self.fixture(root, "FAIL")
            rows, _, _, _ = dashboard.core_data(base, root)
            self.assertEqual(rows[0]["raw_status"], "FAIL")
            self.assertFalse(rows[0]["expected"])
            self.assertIsNone(rows[0]["metrics"]["duration_s"])
            self.assertEqual(rows[0]["metrics"]["rx"], 2)

    def test_changed_summary_count_is_rejected_against_original_transcript(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base, summary = self.fixture(root)
            summary = copy.deepcopy(summary)
            summary["reports"][0]["runs"][0]["scoreboard"]["tx"] = 999
            (base / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "contradict"):
                dashboard.core_data(base, root)

    def test_changed_or_outside_manifest_inputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "release"
            base.mkdir()
            data = b"original evidence\n"
            (base / "input.bin").write_bytes(data)
            entry = {"bundled_path": "input.bin", "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            (base / "inputs.json").write_text(json.dumps([entry]), encoding="utf-8")
            self.assertEqual(len(dashboard.verify_bundle(base, root)), 1)
            (base / "input.bin").write_bytes(b"edited evidence\n")
            with self.assertRaisesRegex(ValueError, "mismatch"):
                dashboard.verify_bundle(base, root)
            (root / "outside.bin").write_bytes(data)
            entry["bundled_path"] = "../outside.bin"
            (base / "inputs.json").write_text(json.dumps([entry]), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "escapes"):
                dashboard.verify_bundle(base, root)


if __name__ == "__main__":
    unittest.main()
