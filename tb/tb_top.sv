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
  // Optional negative controls exercise the real checking paths. With no
  // MUTATION plusarg all connections are transparent; vendored RTL is intact.
  string mutation_mode="";
  bit mutate_tx_data,mutate_rx_data,mutate_parity,mutate_irq;
  logic observed_dlab;
  logic [31:0] dut_pwdata,dut_prdata;
  logic dut_irq;
  initial begin : mutation_control
    if($value$plusargs("MUTATION=%s",mutation_mode)) begin
      case(mutation_mode)
        "tx_data_xor": mutate_tx_data=1;
        "rx_data_xor": mutate_rx_data=1;
        "parity_mask": mutate_parity=1;
        "irq_stuck_low": mutate_irq=1;
        default: `uvm_fatal("UNKNOWN_MUTATION",$sformatf("Unknown mutation %s",mutation_mode))
      endcase
      `uvm_info("MUTATION_ACTIVE",mutation_mode,UVM_NONE)
    end
  end
  always_ff @(posedge clk or negedge apb.rst_n) begin
    if(!apb.rst_n) observed_dlab<=0;
    else if(apb.psel && apb.penable && apb.pready && apb.pwrite && apb.paddr[2:0]==3)
      observed_dlab<=apb.pwdata[7];
  end
  always_comb begin
    dut_pwdata=apb.pwdata;
    if(mutate_tx_data && apb.pwrite && apb.paddr[2:0]==0 && !observed_dlab)
      dut_pwdata[0]=~apb.pwdata[0];
    apb.prdata=dut_prdata;
    if(mutate_rx_data && !apb.pwrite && apb.paddr[2:0]==0 && !observed_dlab)
      apb.prdata[0]=~dut_prdata[0];
    if(mutate_parity && !apb.pwrite && apb.paddr[2:0]==5)
      apb.prdata[2]=0;
  end
  assign uart.irq=mutate_irq?1'b0:dut_irq;
  apb_uart_sv #(.APB_ADDR_WIDTH(12)) dut (
    .CLK(clk),.RSTN(apb.rst_n),.PADDR(apb.paddr),.PWDATA(dut_pwdata),
    .PWRITE(apb.pwrite),.PSEL(apb.psel),.PENABLE(apb.penable),
    .PRDATA(dut_prdata),.PREADY(apb.pready),.PSLVERR(apb.pslverr),
    .rx_i(uart.rx),.tx_o(uart.tx),.event_o(dut_irq)
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
