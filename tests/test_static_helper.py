"""Archive path safety checks for the optional SystemVerilog static checker."""

import importlib.util
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("uart_static_helper", ROOT / "py" / "check_sv.py")
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


class ArchiveTests(unittest.TestCase):
    def test_extracts_only_src_subtree(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "uvm.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("uvm-master/distrib/src/uvm_pkg.sv", "package uvm_pkg; endpackage")
                bundle.writestr("uvm-master/distrib/src/base/test.svh", "// source")
                bundle.writestr("uvm-master/examples/example.txt", "unused")
            destination = checker.extract_uvm_source(archive, root / "src")
            self.assertTrue((destination / "uvm_pkg.sv").is_file())
            self.assertTrue((destination / "base" / "test.svh").is_file())
            self.assertFalse((destination / "examples").exists())

    def test_rejects_parent_paths_before_writing_any_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "uvm.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("uvm/src/uvm_pkg.sv", "package uvm_pkg; endpackage")
                bundle.writestr("uvm/src/../outside.sv", "bad")
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                checker.extract_uvm_source(archive, root / "src")
            self.assertFalse((root / "src").exists())
            self.assertFalse((root / "outside.sv").exists())

    def test_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "uvm.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("uvm/src/uvm_pkg.sv", "package uvm_pkg; endpackage")
                link = zipfile.ZipInfo("uvm/src/link.svh")
                link.create_system = 3
                link.external_attr = (0o120777 << 16)
                bundle.writestr(link, "../../outside")
            with self.assertRaisesRegex(ValueError, "symlinks"):
                checker.extract_uvm_source(archive, root / "src")

    def test_rejects_ambiguous_packages(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "uvm.zip"
            with zipfile.ZipFile(archive, "w") as bundle:
                bundle.writestr("first/src/uvm_pkg.sv", "package uvm_pkg; endpackage")
                bundle.writestr("second/src/uvm_pkg.sv", "package uvm_pkg; endpackage")
            with self.assertRaisesRegex(ValueError, "one src/uvm_pkg"):
                checker.extract_uvm_source(archive, root / "src")

    def test_project_paths_become_relative_for_windows_unicode_cwd(self):
        self.assertEqual(checker.quote_arg(ROOT / "tb" / "tb_top.sv"), '"tb/tb_top.sv"')

    def test_official_tar_selects_source_over_documentation_copies(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "uvm.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                for name, content in (("uvm-1.2/src/uvm_pkg.sv", b"source"), ("uvm-1.2/docs/html/src/uvm_pkg.sv", b"documentation")):
                    info = tarfile.TarInfo(name)
                    info.size = len(content)
                    bundle.addfile(info, io.BytesIO(content))
            destination = checker.extract_uvm_tar_source(archive, root / "src")
            self.assertEqual((destination / "uvm_pkg.sv").read_bytes(), b"source")

    def test_tar_links_are_rejected_before_extraction(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "uvm.tar.gz"
            with tarfile.open(archive, "w:gz") as bundle:
                info = tarfile.TarInfo("uvm-1.2/src/uvm_pkg.sv")
                info.size = 6
                bundle.addfile(info, io.BytesIO(b"source"))
                link = tarfile.TarInfo("uvm-1.2/src/link")
                link.type = tarfile.SYMTYPE
                link.linkname = "../../outside"
                bundle.addfile(link)
            with self.assertRaisesRegex(ValueError, "links/devices"):
                checker.extract_uvm_tar_source(archive, root / "src")
            self.assertFalse((root / "src").exists())


if __name__ == "__main__":
    unittest.main()
