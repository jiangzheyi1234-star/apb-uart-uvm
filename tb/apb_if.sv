interface apb_if(input logic clk);
  timeunit 1ns;
  timeprecision 1ps;
  logic rst_n;
  logic psel = 0;
  logic penable = 0;
  logic pwrite = 0;
  logic [11:0] paddr = '0;
  logic [31:0] pwdata = '0;
  logic [31:0] prdata;
  logic pready;
  logic pslverr;
endinterface
