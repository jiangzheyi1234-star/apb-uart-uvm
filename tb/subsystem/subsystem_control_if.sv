// Testbench controls are kept outside the production APB/RAM interface.
interface subsystem_control_if(input logic clk);
  timeunit 1ns;
  timeprecision 1ps;
  logic fault_enable = 0;
  wire ram_en;
  wire ram_we;
  wire [5:0] ram_addr;
endinterface
