interface uart_if(input logic clk);
  timeunit 1ns;
  timeprecision 1ps;
  logic rst_n;
  logic rx = 1;
  logic tx;
  logic irq;
endinterface
