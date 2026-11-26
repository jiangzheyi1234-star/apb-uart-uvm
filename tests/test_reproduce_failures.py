"""Provenance/command safeguards for new failure executions; no RTL is run."""
import contextlib
import copy
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
sys.path.insert(0, str(ROOT / "py"))
SPEC = importlib.util.spec_from_file_location("failure_reproduction_runner", ROOT / "py/reproduce_failures.py")
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)

VCD = """$timescale 1 ns $end
$scope module tb_top $end
$scope module apb $end
$var wire 1 R rst_n $end
$upscope $end
$upscope $end
$enddefinitions $end
#0
0R
#10
1R
"""


class ReproductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases, cls.profiles = runner.archived_cases(ROOT / "docs/features", ROOT / "docs/protocol")

    def test_exact_archived_targets_and_detector_recheck(self):
        self.assertEqual(len(self.cases), 6)
        self.assertEqual([case["seed"] for case in self.cases], [1, 1, 1, 1, 2, 3])
        self.assertEqual([case["phase"] for case in self.cases], ["mutation"] * 4 + ["negative"] * 2)
        self.assertEqual(len({case["original_run_id"] for case in self.cases}), 6)

    def test_compile_normalization_allows_relocation_and_parallelism(self):
        original = self.profiles["uart"]["build"]
        changed = copy.deepcopy(original)
        old = changed["source_origin"]["staged_project_root"]
        changed["source_origin"]["staged_project_root"] = "/other/stage"
        changed["source_file_list"] = changed["source_file_list"].replace(old, "/other/stage")
        changed["source_manifest"]["uvm_source_root"] = changed["source_manifest"]["uvm_source_root"].replace(old, "/other/stage")
        command = changed["build"][0]["command"]
        command[:] = [arg.replace(old, "/other/stage") for arg in command]
        command[0] = "/different/install/verilator"
        command[command.index("-j") + 1] = "8"
        command[command.index("--Mdir") + 1] = "/other/objects"
        command[command.index("-o") + 1] = "/other/executable"
        self.assertEqual(runner.normalized_build_command(original), runner.normalized_build_command(changed))
        # Production validator and runner agree for all actually archived flags.
        import reproduced_waveforms
        self.assertEqual(runner.normalized_build_command(original), reproduced_waveforms.normalized_build_command(changed))

    def test_direct_build_infers_stage_from_pinned_filelist(self):
        original = self.profiles["uart"]["build"]
        direct = copy.deepcopy(original)
        direct.pop("source_origin")
        self.assertEqual(runner.normalized_build_command(original), runner.normalized_build_command(direct))
        direct["source_file_list"] = "/other/sim/files_fixed.f"
        with self.assertRaises(ValueError):
            runner.normalized_build_command(direct)

    def test_compile_normalization_preserves_semantic_options(self):
        original = self.profiles["uart"]["build"]
        for remove in ("--coverage", "--trace", "--timing", "+define+UVM_NO_DPI"):
            with self.subTest(remove=remove):
                changed = copy.deepcopy(original)
                changed["build"][0]["command"].remove(remove)
                self.assertNotEqual(runner.normalized_build_command(original), runner.normalized_build_command(changed))
        changed = copy.deepcopy(original)
        changed["build"][0]["returncode"] = 1
        with self.assertRaises(ValueError):
            runner.normalized_build_command(changed)

    def test_runtime_changes_only_trace_binary_and_output_destinations(self):
        for case in self.cases:
            original = case["original_row"]["command"]
            command = runner.reproduction_command(original, Path("/new/binary"), Path("/new/waves.vcd"), Path("/scratch/coverage.dat"))
            strip = lambda args: [arg for arg in args[1:] if arg != "+TRACE" and not arg.startswith(("+VCD_FILE=", "+verilator+coverage+file+"))]
            self.assertEqual(strip(command), strip(original))
            self.assertEqual(command.count("+TRACE"), 1)
            self.assertEqual([arg for arg in command if arg.startswith("+VCD_FILE=")], [f"+VCD_FILE={Path('/new/waves.vcd')}"])
        with self.assertRaises(ValueError):
            runner.reproduction_command(["binary", "+TRACE", "+TRACE"], Path("binary"), Path("waves"), Path("coverage"))

    def test_archive_tamper_and_path_escape_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / "summary.json").write_text("{}")
            content = base / "record.log"
            content.write_text("original")
            record = {"bundled_path": "record.log", "sha256": runner.digest(content), "bytes": content.stat().st_size}
            (base / "inputs.json").write_text(json.dumps([record]))
            archive = runner.Archive(base)
            self.assertEqual(archive.checked("record.log"), content)
            content.write_text("tampered")
            with self.assertRaises(ValueError):
                archive.checked("record.log")
            for escape in ("../file", "/tmp/file", "C:/file", "folder\\..\\file"):
                with self.subTest(path=escape), self.assertRaises(ValueError):
                    runner.inside(base, escape)

    def fixture_selected(self, base):
        source, uvm = base / "source", base / "uvm"
        source.mkdir()
        uvm.mkdir()
        (source / "fixture.sv").write_bytes(b"explicit unit fixture source")
        (uvm / "uvm_pkg.sv").write_bytes(b"explicit unit fixture UVM")
        snapshot = {"captured_before_compile": True, "rtl_variant": "fixed",
                    "project_files": [{"path": "fixture.sv", "sha256": runner.digest(source / "fixture.sv"), "bytes": (source / "fixture.sv").stat().st_size}],
                    "uvm_files": [{"path": "uvm_pkg.sv", "sha256": runner.digest(uvm / "uvm_pkg.sv"), "bytes": (uvm / "uvm_pkg.sv").stat().st_size}]}
        stable = {key: snapshot.get(key) for key in runner.STABLE_KEYS}
        snapshot["snapshot_sha256"] = hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()
        snapshot_path = base / "source_snapshot.json"
        snapshot_path.write_text(json.dumps(snapshot))
        binary = base / "fixture_binary"
        binary.write_bytes(b"explicit fixture executable bytes, never executed")
        build_path = base / "fixture_report.json"
        build_path.write_text("{}")
        return {"snapshot": snapshot, "snapshot_path": snapshot_path, "report_path": build_path,
                "report": {}, "source_root": source, "uvm_root": uvm, "binary": binary,
                "binary_sha256": runner.digest(binary), "binary_bytes": binary.stat().st_size,
                "binary_matches_original": False, "sidecars": []}

    def test_source_hashes_checked_and_mutation_detected(self):
        with tempfile.TemporaryDirectory() as temporary:
            selected = self.fixture_selected(Path(temporary))
            runner.verify_sources(selected["snapshot"], selected["source_root"], selected["uvm_root"])
            (selected["source_root"] / "fixture.sv").write_bytes(b"changed")
            with self.assertRaises(ValueError):
                runner.verify_sources(selected["snapshot"], selected["source_root"], selected["uvm_root"])

    def invoke_fixture(self, base, *, plan_only=False, bad_wave=False):
        selected = self.fixture_selected(base)
        output = base / "evidence"
        argv = ["--out", str(output)] + (["--plan-only"] if plan_only else [])

        def process(command, cwd, log, timeout):
            # Explicit fixture invokes no subprocess. Replay original detector
            # transcript text to exercise provenance output and classifications.
            test = next(arg.split("=", 1)[1] for arg in command if arg.startswith("+UVM_TESTNAME="))
            mode = next((arg.split("=", 1)[1] for arg in command if arg.startswith("+MUTATION=")), None)
            seed = int(next(arg.rsplit("+", 1)[1] for arg in command if arg.startswith("+verilator+seed+")))
            case = next(case for case in self.cases if (case["test"], case["mutation"], case["seed"]) == (test, mode, seed))
            text = case["original_log"].read_text(encoding="utf-8").split("\n", 1)[1]
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text("COMMAND " + json.dumps(command) + "\n" + text, encoding="utf-8")
            wave = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("+VCD_FILE=")))
            wave.write_text("invalid fixture" if bad_wave else VCD)
            return runner.regression.ProcessResult(command, 0, False, 0.01, str(log))

        with patch.object(runner, "archived_cases", return_value=(self.cases, self.profiles)), \
             patch.object(runner, "select_build", return_value=selected), \
             patch.object(runner.regression, "run_process", side_effect=process) as mocked, \
             contextlib.redirect_stdout(io.StringIO()):
            result = runner.main(argv)
        return result, output, mocked.call_count

    def test_plan_never_executes_or_claims_pass(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, output, calls = self.invoke_fixture(Path(temporary), plan_only=True)
            self.assertEqual((result, calls), (0, 0))
            index = runner.load(output / "index.json")
            self.assertEqual(index["status"], "PLANNED")
            self.assertNotIn("metrics", index)
            self.assertTrue(all("raw_status" not in entry for entry in index["entries"]))

    def test_flat_process_provenance_and_distinct_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, output, calls = self.invoke_fixture(Path(temporary))
            self.assertEqual((result, calls), (0, 6))
            index = runner.load(output / "index.json")
            self.assertEqual(index["status"], "PASS")
            for entry in index["entries"]:
                self.assertEqual((entry["raw_status"], entry["classification"]), ("FAIL", "DETECTED"))
                self.assertNotEqual(entry["reproduction_id"], entry["original_run_id"])
                self.assertTrue(entry["reproduction_id"].endswith(":" + entry["original_run_id"]))
                raw = runner.load(output / entry["raw_report_path"])
                for key in ("waveform_path", "waveform_sha256", "waveform_bytes", "binary_sha256", "source_snapshot_sha256", "command"):
                    self.assertEqual(raw[key], entry[key])
                self.assertEqual(runner.digest(output / entry["raw_report_path"]), entry["raw_report_sha256"])
            self.assertFalse(list(output.rglob("coverage.dat")))

    def test_bad_vcd_retains_raw_failure_record_but_rejects_audit(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, output, calls = self.invoke_fixture(Path(temporary), bad_wave=True)
            self.assertEqual((result, calls), (1, 6))
            index = runner.load(output / "index.json")
            self.assertEqual(index["status"], "FAIL")
            self.assertTrue(all(entry["audit_status"] == "FAIL" for entry in index["entries"]))
            self.assertTrue(all((output / entry["raw_report_path"]).is_file() for entry in index["entries"]))

    def test_existing_evidence_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            (base / "keep.log").write_text("retain")
            with patch.object(runner.regression, "run_process") as process, contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(runner.main(["--out", str(base)]), 2)
                process.assert_not_called()
            self.assertEqual((base / "keep.log").read_text(), "retain")


if __name__ == "__main__":
    unittest.main()
