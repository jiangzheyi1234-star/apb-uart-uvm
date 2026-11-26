"""Focused ECO safety checks; explicit small fixtures, no RTL result claims."""
from pathlib import Path
import tempfile
import unittest

from hold_repair import first_path, instances, measure_sta, repair_netlist

NETLIST = """module apb_ram_mbist(CLK,RSTN,PWRITE);
input CLK,RSTN,PWRITE;
wire apb_read_pending_q,qbar,nand_out,decode,old_d,other;
DFFR_X1 pending_flop (.CK(CLK),.D(old_d),.Q(apb_read_pending_q),.QN(qbar),.RN(RSTN));
NAND2_X1 reset_feedback (.A1(RSTN),.A2(qbar),.ZN(nand_out));
NOR4_X1 next_state (.A1(PWRITE),.A2(apb_read_pending_q),.A3(decode),.A4(nand_out),.ZN(old_d));
INV_X1 unrelated (.A(decode),.ZN(other));
endmodule
"""

MIN_PATH = """Startpoint: pending_flop (flip-flop)
Endpoint: pending_flop (flip-flop)
Path Type: min
 0.00000 0.00000 ^ pending_flop/CK (DFFR_X1)
 0.06745 0.06745 v pending_flop/QN (DFFR_X1)
 0.01868 0.08613 ^ reset_feedback/ZN (NAND2_X1)
 0.01019 0.09633 v next_state/ZN (NOR4_X1)
 0.00000 0.09633 v pending_flop/D (DFFR_X1)
 0.09633 data arrival time
 0.10268 data required time
 -0.00636 slack (VIOLATED)
"""

MAX_PATH = """Startpoint: PWRITE (input)
Endpoint: other (output)
Path Type: max
 3.01940 data arrival time
 7.90000 data required time
 4.88060 slack (MET)
"""

STA = ("=== MAX PATHS ===\n" + MAX_PATH + "=== MIN PATHS ===\n" + MIN_PATH
       + "=== WORST SLACKS ===\nworst slack max 4.88060\nworst slack min -0.00636\nFRONTEND_STA_COMPLETE\n")


class HoldRepairTests(unittest.TestCase):
    def repair(self, text=NETLIST, timing=STA):
        with tempfile.TemporaryDirectory() as temporary:
            source, target = Path(temporary) / "old.v", Path(temporary) / "new.v"
            source.write_text(text)
            result = repair_netlist(source, target, timing)
            return result, target.read_text()

    def test_unique_logical_register_and_single_pin_delta(self):
        result, text = self.repair()
        self.assertEqual(result["target_instance"], "pending_flop")
        self.assertEqual(result["cell_count_after"], result["cell_count_before"] + 1)
        self.assertEqual(result["baseline_target_path"]["slack_ns"], -0.00636)
        before, after = instances(NETLIST), instances(text)
        self.assertEqual(after["unrelated"]["pins"], before["unrelated"]["pins"])
        self.assertEqual(after["pending_flop"]["pins"], {**before["pending_flop"]["pins"], "D": result["new_net"]})
        self.assertEqual(after[result["buffer_instance"]]["pins"], {"A": "old_d", "Z": result["new_net"]})

    def test_rejects_changed_clock_reset_feedback_and_extra_consumer(self):
        for changed in (NETLIST.replace(".CK(CLK)", ".CK(other_clock)"),
                        NETLIST.replace(".RN(RSTN)", ".RN(other_reset)"),
                        NETLIST.replace(".A1(RSTN)", ".A1(PWRITE)"),
                        NETLIST.replace(".A(decode)", ".A(old_d)"),
                        NETLIST.replace(".ZN(old_d)", ".ZN(other)")):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.repair(changed)

    def test_rejects_duplicate_target_and_identifier_collision(self):
        duplicate = NETLIST.replace("endmodule", "DFFR_X1 duplicate (.CK(CLK),.D(old_d),.Q(apb_read_pending_q),.QN(other),.RN(RSTN));\nendmodule")
        for changed in (duplicate, NETLIST.replace("endmodule", "wire hold_eco_apb_read_pending_d_net;\nendmodule")):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.repair(changed)

    def test_requires_actual_negative_worst_path_at_the_guarded_endpoint(self):
        for changed in (STA.replace("-0.00636 slack (VIOLATED)", "0.00636 slack (MET)"),
                        STA.replace("Endpoint: pending_flop", "Endpoint: unrelated_flop"),
                        STA.replace("reset_feedback/ZN", "other_gate/ZN")):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.repair(timing=changed)

    def test_does_not_reapply_an_existing_repair(self):
        _, repaired = self.repair()
        with self.assertRaises(ValueError):
            self.repair(repaired)

    def test_reports_actual_global_failure_and_checks_path_consistency(self):
        actual = measure_sta(STA)
        self.assertEqual(actual["status"], "VIOLATED")
        self.assertEqual(actual["hold_worst_slack_ns"], -0.00636)
        for changed in (STA.replace("worst slack min -0.00636", "worst slack min 0.00000"),
                        STA.replace("FRONTEND_STA_COMPLETE", ""), "Error: invalid\n" + STA):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                measure_sta(changed)
        self.assertEqual(first_path(STA, "MIN PATHS")["arrival_ns"], .09633)


if __name__ == "__main__":
    unittest.main()
