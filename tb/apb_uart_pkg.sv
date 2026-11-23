package apb_uart_pkg;
  timeunit 1ns; timeprecision 1ps;
  import uvm_pkg::*;
  `include "uvm_macros.svh"
  `uvm_analysis_imp_decl(_apb)
  `uvm_analysis_imp_decl(_tx)
  `uvm_analysis_imp_decl(_rx)
  `uvm_analysis_imp_decl(_cov_apb)
  `uvm_analysis_imp_decl(_cov_tx)
  `uvm_analysis_imp_decl(_cov_rx)
  `include "apb_agent/apb_seq_item.sv"
  `include "apb_agent/apb_sequencer.sv"
  `include "apb_agent/apb_driver.sv"
  `include "apb_agent/apb_monitor.sv"
  `include "apb_agent/apb_agent.sv"
  `include "uart_agent/uart_config.sv"
  `include "uart_agent/uart_seq_item.sv"
  `include "uart_agent/uart_sequencer.sv"
  `include "uart_agent/uart_driver.sv"
  `include "uart_agent/uart_monitor.sv"
  `include "uart_agent/uart_agent.sv"
  `include "scoreboard/apb_uart_scoreboard.sv"
  `include "coverage/apb_uart_coverage.sv"
  `include "env/apb_uart_env.sv"
  `include "seq/base_seq.sv"
  `include "test/base_test.sv"
  `include "test/uart_tests.sv"
  `include "test/uart_extended_tests.sv"
  `include "ral/uart_apb_reg_adapter.sv"
  `include "ral/uart_dlab_frontdoor.sv"
  `include "ral/uart_reg_block.sv"
  `include "ral/uart_bank_predictor.sv"
  `include "test/uart_ral_test.sv"
endpackage
