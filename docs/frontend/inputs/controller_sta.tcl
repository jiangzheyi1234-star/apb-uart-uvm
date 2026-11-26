# Environment variables are supplied by scripts/frontend/run_flow.py.
read_liberty $::env(FRONTEND_LIBERTY)
read_verilog $::env(FRONTEND_NETLIST)
link_design apb_ram_mbist
read_sdc $::env(FRONTEND_SDC)
puts "=== CONSTRAINT AUDIT ==="
check_setup -verbose
puts "=== MAX PATHS ==="
report_checks -path_delay max -group_path_count 10 -format full_clock_expanded -digits 5
puts "=== MIN PATHS ==="
report_checks -path_delay min -group_path_count 10 -format full_clock_expanded -digits 5
puts "=== WORST SLACKS ==="
report_worst_slack -max -digits 5
report_worst_slack -min -digits 5
report_tns
puts "FRONTEND_STA_COMPLETE"
exit
