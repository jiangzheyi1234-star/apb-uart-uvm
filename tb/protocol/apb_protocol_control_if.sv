interface apb_protocol_control_if(input logic clk);
  timeunit 1ns;
  timeprecision 1ps;
  // The slave captures these controls during SETUP. Reprogramming them while
  // idle cannot retroactively change an already accepted request.
  int unsigned wait_cycles=0;
  bit hold_ready=0;
  bit error_response=0;
  bit poison_wait_reads=0;
endinterface
