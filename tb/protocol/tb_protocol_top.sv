`include "uvm_macros.svh"
module tb_top;
  timeunit 1ns;
  timeprecision 1ps;
  import uvm_pkg::*;
  import apb_protocol_pkg::*;
  logic clk=0;
  always #5ns clk=~clk;
  apb_if apb(clk);
  apb_protocol_control_if control(clk);
  apb_programmable_slave peripheral(apb,control);

  initial begin
    apb.rst_n=0;
    repeat(8) @(negedge clk);
    apb.rst_n=1;
  end
  initial begin
    uvm_config_db#(virtual apb_if)::set(null,"uvm_test_top*","vif",apb);
    uvm_config_db#(virtual apb_protocol_control_if)::set(null,"uvm_test_top*","control_vif",control);
    run_test();
  end
  initial begin : waveform_capture
    string waveform_path;
    if($test$plusargs("TRACE")) begin
      if(!$value$plusargs("VCD_FILE=%s",waveform_path)) waveform_path="protocol.vcd";
      $dumpfile(waveform_path);
      $dumpvars(0,tb_top);
    end
  end
  initial begin
    #1ms;
    $fatal(1,"APB protocol suite global timeout");
  end
endmodule
