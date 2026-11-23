"""Verify native bin decoding, exclusions and measured coverage accounting."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("uart_coverage_report", ROOT / "py" / "report_coverage.py")
coverage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(coverage)


def native_record(attributes, hits):
    return "C '" + "".join("\x01" + key + "\x02" + str(value) for key, value in attributes.items()) + f"' {hits}\n"


class NativeCoverageTests(unittest.TestCase):
    def test_eligible_bins_use_threshold_and_exclude_noncoverage_bins(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            database = directory / "coverage.dat"
            text = "# SystemC::Coverage-3\n"
            base = {"f": "tb/coverage/apb_uart_coverage.sv", "l": 15, "h": "TOP.cg", "o": "payload", "t": "covergroup"}
            text += native_record(dict(base, B="zero", s=1), 5)
            text += native_record(dict(base, B="ones", s=3), 2)
            for kind in ("default", "ignore", "illegal"):
                text += native_record(dict(base, B=kind, Bt=kind), 0)
            text += native_record(dict(base, B="disabled", w=0), 0)
            text += native_record({"f": "rtl_fixed/uart_tx.sv", "l": 10, "t": "line"}, 9)
            text += native_record({"f": "rtl_fixed/uart_tx.sv", "l": 15, "t": "line"}, 0)
            database.write_text(text, encoding="utf-8")
            summary = coverage.generate_report(database, directory / "report")
            functional = summary["functional"]
            self.assertEqual((functional["bins_hit"], functional["bins_total"]), (1, 2))
            self.assertEqual(functional["bin_hit_percent"], 50.0)
            self.assertEqual(len(functional["excluded_bins"]), 4)
            self.assertEqual(functional["uncovered_bins"][0]["name"], "ones")
            self.assertEqual(summary["code_points"]["by_source_scope_and_type"]["rtl/line"]["points_seen"], 1)
            self.assertEqual(json.loads((directory / "report" / "coverage_summary.json").read_text(encoding="utf-8"))["record_count"], 8)

    def test_decodes_percent_escaped_values_after_splitting_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "coverage.dat"
            database.write_text(native_record({"f": "tb/test.sv", "B": "bin%25name%22quoted", "h": "group"}, 1), encoding="utf-8")
            attributes = coverage.parse_records(database)[0]["attributes"]
            self.assertEqual(attributes["bin"], 'bin%name"quoted')

    def test_no_functional_bins_is_not_100_percent(self):
        summary = coverage.native_summary([{"attributes": {"filename": "rtl/uart.sv", "type": "line"}, "hits": 1}])
        self.assertEqual(summary["functional"]["status"], "NO_FUNCTIONAL_BIN_RECORDS")
        self.assertIsNone(summary["functional"]["bin_hit_percent"])

    def test_real_native_hierarchies_group_bins_by_coverpoint_and_cross(self):
        records = []
        hierarchy = "apb_uart_pkg::apb_uart_coverage::bus_cg.access"
        for name, hits in (("<auto_0,registers[0],auto_0>", 4), ("<auto_1,registers[0],auto_0>", 0)):
            records.append({"attributes": {"filename": "tb/coverage/apb_uart_coverage.sv", "lineno": "18",
                                            "hier": hierarchy + "." + name, "bin": name, "cross": "1"}, "hits": hits})
        summary = coverage.native_summary(records)["functional"]
        self.assertEqual(len(summary["by_point"]), 1)
        point, counts = next(iter(summary["by_point"].items()))
        self.assertTrue(point.endswith(hierarchy))
        self.assertEqual(counts, {"bins_hit": 1, "bins_total": 2, "bin_hit_percent": 50.0})
        self.assertEqual(summary["bins_total"], 2)
        self.assertEqual(summary["all_bins"][0]["hierarchy"], hierarchy + ".<auto_0,registers[0],auto_0>")

    def test_bin_suffix_removal_is_verified_and_preserves_dots_in_bin_names(self):
        self.assertEqual(coverage.point_hierarchy("frame_cg.baud_format.<one,1.5>", "<one,1.5>"), "frame_cg.baud_format")
        self.assertEqual(coverage.point_hierarchy("frame_cg.payload.auto_1", "auto_0"), "frame_cg.payload.auto_1")
        self.assertEqual(coverage.point_hierarchy("frame_cg.payload", ""), "frame_cg.payload")

    def test_malformed_and_empty_data_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "coverage.dat"
            for text in ("# SystemC::Coverage-3\n", "not coverage data\n", "C 'missing_fields' 10\n"):
                database.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    coverage.parse_records(database)

    def test_lcov_is_scoped_and_separate_from_functional_bins(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "coverage.info"
            path.write_text("SF:/workspace/rtl_fixed/uart.sv\nDA:10,7\nDA:20,0\nBRDA:10,0,0,1\nBRDA:10,0,1,-\nend_of_record\nSF:/tools/uvm/src/pkg.sv\nDA:10,1\nend_of_record\n", encoding="utf-8")
            summary = coverage.lcov_summary(path)
            self.assertEqual(summary["source_scopes"]["rtl"]["line_percent"], 50.0)
            self.assertEqual(summary["source_scopes"]["rtl"]["branch_percent"], 50.0)
            self.assertEqual(summary["source_scopes"]["library_or_external"]["lines_total"], 1)


if __name__ == "__main__":
    unittest.main()
