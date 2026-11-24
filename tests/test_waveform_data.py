"""Trace semantics that matter when debugging bus reads and reset aborts."""

import importlib.util
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("waveform_data", Path(__file__).resolve().parents[1] / "py/waveform_data.py")
wave = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wave)


HEADER = """$timescale
  1 ns
$end
$scope module tb_top $end
$scope module apb $end
$var wire 1 C clk $end
$var wire 1 R rst_n $end
$var wire 1 S psel $end
$var wire 1 E penable $end
$var wire 1 Y pready $end
$var wire 1 W pwrite $end
$var wire 12 A paddr [11:0] $end
$var wire 32 D pwdata [31:0] $end
$var wire 32 Q prdata [31:0] $end
$var wire 1 X pslverr $end
$upscope $end
$upscope $end
$enddefinitions $end
"""


class WaveformTests(unittest.TestCase):
    def parse(self, content):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "trace.vcd"
            p.write_text(content, encoding="utf-8")
            return wave.read_interface_vcd(p)

    def test_read_response_uses_pre_edge_value_and_actual_wait_cycles(self):
        trace = self.parse(HEADER + """#0
0C
1R
0S
0E
0Y
0W
0X
b1 A
b0 D
b10101010 Q
#2
1S
#5
1C
#10
0C
1E
#15
1C
#20
0C
#25
1C
#30
0C
1Y
1X
#35
1C
b10111011 Q
#40
0C
0S
0E
""")
        event, = wave.apb_transactions(trace["signals"])
        self.assertEqual(event["read_data"], "0x000000AA")
        self.assertEqual(event["wait_cycles"], 2)
        self.assertEqual(event["status"], "SLVERR")
        self.assertEqual((event["start"], event["end"]), (5, 35))

    def test_reset_aborts_pending_transfer_instead_of_creating_completion(self):
        trace = self.parse(HEADER + """#0
0C
1R
0S
0E
0Y
1W
0X
b11 A
b10000011 D
b0 Q
#2
1S
#5
1C
#10
0C
1E
#15
1C
#17
0R
0S
0E
#20
0C
#25
1C
""")
        event, = wave.apb_transactions(trace["signals"])
        self.assertEqual(event["status"], "RESET_ABORT")
        self.assertEqual(event["end"], 17)
        self.assertIsNone(event["read_data"])
        self.assertEqual(event["wait_cycles"], 1)

    def test_timescale_and_unknown_vector_bits_are_preserved(self):
        trace = self.parse(HEADER.replace("1 ns", "10 ps") + "#0\n0C\n0R\nbx A\nbz D\n#100\n1C\n")
        self.assertEqual(trace["range"], [0, 1])
        self.assertEqual(trace["signals"]["apb.paddr"]["events"][0][1], "x" * 12)
        self.assertEqual(trace["signals"]["apb.pwdata"]["events"][0][1], "z" * 32)

    def test_missing_scale_and_backwards_time_do_not_produce_invented_trace(self):
        for text in (HEADER.replace("$timescale\n  1 ns\n$end\n", "") + "#0\n0C\n",
                     HEADER + "#10\n0C\n#5\n1C\n"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    self.parse(text)


if __name__ == "__main__":
    unittest.main()
