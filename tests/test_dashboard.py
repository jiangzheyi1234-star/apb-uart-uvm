"""Dashboard ingestion integrity tests; fixture logs are not RTL evidence."""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

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

    def code_fixture(self, root, filename="./rtl_fixed\\uart_rx.sv"):
        base = root / "release"
        base.mkdir()
        (base / "snapshot.json").write_text(json.dumps({"project_files": [{"path": "rtl_fixed/uart_rx.sv"}]}), encoding="utf-8")
        path = base / "coverage.info"
        path.write_text(f"SF:{filename}\nDA:10,4\nDA:20,0\nBRDA:10,0,0,0\nBRDA:10,0,0,3\nend_of_record\n", encoding="utf-8")
        report = {"rtl_variant": "fixed", "build_source_snapshot": {"manifest_input": "snapshot.json"}}
        return base, report, path

    def test_code_files_are_authorized_relative_and_keep_lcov_scope_totals(self):
        with tempfile.TemporaryDirectory() as temporary:
            base, report, path = self.code_fixture(Path(temporary))
            summary = dashboard.lcov_summary(path)
            files = dashboard.coverage_code_files(base, report, path, summary)
            self.assertEqual(files, [{"source_path": "rtl_fixed/uart_rx.sv", "lines": {"hit": 1, "total": 2},
                                      "branches": {"hit": 1, "total": 2}, "gaps": [
                                          {"line": 10, "line_hits": 4, "line_misses": 0, "branches_hit": 1, "branches_total": 2},
                                          {"line": 20, "line_hits": 0, "line_misses": 1, "branches_hit": 0, "branches_total": 0}]}])
            summary["source_scopes"]["rtl"]["branches_total"] = 99
            with self.assertRaisesRegex(ValueError, "contradicts"):
                dashboard.coverage_code_files(base, report, path, summary)

    def test_untrusted_paths_and_older_evidence_do_not_gain_source_links(self):
        paths = ["/outside/rtl_fixed/uart_rx.sv", "C:\\outside\\rtl_fixed\\uart_rx.sv",
                 "rtl_fixed/../uart_rx.sv", "rtl_fixed/uart_rx.sv#L1", "rtl/uart_rx.sv", "rtl_fixed/unrecorded.sv"]
        for filename in paths:
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temporary:
                base, report, path = self.code_fixture(Path(temporary), filename)
                self.assertIsNone(dashboard.coverage_code_files(base, report, path, dashboard.lcov_summary(path)))
        with tempfile.TemporaryDirectory() as temporary:
            base, report, path = self.code_fixture(Path(temporary))
            self.assertIsNone(dashboard.coverage_code_files(base, {"rtl_variant": "fixed"}, path, dashboard.lcov_summary(path)))
            with path.open("a", encoding="utf-8") as output:
                output.write("SF:rtl_fixed/uart_rx.sv\nDA:10,1\nend_of_record\n")
            self.assertIsNone(dashboard.coverage_code_files(base, report, path, dashboard.lcov_summary(path)))

    def test_code_file_links_use_the_same_anchored_repository_and_pinned_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            template = root / "template"
            template.mkdir()
            for filename in ("index.html", "app.js", "styles.css"):
                (template / filename).write_text("", encoding="utf-8")
            profile = {"gaps": [], "code_files": [{"source_path": "rtl_fixed/uart_rx.sv",
                                                   "lines": {"hit": 1, "total": 2},
                                                   "branches": {"hit": 1, "total": 2}, "gaps": []}]}
            cases = [("owner/repo", "a" * 40, True), ("owner/repo", "feature/source-view", False),
                     ("owner/repo", None, False),
                     ("owner/repo/../other", "main", False), ("https://evil.example/repo", "main", False),
                     ("owner/repo", "main/../../other", False)]
            for repository, ref, safe in cases:
                with self.subTest(repository=repository, ref=ref), \
                        patch.object(dashboard, "verify_bundle", return_value=[]), \
                        patch.object(dashboard, "core_data", return_value=([], [copy.deepcopy(profile)], [], [])), \
                        patch.object(dashboard, "control_data", return_value=[]), \
                        patch.object(dashboard, "protocol_data", return_value=([], [])):
                    result = dashboard.build(root, root / "out", template, "unit", repository, ref)
                if safe:
                    self.assertEqual(result["coverage"][0]["code_files"][0]["source_url"],
                                     f"https://github.com/{repository}/blob/{ref}/rtl_fixed/uart_rx.sv")
                else:
                    self.assertEqual(result["coverage"][0]["code_files"][0]["lines"], {"hit": 1, "total": 2})
                    self.assertNotIn("source_url", result["coverage"][0]["code_files"][0])


if __name__ == "__main__":
    unittest.main()
