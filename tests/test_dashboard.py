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


class FailureEvidenceTests(unittest.TestCase):
    def test_excerpt_preserves_actual_lines_excludes_counts_and_limits_size(self):
        first = "  # UVM_ERROR @ 10: env [STATUS] expected 0x65 got 0x61"
        long = "UVM_ERROR @ 20 [TX_MISMATCH] " + "x" * 600
        fatal = "UVM_FATAL @ 30 [TIMEOUT] recorded message"
        log = "UVM_ERROR : 12\n# UVM_FATAL : 0\nUVM_WARNING @ 1 [LIB] warning\n" + "\n".join(
            [first, long, fatal, "UVM_ERROR @ 40 [EXTRA] fourth record"])
        self.assertEqual(dashboard.failure_excerpt(log), [first, long[:499] + "…", fatal])
        self.assertEqual(dashboard.failure_excerpt("UVM_ERROR : 2\nUVM_FATAL : 0\n"), [])

    def test_unavailable_reasons_only_apply_to_unrendered_failures(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "run.log").write_text("UVM_ERROR @ 10 [IRQ] exact log line\nUVM_ERROR : 1\n", encoding="utf-8")
            rows = [
                {"id": "rendered", "raw_status": "FAIL", "suite_id": "uart_core", "log_url": "run.log", "waveform_unavailable": "old"},
                {"id": "fault", "raw_status": "FAIL", "suite_id": "fault_control", "phase": "mutation", "log_url": "run.log"},
                {"id": "protocol", "raw_status": "FAIL", "suite_id": "apb_protocol", "seed": 2, "log_url": "run.log"},
                {"id": "pass", "raw_status": "PASS", "suite_id": "uart_core", "log_url": "run.log"},
            ]
            dashboard.annotate_failures(root, rows, [{"run_id": "rendered"}])
            self.assertNotIn("waveform_unavailable", rows[0])
            self.assertIn("未启用 TRACE", rows[1]["waveform_unavailable"])
            self.assertIn("未保留", rows[2]["waveform_unavailable"])
            self.assertNotIn("failure_excerpt", rows[3])
            self.assertEqual(rows[0]["failure_excerpt"], ["UVM_ERROR @ 10 [IRQ] exact log line"])
            self.assertEqual([r["raw_status"] for r in rows], ["FAIL", "FAIL", "FAIL", "PASS"])

    def test_verified_supplement_is_decoded_for_exact_run_and_hashed_as_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = root / "release"
            folder = base / "recovered-vcd"
            folder.mkdir(parents=True)
            (folder / "index.json").write_text("{}", encoding="utf-8")
            wave = folder / "failed_seed_2.vcd"
            wave.write_bytes(b"fixture bytes")
            entry = {"url": "release/recovered-vcd/failed_seed_2.vcd", "sha256": dashboard.digest(wave), "bytes": wave.stat().st_size}
            row = {"id": "uart_core:upstream:failed:2", "suite_id": "uart_core", "variant": "upstream", "raw_status": "FAIL", "test": "failed", "seed": 2}
            waves, inputs = [], []
            with patch.object(dashboard, "recovered_wave_links", return_value={row["id"]: entry}), \
                    patch.object(dashboard, "waveform", return_value={"run_id": row["id"], "source": {"sha256": entry["sha256"]}}) as decode:
                dashboard.append_recovered_waveforms(base, root, [row], waves, inputs)
            self.assertEqual(waves[0]["run_id"], row["id"])
            self.assertTrue(waves[0]["source"]["recovered"])
            self.assertEqual(decode.call_args.kwargs["run_id"], row["id"])
            self.assertEqual({item["path"] for item in inputs}, {"release/recovered-vcd/index.json", entry["url"]})
            wave.write_bytes(b"tampered")
            with patch.object(dashboard, "recovered_wave_links", return_value={row["id"]: entry}), \
                    self.assertRaisesRegex(ValueError, "bytes changed"):
                dashboard.append_recovered_waveforms(base, root, [row], [], [])


class VerificationPlanTests(unittest.TestCase):
    def rows(self):
        return [
            {"id": "core:1", "suite_id": "uart_core", "test": "shared_test", "variant": "fixed", "seed": 1, "raw_status": "PASS"},
            {"id": "protocol:negative", "suite_id": "apb_protocol", "test": "shared_test", "variant": "agent", "phase": "negative",
             "seed": 1, "raw_status": "FAIL", "classification": "DETECTED"},
            {"id": "core:2", "suite_id": "uart_core", "test": "shared_test", "variant": "fixed", "seed": 2, "raw_status": "PASS"},
            {"id": "core:upstream", "suite_id": "uart_core", "test": "shared_test", "variant": "upstream", "seed": 1, "raw_status": "FAIL"},
            {"id": "protocol:positive", "suite_id": "apb_protocol", "test": "shared_test", "variant": "agent", "phase": "positive",
             "seed": 1, "raw_status": "PASS"},
            {"id": "fault:mutation", "suite_id": "fault_control", "test": "shared_test", "variant": "fixed", "phase": "mutation",
             "seed": 1, "raw_status": "FAIL", "classification": "DETECTED"},
        ]

    def plan(self, checks):
        return {"groups": [{"id": "group", "title": "Authored group", "items": [
            {"id": "point", "title": "Authored point", "summary": "Intended behavior", "checks": checks}]}]}

    def test_conjunctive_filters_and_point_dedup_keep_suites_and_raw_results_separate(self):
        rows = self.rows()
        plan = self.plan([
            {"suite_id": "uart_core", "tests": ["shared_test", "shared_test"], "variants": ["fixed"]},
            {"suite_id": "apb_protocol", "tests": ["shared_test"], "phases": ["negative"], "variants": ["agent"]},
            {"suite_id": "uart_core", "tests": ["shared_test"], "variants": ["fixed"]},
        ])
        plan["groups"][0]["items"].append({"id": "other-point", "title": "Cross link", "summary": "Same measured test",
                                                "checks": [{"suite_id": "uart_core", "tests": ["shared_test"], "variants": ["fixed"]}]})
        original = copy.deepcopy((plan, rows))
        result = dashboard.bind_verification_plan(plan, rows)
        item, other = result["groups"][0]["items"]
        self.assertEqual(item["checks"][0]["run_ids"], ["core:1", "core:2"])
        self.assertEqual(item["checks"][1]["run_ids"], ["protocol:negative"])
        self.assertEqual(item["run_ids"], ["core:1", "protocol:negative", "core:2"])
        self.assertEqual(other["run_ids"], ["core:1", "core:2"])
        self.assertEqual(item["binding_status"], "recorded")
        self.assertEqual(item["title"], "Authored point")
        self.assertEqual((plan, rows), original)
        self.assertEqual(rows[1]["raw_status"], "FAIL")
        self.assertEqual(rows[1]["classification"], "DETECTED")
        self.assertEqual(result, dashboard.bind_verification_plan(plan, rows))

    def test_missing_unknown_and_empty_filters_remain_partial_or_unrecorded(self):
        plan = self.plan([
            {"suite_id": "uart_core", "tests": ["shared_test", "not_archived"], "variants": ["fixed"]},
            {"suite_id": "unknown_suite", "tests": ["shared_test"]},
            {"suite_id": "apb_protocol", "tests": ["shared_test"], "phases": ["unknown_phase"]},
            {"suite_id": "apb_protocol", "tests": ["shared_test"], "phases": ["negative"], "variants": ["fixed"]},
            {"suite_id": "uart_core", "tests": ["shared_test"], "phases": []},
            {"suite_id": "uart_core", "tests": ["shared_test"], "variants": []},
            {"suite_id": "uart_core", "tests": []},
        ])
        item = dashboard.bind_verification_plan(plan, self.rows())["groups"][0]["items"][0]
        self.assertEqual(item["binding_status"], "partial")
        self.assertEqual(item["checks"][0]["missing_tests"], ["not_archived"])
        self.assertEqual(item["checks"][0]["binding_status"], "partial")
        for check in item["checks"][1:]:
            self.assertEqual(check["run_ids"], [])
            self.assertEqual(check["binding_status"], "unrecorded")
        empty = dashboard.bind_verification_plan(self.plan([]), self.rows())["groups"][0]["items"][0]
        self.assertEqual(empty["run_ids"], [])
        self.assertEqual(empty["binding_status"], "unrecorded")

    def test_duplicate_ids_and_malformed_selectors_are_rejected(self):
        plan = self.plan([{"suite_id": "uart_core", "tests": ["shared_test"]}])
        cases = []
        duplicate_group = copy.deepcopy(plan)
        duplicate_group["groups"].append(copy.deepcopy(duplicate_group["groups"][0]))
        cases.append(duplicate_group)
        duplicate_item = copy.deepcopy(plan)
        duplicate_item["groups"].append({"id": "other-group", "title": "Other", "items": copy.deepcopy(plan["groups"][0]["items"])})
        cases.append(duplicate_item)
        for name, value in (("tests", "shared_test"), ("phases", "negative"), ("variants", [None]), ("suite_id", "")):
            malformed = copy.deepcopy(plan)
            malformed["groups"][0]["items"][0]["checks"][0][name] = value
            cases.append(malformed)
        cases.append({"groups": {}})
        for value in cases:
            with self.subTest(plan=value), self.assertRaises(ValueError):
                dashboard.bind_verification_plan(value, self.rows())

    def test_optional_template_mapping_is_added_only_when_present(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            template = root / "template"
            template.mkdir()
            for name in ("index.html", "app.js", "styles.css"):
                (template / name).write_text("", encoding="utf-8")
            for present in (False, True):
                if present:
                    (template / "verification-plan.json").write_text(json.dumps(self.plan([
                        {"suite_id": "apb_protocol", "tests": ["shared_test"], "phases": ["negative"]}])), encoding="utf-8")
                rows = self.rows()
                with patch.object(dashboard, "verify_bundle", return_value=[]), \
                        patch.object(dashboard, "core_data", return_value=(rows, [], [], [])), \
                        patch.object(dashboard, "control_data", return_value=[]), \
                        patch.object(dashboard, "protocol_data", return_value=([], [])):
                    result = dashboard.build(root, root / "out", template, "unit", "owner/repo")
                self.assertEqual("verification_plan" in result, present)
                self.assertEqual(result["runs"], self.rows())
                self.assertEqual(result["schema_version"], 1)
                if present:
                    self.assertEqual(result["verification_plan"]["groups"][0]["items"][0]["run_ids"], ["protocol:negative"])


if __name__ == "__main__":
    unittest.main()
