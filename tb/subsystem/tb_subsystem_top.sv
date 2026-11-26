`include "uvm_macros.svh"
module tb_top;
  timeunit 1ns;
  timeprecision 1ps;
  import uvm_pkg::*;
  import subsystem_pkg::*;
  logic clk = 0;
  always #5ns clk = ~clk;
  apb_if apb(clk);
  uart_if uart(clk);
  subsystem_control_if control(clk);
  logic ram_en, ram_we;
  logic [5:0] ram_addr, read_address;
  logic [31:0] ram_wdata, physical_rdata, returned_rdata;

  assign uart.rst_n = apb.rst_n;
  assign control.ram_en = ram_en;
  assign control.ram_we = ram_we;
  assign control.ram_addr = ram_addr;
  apb_peripheral_subsystem dut (
    .CLK(clk), .RSTN(apb.rst_n), .PADDR(apb.paddr), .PWDATA(apb.pwdata),
    .PWRITE(apb.pwrite), .PSEL(apb.psel), .PENABLE(apb.penable),
    .PRDATA(apb.prdata), .PREADY(apb.pready), .PSLVERR(apb.pslverr),
    .rx_i(uart.rx), .tx_o(uart.tx), .event_o(uart.irq),
    .ram_en(ram_en), .ram_we(ram_we), .ram_addr(ram_addr),
    .ram_wdata(ram_wdata), .ram_rdata(returned_rdata)
  );
  apb_sync_ram memory (
    .CLK(clk), .ram_en(ram_en), .ram_we(ram_we), .ram_addr(ram_addr),
    .ram_wdata(ram_wdata), .ram_rdata(physical_rdata)
  );
  // Capture the address of the synchronous read, not the current request.
  // The memory and this register update together in NBA. Only the returned
  // value is impaired; the production RAM array and RTL have no test controls.
  always_ff @(posedge clk or negedge apb.rst_n) begin
    if (!apb.rst_n) read_address <= 0;
    else if (ram_en && !ram_we) read_address <= ram_addr;
  end
  assign returned_rdata = (control.fault_enable && read_address == 6'd63)
                        ? physical_rdata & 32'hfffffff7 : physical_rdata;

  initial begin
    apb.rst_n = 0;
    repeat (8) @(negedge clk);
    apb.rst_n = 1;
  end
  initial begin
    uvm_config_db#(virtual apb_if)::set(null,"uvm_test_top*","vif",apb);
    uvm_config_db#(virtual uart_if)::set(null,"uvm_test_top.uart*","vif",uart);
    uvm_config_db#(virtual uart_if)::set(null,"uvm_test_top","uart_vif",uart);
    uvm_config_db#(virtual subsystem_control_if)::set(null,"uvm_test_top*","control_vif",control);
    run_test();
  end
  initial begin : waveform_capture
    string waveform_path;
    if ($test$plusargs("TRACE")) begin
      if (!$value$plusargs("VCD_FILE=%s",waveform_path)) waveform_path="subsystem.vcd";
      $dumpfile(waveform_path);
      $dumpvars(0,tb_top);
    end
  end
  initial begin
    #2ms;
    $fatal(1,"Subsystem suite global timeout");
  end
endmodule
