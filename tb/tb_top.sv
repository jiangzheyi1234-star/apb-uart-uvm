`include "uvm_macros.svh"
module tb_top;
  timeunit 1ns; timeprecision 1ps;
  import uvm_pkg::*;
  import apb_uart_pkg::*;
  logic clk=0;
  always #5ns clk=~clk;
  apb_if apb(clk);
  uart_if uart(clk);
  assign uart.rst_n=apb.rst_n;
  apb_uart_sv #(.APB_ADDR_WIDTH(12)) dut (
    .CLK(clk),.RSTN(apb.rst_n),.PADDR(apb.paddr),.PWDATA(apb.pwdata),
    .PWRITE(apb.pwrite),.PSEL(apb.psel),.PENABLE(apb.penable),
    .PRDATA(apb.prdata),.PREADY(apb.pready),.PSLVERR(apb.pslverr),
    .rx_i(uart.rx),.tx_o(uart.tx),.event_o(uart.irq)
  );
  initial begin
    apb.rst_n=0;
    repeat(8) @(negedge clk);
    apb.rst_n=1;
  end
  initial begin
    uvm_config_db#(virtual apb_if)::set(null,"uvm_test_top*","vif",apb);
    uvm_config_db#(virtual uart_if)::set(null,"uvm_test_top.env.uart*","vif",uart);
    run_test();
  end
  initial begin : waveform_capture
    string waveform_path;
    if($test$plusargs("TRACE")) begin
      if(!$value$plusargs("VCD_FILE=%s",waveform_path)) waveform_path="waves.vcd";
      $dumpfile(waveform_path);
      $dumpvars(0,tb_top);
    end
  end
  initial begin
    #10ms;
    $fatal(1,"Global timeout: UVM test did not finish");
  end
  // Failures use UVM_ERROR, so the regression parser cannot miss an assertion.
  apb_access_has_setup: assert property (@(posedge clk) disable iff(!apb.rst_n)
    apb.psel && apb.penable |-> $past(apb.psel))
    else `uvm_error("APB_PROTOCOL","Access without setup")
  apb_controls_stable: assert property (@(posedge clk) disable iff(!apb.rst_n)
    apb.psel && apb.penable |-> $stable({apb.paddr,apb.pwrite,apb.pwdata}))
    else `uvm_error("APB_PROTOCOL","Controls changed in access phase")
endmodule
