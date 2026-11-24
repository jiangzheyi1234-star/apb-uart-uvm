// Independent verification peripheral, not an alteration of the UART RTL.
// Contract: sixteen word-addressed RW locations, reset to zero; an error write
// completes with PSLVERR but does not commit. Read data is valid at completion.
module apb_programmable_slave(apb_if apb, apb_protocol_control_if control);
  timeunit 1ns;
  timeprecision 1ps;
  logic [31:0] memory[16];
  logic [31:0] saved_data, saved_read;
  logic [3:0] saved_index;
  logic active, saved_write, saved_hold, saved_error, saved_poison;
  int unsigned remaining;

  always_ff @(posedge apb.clk or negedge apb.rst_n) begin
    if(!apb.rst_n) begin
      active<=0; remaining<=0;
      saved_data<=0; saved_read<=0; saved_index<=0;
      saved_write<=0; saved_hold<=0; saved_error<=0; saved_poison<=0;
      for(int index=0;index<16;index++) memory[index]<=0;
    end else begin
      if(apb.psel && !apb.penable) begin
        active<=1;
        remaining<=control.wait_cycles;
        saved_index<=apb.paddr[5:2];
        saved_write<=apb.pwrite;
        saved_data<=apb.pwdata;
        saved_read<=memory[apb.paddr[5:2]];
        saved_hold<=control.hold_ready;
        saved_error<=control.error_response;
        saved_poison<=control.poison_wait_reads;
      end else if(apb.psel && apb.penable && active) begin
        if(!saved_hold) begin
          if(remaining!=0) remaining<=remaining-1;
          else begin
            if(saved_write && !saved_error) memory[saved_index]<=saved_data;
            active<=0;
          end
        end
      end else if(!apb.psel) active<=0;
    end
  end

  always_comb begin
    apb.pready=apb.rst_n && active && !saved_hold && remaining==0;
    apb.pslverr=apb.pready && saved_error;
    // Poisoned wait-phase data is legal APB behavior. It proves that neither
    // the master nor the passive monitor treats an unready read as complete.
    apb.prdata=(saved_poison && !apb.pready)?32'hbad0feed:saved_read;
  end
endmodule
