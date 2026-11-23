"""Deterministic subprocess fixture, never a substitute for RTL simulation."""

import argparse
from pathlib import Path
import time

p = argparse.ArgumentParser()
p.add_argument("operation", choices=("compile", "simulate"))
p.add_argument("--calls", type=Path, required=True)
p.add_argument("--test", default="uart_smoke_test")
p.add_argument("--seed", type=int, default=1)
p.add_argument("--result", default="pass", choices=("pass", "fail", "truncated", "timeout", "build_fail"))
args = p.parse_args()
with args.calls.open("a", encoding="utf-8") as calls:
    calls.write(f"{args.operation} {args.test} {args.seed}\n")
if args.result == "timeout":
    time.sleep(30)
if args.operation == "compile":
    if args.result == "build_fail":
        print("Error-[SYNTAX] Fixture compile failure")
        raise SystemExit(1)
    print("Fixture compile succeeded")
else:
    print("UVM_INFO @ 100 [UART_UVM_TEST_PASS] Fixture scoreboard drained")
    if args.result != "truncated":
        if args.result == "fail":
            print("UVM_ERROR @ 110 [COMPARE] Fixture data mismatch")
        print("--- UVM Report Summary ---")
        print("UVM_INFO : 10")
        print("UVM_WARNING : 0")
        print(f"UVM_ERROR : {1 if args.result == 'fail' else 0}")
        print("UVM_FATAL : 0")
