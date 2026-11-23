#!/usr/bin/env bash
# Run all tests. Set RTL_VARIANT=upstream for the original defect demonstration.
set -euo pipefail
project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
if [[ ! -x .tools/verilator/bin/verilator ]]; then
  bash scripts/bootstrap_verilator.sh
fi
tests=(
  uart_smoke_test uart_fifo_boundary_test uart_error_test uart_reset_test
  uart_tx_overflow_test uart_rx_retention_test uart_empty_read_test
  uart_address_mirror_test uart_parity_requirement_test
  uart_framing_requirement_test uart_error_association_test
  uart_irq_test uart_irq_requirement_test uart_random_stress_test uart_baud_sweep_test
)
args=()
for test in "${tests[@]}"; do args+=(--test "$test"); done
python3 py/verify_rtl.py
python3 py/run_linux_regression.py --rtl "${RTL_VARIANT:-fixed}" \
  --build-dir "/var/tmp/apb-uart-uvm-build-${RTL_VARIANT:-fixed}" --build-timeout 1800 \
  --jobs 2 --coverage --trace --seeds 1 2 3 "${args[@]}" "$@"
