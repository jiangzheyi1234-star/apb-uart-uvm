"""Exercise the portable importer without a simulator or the UART evidence tree."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "py/workbench.py"


class PortableWorkbenchTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.demo = self.root / "计数器 input"
        self.site = self.root / "review site"

    def run_cli(self, *args, expected=0):
        result = subprocess.run([sys.executable, str(CLI), *map(str, args)],
                                capture_output=True, encoding="utf-8", errors="replace",
                                cwd=self.root, env={**os.environ, "PYTHONUTF8": "1"}, check=False)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def make_demo(self):
        self.run_cli("init", "--out", self.demo)
        path = self.demo / "manifest.json"
        return path, json.loads(path.read_bytes())

    def test_manifest_links_exact_run_and_selected_wave_to_copied_bytes(self):
        path, manifest = self.make_demo()
        original = self.demo / "overflow.txt"
        original.rename(self.demo / "失败 #11.txt")
        manifest["runs"][1]["log"] = "失败 #11.txt"
        (self.demo / "unlisted.txt").write_text("unlisted", encoding="utf-8")
        manifest["project"]["title"] = "Counter <bench>"
        manifest["verification_plan"]["groups"][0]["items"][1]["checks"][0]["tests"].append("unexecuted")
        path.write_text(json.dumps(manifest), encoding="utf-8")
        self.run_cli("build", path, "--out", self.site)
        data = json.loads((self.site / "data/dashboard.json").read_bytes())
        failed = data["runs"][1]
        self.assertEqual((failed["id"], failed["seed"], failed["raw_status"]), ("overflow:11", 11, "FAIL"))
        self.assertEqual(failed["log_url"], "evidence/%E5%A4%B1%E8%B4%A5%20%2311.txt")
        point = data["verification_plan"]["groups"][0]["items"][1]
        self.assertEqual(point["run_ids"], [failed["id"]])
        self.assertEqual(point["binding_status"], "partial")
        self.assertEqual(point["checks"][0]["missing_tests"], ["unexecuted"])
        self.assertEqual(len(data["inputs"]), 3)
        wave = data["waveforms"][0]
        self.assertEqual(wave["run_id"], failed["id"])
        self.assertEqual(wave["signals"][0]["events"], [[0, "00"], [5, "11"]])
        self.assertEqual(wave["source"]["sha256"], hashlib.sha256((self.demo / "overflow.vcd").read_bytes()).hexdigest())
        for evidence in data["inputs"]:
            archive = (self.site / evidence["path"]).read_bytes()
            self.assertEqual(evidence["sha256"], hashlib.sha256(archive).hexdigest())
            self.assertEqual(evidence["bytes"], len(archive))
        self.assertFalse((self.site / "evidence/unlisted.txt").exists())
        html = (self.site / "index.html").read_text(encoding="utf-8")
        self.assertIn("Counter &lt;bench&gt;", html)
        self.assertNotIn("APB UART", html)
        self.assertNotIn("echarts.min.js", html)

    def test_junit_preserves_raw_results_and_archives_report_once(self):
        report = self.root / "project report.xml"
        report.write_text(
            '<testsuites><testsuite name="FIFO" failures="1"><testcase classname="fifo" name="push"/>'
            '<testcase name="pop"><failure message="expected valid"/></testcase>'
            '<testcase name="setup"><error/></testcase><testcase name="skip"><skipped/></testcase>'
            '</testsuite></testsuites>', encoding="utf-8")
        self.run_cli("build", "--junit", report, "--title", "FIFO Verification", "--out", self.site)
        data = json.loads((self.site / "data/dashboard.json").read_bytes())
        self.assertEqual(data["project"]["title"], "FIFO Verification")
        self.assertEqual(data["runs"][0]["test"], "fifo.push")
        self.assertEqual([row["raw_status"] for row in data["runs"]], ["PASS", "FAIL", "ERROR", "SKIP"])
        self.assertTrue(all(row["seed"] is None for row in data["runs"]))
        self.assertEqual(data["runs"][1]["failure_excerpt"], ["expected valid"])
        self.assertEqual({row["report_url"] for row in data["runs"]}, {"evidence/project%20report.xml"})
        self.assertEqual(len(data["inputs"]), 1)
        self.assertEqual((self.site / "evidence/project report.xml").read_bytes(), report.read_bytes())

    def test_invalid_artifact_selection_leaves_no_partial_site(self):
        path, manifest = self.make_demo()
        bad = manifest["runs"][1]
        for field, value, message in (
            ("id", manifest["runs"][0]["id"], "Duplicate run ID"),
            ("log", "../outside.txt", "relative to the manifest"),
            ("log", "missing.txt", "Artifact file is missing"),
            ("signals", ["wrong.count"], "Selected VCD signals have no samples"),
            ("raw_status", "UNKNOWN", "Unsupported status"),
        ):
            with self.subTest(field=field, value=value):
                original = bad[field]
                bad[field] = value
                path.write_text(json.dumps(manifest), encoding="utf-8")
                result = self.run_cli("build", path, "--out", self.site, expected=1)
                self.assertIn(message, result.stderr)
                self.assertFalse(self.site.exists())
                bad[field] = original

        bad.pop("signals")
        path.write_text(json.dumps(manifest), encoding="utf-8")
        self.run_cli("build", path, "--out", self.site)
        data = json.loads((self.site / "data/dashboard.json").read_bytes())
        self.assertFalse(data["waveforms"])
        self.assertEqual(data["runs"][1]["vcd_url"], "evidence/overflow.vcd")
        again = self.run_cli("build", path, "--out", self.site, expected=1)
        self.assertIn("Output directory already exists", again.stderr)
        self.assertTrue((self.site / "evidence/overflow.vcd").is_file())


if __name__ == "__main__":
    unittest.main()
