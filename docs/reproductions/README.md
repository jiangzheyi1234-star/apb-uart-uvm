# Failure waveform reproductions

Reproduction audit: **PASS**

Original archived FAIL records remain unchanged. These are new executions with tracing enabled.
DETECTED records the expected checker firing. The simulator result stays FAIL.

| Original run | Raw status | Classification | Binary SHA-256 matches original | Log | VCD |
| --- | --- | --- | --- | --- | --- |
| fault_control:mutation:uart_smoke_test:tx_data_xor:1 | FAIL | DETECTED | True | runs/00_tx_data_xor_seed_1/simulation.log | runs/00_tx_data_xor_seed_1/waves.vcd |
| fault_control:mutation:uart_smoke_test:rx_data_xor:1 | FAIL | DETECTED | True | runs/01_rx_data_xor_seed_1/simulation.log | runs/01_rx_data_xor_seed_1/waves.vcd |
| fault_control:mutation:uart_parity_requirement_test:parity_mask:1 | FAIL | DETECTED | True | runs/02_parity_mask_seed_1/simulation.log | runs/02_parity_mask_seed_1/waves.vcd |
| fault_control:mutation:uart_irq_requirement_test:irq_stuck_low:1 | FAIL | DETECTED | True | runs/03_irq_stuck_low_seed_1/simulation.log | runs/03_irq_stuck_low_seed_1/waves.vcd |
| apb_protocol:negative:apb_timeout_requirement_test:2 | FAIL | DETECTED | True | runs/04_apb_timeout_requirement_test_seed_2/simulation.log | runs/04_apb_timeout_requirement_test_seed_2/waves.vcd |
| apb_protocol:negative:apb_timeout_requirement_test:3 | FAIL | DETECTED | True | runs/05_apb_timeout_requirement_test_seed_3/simulation.log | runs/05_apb_timeout_requirement_test_seed_3/waves.vcd |
