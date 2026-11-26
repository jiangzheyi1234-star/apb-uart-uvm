"""Parser and subprocess integration tests; these do not test the RTL."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("uart_regression", ROOT / "py" / "run_regression.py")
regression = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = regression
SPEC.loader.exec_module(regression)
FIXTURE = Path(__file__).parent / "fixtures" / "simulator_stub.py"
CLEAN = """UVM_INFO @ 100 [UART_UVM_TEST_PASS] Scoreboard completed
--- UVM Report Summary ---
UVM_ERROR : 0
UVM_FATAL : 0
"""


class ParserTests(unittest.TestCase):
    def test_clean_uvm_summary_and_completion(self):
        for prefix in ("", "# "):
            transcript = "\n".join(prefix + line for line in CLEAN.splitlines())
            self.assertEqual(regression.classify_log(transcript, 0).status, "PASS")

    def test_rejects_missing_or_forged_success(self):
        for transcript in (
            "", "PASS", CLEAN.replace("UVM_FATAL : 0", ""),
            CLEAN.replace("[UART_UVM_TEST_PASS]", "[FINISHED]"),
            CLEAN.replace("UVM_INFO @ 100", "COMMAND fake"),
        ):
            with self.subTest(transcript=transcript):
                self.assertEqual(regression.classify_log(transcript, 0).status, "FAIL")

    def test_rejects_reported_errors_even_with_zero_summary(self):
        for error in (
            "UVM_ERROR @ 55 [COMPARE] Mismatch\n",
            "# UVM_FATAL tb/test.sv(12) @ 55 [TIMEOUT] Timed out\n",
            "# ** Error: simulation failed\n",
            "# ** Error (suppressible): simulation failed\n",
            "Error-[FAILURE] simulation failed\n",
            "FATAL: tb_top: assertion failed\n",
            "%Error: tb_top.sv:10: Assertion failed\n",
        ):
            with self.subTest(error=error):
                self.assertEqual(regression.classify_log(error + CLEAN, 0).status, "FAIL")

    def test_summary_error_nonzero_exit_and_timeout(self):
        self.assertEqual(regression.classify_log(CLEAN.replace("UVM_ERROR : 0", "UVM_ERROR : 2"), 0).uvm_errors, 2)
        self.assertEqual(regression.classify_log(CLEAN, 1).status, "FAIL")
        self.assertEqual(regression.classify_log(CLEAN, 0, True).status, "TIMEOUT")

    def test_repeated_summary_must_all_be_clean(self):
        self.assertEqual(regression.classify_log("UVM_FATAL : 1\n" + CLEAN, 0).status, "FAIL")

    def test_protocol_marker_must_be_selected_explicitly_and_cannot_use_uart_pass(self):
        protocol = CLEAN.replace("UART_UVM_TEST_PASS", "APB_AGENT_TEST_PASS")
        self.assertEqual(regression.classify_log(protocol, 0).status, "FAIL")
        self.assertEqual(regression.classify_log(protocol, 0, pass_marker="APB_AGENT_TEST_PASS").status, "PASS")
        self.assertEqual(regression.classify_log(CLEAN, 0, pass_marker="APB_AGENT_TEST_PASS").status, "FAIL")
        self.assertEqual(regression.classify_log(protocol.replace("UVM_INFO", "COMMAND"), 0,
                                                 pass_marker="APB_AGENT_TEST_PASS").status, "FAIL")


class SubprocessTests(unittest.TestCase):
    def fixture_plans(self, directory, run_result="pass", build_result="pass"):
        calls = directory / "calls.txt"

        def fake_plans(args, output, uvm_src):
            build = [[sys.executable, str(FIXTURE), "compile", "--calls", str(calls), "--result", build_result]]
            runs = []
            for test in args.test or regression.DEFAULT_TESTS:
                for seed in args.seeds:
                    runs.append({"test": test, "seed": seed, "directory": str(output / f"{test}_{seed}"),
                                 "command": [sys.executable, str(FIXTURE), "simulate", "--calls", str(calls),
                                             "--test", test, "--seed", str(seed), "--result", run_result]})
            return build, runs
        return calls, fake_plans

    def run_main(self, arguments, fake_plans=None):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            if fake_plans:
                with tempfile.TemporaryDirectory() as source:
                    source_root = Path(source)
                    (source_root / "sim").mkdir()
                    (source_root / "sim" / "files.f").write_text("// fixture only\n", encoding="utf-8")
                    with patch.object(regression, "ROOT", source_root), patch.object(regression, "plans", side_effect=fake_plans), patch.object(regression.shutil, "which", return_value=sys.executable), patch.object(regression, "simulator_version_command", return_value=[sys.executable, "--version"]), patch.object(regression, "compiled_binary_path", return_value=None):
                        return regression.main(arguments)
            return regression.main(arguments)

    def test_compile_once_run_every_test_seed_and_write_reports(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            output = directory / "out"
            calls, fake = self.fixture_plans(directory)
            # VCS bypasses Questa's UVM include discovery; the subprocess is a fixture.
            result = self.run_main(["--sim", "vcs", "--seeds", "7", "19", "--out", str(output)], fake)
            self.assertEqual(result, 0)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "PASS")
            self.assertEqual(len(report["runs"]), 8)
            lines = calls.read_text(encoding="utf-8").splitlines()
            self.assertEqual(sum(line.startswith("compile ") for line in lines), 1)
            self.assertEqual(sum(line.startswith("simulate ") for line in lines), 8)
            self.assertTrue((output / "report.md").is_file())
            self.assertTrue(all(Path(run["log"]).is_file() for run in report["runs"]))
            self.assertTrue(report["source_manifest"]["captured_before_compile"])
            self.assertTrue(Path(report["source_manifest_file"]).is_file())
            self.assertIn("Python", report["tool_version"])  # Explicit subprocess fixture, not RTL evidence.

    def test_runtime_failures_propagate_to_exit_and_report(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            output = directory / "out"
            _, fake = self.fixture_plans(directory, run_result="fail")
            result = self.run_main(["--sim", "vcs", "--test", "uart_smoke_test", "--out", str(output)], fake)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(result, 1)
            self.assertEqual(report["status"], "FAIL")
            self.assertEqual(report["runs"][0]["uvm_errors"], 1)

    def test_build_failure_prevents_simulation(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            output = directory / "out"
            calls, fake = self.fixture_plans(directory, build_result="build_fail")
            result = self.run_main(["--sim", "vcs", "--out", str(output)], fake)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(result, 1)
            self.assertEqual(report["status"], "BUILD_FAIL")
            self.assertEqual(report["runs"], [])
            self.assertEqual(len(calls.read_text(encoding="utf-8").splitlines()), 1)

    def test_timeout_kills_subprocess_and_is_never_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            output = directory / "out"
            _, fake = self.fixture_plans(directory, run_result="timeout")
            result = self.run_main(["--sim", "vcs", "--test", "uart_smoke_test", "--timeout", "0.2", "--out", str(output)], fake)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(result, 1)
            self.assertEqual(report["runs"][0]["status"], "TIMEOUT")

    def test_dry_run_works_without_simulator_and_never_claims_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "out"
            result = self.run_main(["--sim", "questa", "--dry-run", "--out", str(output)])
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(result, 0)
            self.assertEqual(report["status"], "DRY_RUN")
            self.assertEqual({run["status"] for run in report["runs"]}, {"DRY_RUN"})
            self.assertEqual(report["build"], [])

    def test_missing_simulator_reports_error(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "out"
            with patch.object(regression.shutil, "which", return_value=None):
                result = self.run_main(["--sim", "vcs", "--out", str(output)])
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(result, 2)
            self.assertEqual(report["status"], "ERROR")
            self.assertIn("not found", report["reason"])

    def test_requested_missing_artifact_cannot_pass(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            output = directory / "out"
            _, fake = self.fixture_plans(directory)

            def missing_artifact(args, selected_output, uvm_src):
                commands, runs = fake(args, selected_output, uvm_src)
                for run in runs:
                    run["waveform_file"] = str(Path(run["directory"]) / "never_written.vcd")
                return commands, runs

            result = self.run_main(["--sim", "vcs", "--test", "uart_smoke_test", "--out", str(output)], missing_artifact)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(result, 1)
            self.assertEqual(report["status"], "FAIL")
            self.assertIn("Missing requested artifact", report["runs"][0]["reason"])


class CommandPlanTests(unittest.TestCase):
    def test_subsystem_plan_uses_its_own_tests_and_completion_marker(self):
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp)
            argv = ["--sim", "verilator", "--suite", "subsystem", "--dry-run", "--seeds", "1", "2",
                    "--trace", "--out", str(output)]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(regression.main(argv), 0)
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "DRY_RUN")
        self.assertEqual(report["rtl_variant"], "fixed")
        self.assertEqual(report["completion_marker"], "SUBSYSTEM_UVM_TEST_PASS")
        self.assertTrue(report["source_file_list"].endswith("files_subsystem.f"))
        self.assertEqual(len(report["runs"]), 8)
        self.assertEqual({row["test"] for row in report["runs"]}, set(regression.DEFAULT_SUBSYSTEM_TESTS))
        for row in report["runs"]:
            self.assertIn("+TRACE", row["command"])
            self.assertNotIn("+RTL_FIXED=1", row["command"])

    def test_subsystem_snapshot_is_independent_of_legacy_suites(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            files = ["tb/uart.sv", "tb/subsystem/suite.sv", "rtl_fixed/uart.sv", "rtl_subsystem/ram.sv",
                     "sim/files_subsystem.f", "sim/files_fixed.f", "sim/files_protocol.f"]
            for filename in files:
                path = root / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(filename, encoding="utf-8")
            scopes = {}
            with patch.object(regression, "ROOT", root):
                for suite in regression.SUITE_DEFAULT_TESTS:
                    args = regression.parser().parse_args(["--suite", suite, "--rtl", "fixed"])
                    snapshot = regression.capture_source_manifest(args, None)
                    scopes[suite] = {item["path"] for item in snapshot["project_files"]}
        self.assertEqual(scopes["subsystem"], set(files[:5]))
        self.assertEqual(scopes["apb_protocol"], {"tb/uart.sv", "sim/files_protocol.f"})
        self.assertEqual(scopes["uart"], {"tb/uart.sv", "rtl_fixed/uart.sv", "sim/files_fixed.f"})

    def test_protocol_suite_is_independent_for_every_simulator(self):
        for simulator in ("questa", "vcs", "verilator"):
            with self.subTest(simulator=simulator):
                args = regression.parser().parse_args(["--suite", "apb_protocol", "--sim", simulator, "--rtl", "fixed"])
                build, runs = regression.plans(args, Path("/tmp/protocol"), Path("/opt/uvm/src"))
                self.assertTrue(any(part.endswith("files_protocol.f") for command in build for part in command))
                self.assertFalse(any(part.endswith(("files_fixed.f", "files.f")) for command in build for part in command))
                self.assertEqual({run["test"] for run in runs}, set(regression.DEFAULT_PROTOCOL_TESTS))
                self.assertTrue(all("+RTL_FIXED=1" not in run["command"] for run in runs))
                self.assertTrue(all(run["coverage_file"] is None for run in runs))

    def test_protocol_dry_run_reports_suite_without_claiming_uart_rtl_or_pass(self):
        with tempfile.TemporaryDirectory() as temp, contextlib.redirect_stdout(io.StringIO()):
            output = Path(temp) / "protocol"
            result = regression.main(["--suite", "apb_protocol", "--rtl", "fixed", "--sim", "verilator",
                                      "--dry-run", "--seeds", "1", "2", "3", "--out", str(output)])
            report = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(result, 0)
            self.assertEqual(report["status"], "DRY_RUN")
            self.assertEqual(report["suite"], "apb_protocol")
            self.assertIsNone(report["rtl_variant"])
            self.assertEqual(report["completion_marker"], "APB_AGENT_TEST_PASS")
            self.assertEqual(len(report["runs"]), 9)
            self.assertNotIn("coverage", report)
            self.assertFalse(report["build"])

    def test_protocol_cannot_export_uart_functional_coverage(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            regression.main(["--suite", "apb_protocol", "--coverage", "--dry-run"])
        self.assertEqual(error.exception.code, 2)

    def test_protocol_snapshot_has_no_uart_rtl_and_preserves_stable_hash_schema(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("tb", "sim", "rtl", "rtl_fixed"):
                (root / name).mkdir()
            (root / "tb" / "protocol.sv").write_text("module tb_top; endmodule\n", encoding="utf-8")
            (root / "sim" / "files_protocol.f").write_text("tb/protocol.sv\n", encoding="utf-8")
            for variant in ("rtl", "rtl_fixed"):
                (root / variant / "uart.sv").write_text("module uart; endmodule\n", encoding="utf-8")
            args = regression.parser().parse_args(["--suite", "apb_protocol", "--rtl", "fixed"])
            with patch.object(regression, "ROOT", root):
                snapshot = regression.capture_source_manifest(args, None)
            self.assertEqual(snapshot["suite"], "apb_protocol")
            self.assertIsNone(snapshot["rtl_variant"])
            self.assertEqual({entry["path"] for entry in snapshot["project_files"]}, {"tb/protocol.sv", "sim/files_protocol.f"})
            import hashlib
            stable = {key: snapshot[key] for key in ("project_files", "uvm_files", "rtl_variant")}
            self.assertEqual(snapshot["snapshot_sha256"], hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest())

    def test_linux_default_protocol_stage_and_build_are_separate_from_uart(self):
        spec = importlib.util.spec_from_file_location("linux_protocol_stage", ROOT / "py" / "run_linux_regression.py")
        stage = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(stage)
        self.assertNotEqual(stage.default_stage_directory("uart"), stage.default_stage_directory("apb_protocol"))
        for variant in ("upstream", "fixed"):
            self.assertNotEqual(stage.default_build_directory("uart", variant), stage.default_build_directory("apb_protocol", variant))
            self.assertTrue(str(stage.default_build_directory("apb_protocol", variant)).isascii())

    def test_questa_source_and_precompiled_modes(self):
        args = regression.parser().parse_args(["--test", "uart_smoke_test"])
        build, runs = regression.plans(args, Path("/tmp/uart"), Path("/opt/uvm/src"))
        self.assertIn("mtiUvm", build[1])
        self.assertNotIn("+define+UVM_NO_DPI", build[1])
        args.compile_uvm_source = True
        build, runs = regression.plans(args, Path("/tmp/uart"), Path("/opt/uvm/src"))
        self.assertIn("+define+UVM_NO_DPI", build[1])
        self.assertNotIn("mtiUvm", build[1])
        self.assertIn("+UVM_TESTNAME=uart_smoke_test", runs[0]["command"])

    def test_vcs_has_uvm_and_seed(self):
        args = regression.parser().parse_args(["--sim", "vcs", "--seeds", "31", "--test", "uart_smoke_test"])
        build, runs = regression.plans(args, Path("/tmp/uart"), None)
        self.assertIn("uvm-1.2", build[0])
        self.assertIn("+ntb_random_seed=31", runs[0]["command"])

    def test_questa_coverage_is_instrumented_and_saved_per_run(self):
        args = regression.parser().parse_args(["--coverage", "--test", "uart_smoke_test"])
        build, runs = regression.plans(args, Path("/tmp/uart"), Path("/opt/uvm/src"))
        self.assertIn("+cover=bcesft", build[1])
        self.assertIn("-coverage", runs[0]["command"])
        self.assertIn("coverage save -onexit", runs[0]["command"][-1])

    def test_fixed_variant_selects_fixed_filelist_and_runtime_contract(self):
        for simulator in ("questa", "vcs", "verilator"):
            args = regression.parser().parse_args(["--sim", simulator, "--rtl", "fixed", "--test", "uart_smoke_test"])
            build, runs = regression.plans(args, Path("/tmp/uart"), Path("/opt/uvm/src"))
            self.assertTrue(any(part.endswith("files_fixed.f") for command in build for part in command))
            self.assertIn("+RTL_FIXED=1", runs[0]["command"])

    def test_verilator_uses_real_timing_uvm_coverage_trace_and_seed(self):
        args = regression.parser().parse_args(["--sim", "verilator", "--test", "uart_smoke_test", "--coverage", "--trace", "--seeds", "13"])
        build, runs = regression.plans(args, Path("/tmp/uart"), Path("/opt/uvm/src"))
        for flag in ("--binary", "--timing", "--assert", "--coverage", "--trace", "+define+UVM_NO_DPI", "+define+UVM_REGEX_NO_DPI"):
            self.assertIn(flag, build[0])
        self.assertIn("+verilator+seed+13", runs[0]["command"])
        self.assertTrue(any(part.startswith("+verilator+coverage+file+") for part in runs[0]["command"]))
        self.assertTrue(any(part.startswith("+VCD_FILE=") for part in runs[0]["command"]))
        self.assertTrue(runs[0]["coverage_file"].endswith("coverage.dat"))

    def test_stable_build_directory_keeps_actual_build_and_run_evidence_paths(self):
        args = regression.parser().parse_args(["--sim", "verilator", "--build-dir", "/tmp/uart-cache", "--test", "uart_smoke_test"])
        build, runs = regression.plans(args, Path("/tmp/fresh-report"), Path("/opt/uvm/src"))
        self.assertIn(str(Path("/tmp/uart-cache") / "obj_dir"), build[0])
        self.assertEqual(runs[0]["command"][0], str(Path("/tmp/uart-cache") / "Vtb_top"))
        self.assertEqual(runs[0]["directory"], str(Path("/tmp/fresh-report") / "uart_smoke_test_seed_1"))


if __name__ == "__main__":
    unittest.main()
