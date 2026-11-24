"""Distribution boundaries, audit manifests and offline overlay navigation."""

import hashlib
from html.parser import HTMLParser
import importlib.util
from pathlib import Path
import tempfile
import unittest
from urllib.parse import unquote, urlsplit
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("uart_packaging", ROOT / "py" / "package_project.py")
packaging = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(packaging)


class LocalLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.targets = []

    def handle_starttag(self, tag, attributes):
        for name, value in attributes:
            if name in ("href", "src") and value:
                parsed = urlsplit(value)
                if not parsed.scheme and not parsed.netloc and parsed.path:
                    self.targets.append(unquote(parsed.path))


class PackagingTests(unittest.TestCase):
    def write(self, root, relative, content="fixture\n"):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def fixture(self, root):
        for name in (
            "README.md", "README.en.md", "LICENSE", "NOTICE.md", "CONTRIBUTING.md",
            "CHANGELOG.md", "RELEASE.md", "rtl/uart.sv", "rtl_fixed/uart.sv",
            "tb/ral/README.md", "sim/files.f", "py/run.py", "tests/test_example.py",
            "scripts/bootstrap.sh", "third_party/manifest.json", ".github/workflows/verification.yml",
            "docs/README.md", "docs/architecture.md", "docs/registers.md",
            "docs/release/inputs/run.log", "docs/release/inputs/coverage.dat",
            "docs/features/plot.svg", "docs/ci/acceptance.json",
        ):
            self.write(root, name)
        self.write(root, "docs/.nojekyll", "")
        self.write(root, "docs/index.html", '<a href="release/index.html">core</a><a href="features/index.html">features</a><a href="README.md">source guide</a>')
        self.write(root, "docs/release/index.html", '<a href="inputs/run.log">log</a><a href="../../README.md">source</a>')
        self.write(root, "docs/features/index.html", '<img src="plot.svg"><a href="../ci/acceptance.json">CI</a>')
        for name in (
            "docs/interview_guide.md", "docs/guangzhou_interview.md", "docs/industry_benchmark.md",
            "docs/optimization_rounds.md", "docs/resume.md", "docs/求职说明.md",
            "docs/evidence/index.html", "docs/evidence/inputs/old.log",
            "tb/guangzhou_interview.md", "docs/features/interview_notes.md",
            "tb/interview_notes/notes.md", "docs/features/career_materials/notes.md",
            "docs/release/career.md", "docs/release/.private/personal.md",
            ".private/material.md", "tb/.private/private.md", "scripts/personal/notes.md",
            "sim/simulation.log", "sim/waves.vcd", "sim/coverage.dat", "sim/work/generated.sv",
            "rtl/build/generated.sv", "rtl/.tools/downloaded.sv", "py/__pycache__/old.pyc",
            "results/report.json", "dist/old.zip",
        ):
            self.write(root, name)

    def assert_manifest(self, archive_path, manifest_name):
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            self.assertEqual(len(names), len(set(names)))
            self.assertIsNone(archive.testzip())
            records = {}
            for line in archive.read(manifest_name).decode("utf-8").splitlines():
                checksum, name = line.split("  ", 1)
                self.assertNotIn(name, records)
                records[name] = checksum
            self.assertEqual(set(records), set(names) - {manifest_name})
            for name, checksum in records.items():
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), checksum)
            return set(names)

    def test_source_excludes_evidence_career_private_and_generated_material(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            output = root / "dist/source.zip"
            result = packaging.package_project(root, output)
            names = self.assert_manifest(output, "MANIFEST.source.sha256")
            self.assertEqual(result["profile"], "source")
            self.assertTrue({"rtl/uart.sv", "tb/ral/README.md", "tests/test_example.py",
                             "docs/README.md", "docs/architecture.md", "docs/registers.md",
                             "RELEASE.md", "CHANGELOG.md"}.issubset(names))
            self.assertFalse(any(name.startswith(("docs/release/", "docs/features/", "docs/ci/", "docs/evidence/")) for name in names))
            self.assertNotIn("docs/index.html", names)
            self.assertNotIn("docs/.nojekyll", names)
            self.assertFalse(any(word in name.lower() for name in names for word in ("interview", "resume", "career", "private", "optimization_round", "industry_benchmark")))
            self.assertFalse(any(name.endswith((".log", ".vcd", ".dat", ".pyc")) for name in names))
            self.assertNotIn("sim/work/generated.sv", names)
            self.assertNotIn("rtl/build/generated.sv", names)
            self.assertNotIn("rtl/.tools/downloaded.sv", names)

    def test_evidence_has_current_records_but_no_source_or_career_material(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            output = root / "dist/evidence.zip"
            packaging.package_project(root, output, "evidence")
            names = self.assert_manifest(output, "MANIFEST.evidence.sha256")
            self.assertTrue({"docs/index.html", "docs/.nojekyll", "docs/release/inputs/run.log",
                             "docs/release/inputs/coverage.dat", "docs/features/plot.svg",
                             "docs/ci/acceptance.json", "LICENSE"}.issubset(names))
            self.assertFalse(any(name.startswith(("rtl/", "rtl_fixed/", "tb/", "sim/", "py/", "tests/", "docs/evidence/")) for name in names))
            self.assertNotIn("README.md", names)
            self.assertNotIn("docs/README.md", names)
            self.assertFalse(any(word in name.lower() for name in names for word in ("interview", "career", "private")))

    def test_overlay_retains_both_manifests_and_local_evidence_navigation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            self.fixture(root)
            source, evidence = root / "dist/source.zip", root / "dist/evidence.zip"
            packaging.package_project(root, source, "source")
            packaging.package_project(root, evidence, "evidence")
            delivery = Path(temporary) / "delivery"
            for output in (source, evidence):
                with zipfile.ZipFile(output) as archive:
                    archive.extractall(delivery)
            self.assertTrue((delivery / "MANIFEST.source.sha256").is_file())
            self.assertTrue((delivery / "MANIFEST.evidence.sha256").is_file())
            for name in ("docs/index.html", "docs/release/index.html", "docs/features/index.html"):
                page = delivery / name
                parser = LocalLinks()
                parser.feed(page.read_text(encoding="utf-8"))
                self.assertGreater(len(parser.targets), 0)
                for target in parser.targets:
                    with self.subTest(page=name, target=target):
                        self.assertTrue((page.parent / target).resolve().is_file())

    def test_source_archives_are_byte_reproducible(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            first, second = root / "dist/first.zip", root / "dist/second.zip"
            packaging.package_project(root, first)
            packaging.package_project(root, second)
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_symlinks_cannot_import_external_or_private_content(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            external = Path(temporary) / "external"
            self.fixture(root)
            secret = self.write(external, "secret.sv")
            try:
                (root / "tb/linked_directory").symlink_to(external, target_is_directory=True)
                (root / "rtl/linked_file.sv").symlink_to(secret)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"Symlink creation is unavailable: {error}")
            names = {path.relative_to(root).as_posix() for path in packaging.collect_files(root, root / "dist/source.zip")}
            self.assertFalse(any("linked_" in name for name in names))

    def test_linked_docs_ancestor_cannot_bypass_explicit_document_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "project"
            self.write(root, "README.md")
            actual = root / "actual_docs"
            self.write(actual, "registers.md")
            try:
                (root / "docs").symlink_to(actual, target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                self.skipTest(f"Symlink creation is unavailable: {error}")
            names = {path.relative_to(root).as_posix() for path in packaging.collect_files(root, root / "dist/source.zip")}
            self.assertNotIn("docs/registers.md", names)

    def test_unknown_profile_and_non_zip_outputs_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.fixture(root)
            with self.assertRaises(ValueError):
                packaging.collect_files(root, root / "out.zip", "combined")
            with self.assertRaises(ValueError):
                packaging.package_project(root, root / "README.md")


if __name__ == "__main__":
    unittest.main()
