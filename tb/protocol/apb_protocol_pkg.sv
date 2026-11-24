package apb_protocol_pkg;
  timeunit 1ns;
  timeprecision 1ps;
  import uvm_pkg::*;
  `include "uvm_macros.svh"
  `include "apb_agent/apb_seq_item.sv"
  `include "apb_agent/apb_sequencer.sv"
  `include "apb_agent/apb_driver.sv"
  `include "apb_agent/apb_monitor.sv"
  `include "apb_agent/apb_agent.sv"
  `include "protocol/apb_protocol_checker.sv"
  `include "protocol/apb_protocol_tests.sv"
endpackage
