`timescale 1ns/1ps
// Three independent RAM models: RTL, mapped gates, and scan-inserted gates.
// All comparisons are from ports; no controller state is peeked or forced.
module frontend_gate_smoke;
  parameter integer SCAN_LENGTH=1;
  `include "scan_capture.vh"
  reg CLK=0, RSTN=0;
  always #5 CLK=~CLK;
  reg [11:0] PADDR=0;
  reg [31:0] PWDATA=0;
  reg PWRITE=0,PSEL=0,PENABLE=0;
  wire [31:0] q0,q1,q2;
  wire ready0,ready1,ready2,err0,err1,err2;
  wire en0,en1,en2,we0,we1,we2;
  wire [5:0] a0,a1,a2;
  wire [31:0] d0,d1,d2;
  reg [31:0] r0=0,r1=0,r2=0;
  reg [31:0] mem0[0:63],mem1[0:63],mem2[0:63];
  reg SCAN_EN=0,SCAN_IN=0;
  wire SCAN_OUT;
  reg checks=0,fault=0;
  integer comparisons=0,transactions=0,scan_checks=0,capture_checks=0;
  integer native_ops=0,native_reads=0,native_writes=0;
  reg watch_bist=0;
  wire [31:0] fault_mask=32'h00000008;
  apb_ram_mbist_rtl rtl(CLK,RSTN,PADDR,PWDATA,PWRITE,PSEL,PENABLE,q0,ready0,err0,en0,we0,a0,d0,r0);
  apb_ram_mbist gate(CLK,RSTN,PADDR,PWDATA,PWRITE,PSEL,PENABLE,q1,ready1,err1,en1,we1,a1,d1,r1);
  apb_ram_mbist_scan scan_gate(CLK,RSTN,PADDR,PWDATA,PWRITE,PSEL,PENABLE,q2,ready2,err2,en2,we2,a2,d2,r2,SCAN_EN,SCAN_IN,SCAN_OUT);
  function [31:0] stuck(input [31:0] value,input [5:0] addr);
    stuck=(fault && addr==63)?(value & ~fault_mask):value;
  endfunction
  always @(posedge CLK) begin
    if(en0 && !SCAN_EN) begin
      if(we0) mem0[a0]<=stuck(d0,a0); else r0<=stuck(mem0[a0],a0);
      if(watch_bist) begin
        native_ops<=native_ops+1;
        if(we0) native_writes<=native_writes+1; else native_reads<=native_reads+1;
      end
    end
    if(en1 && !SCAN_EN) begin
      if(we1) mem1[a1]<=stuck(d1,a1); else r1<=stuck(mem1[a1],a1);
    end
    if(en2 && !SCAN_EN) begin
      if(we2) mem2[a2]<=stuck(d2,a2); else r2<=stuck(mem2[a2],a2);
    end
    #1;
    if(checks && RSTN && !SCAN_EN) begin
      if({q0,ready0,err0,en0,we0,a0,d0} !== {q1,ready1,err1,en1,we1,a1,d1})
        $fatal(1,"RTL_GATE_MISMATCH t=%0t",$time);
      if({q0,ready0,err0,en0,we0,a0,d0} !== {q2,ready2,err2,en2,we2,a2,d2})
        $fatal(1,"SCAN_FUNCTIONAL_MISMATCH t=%0t",$time);
      comparisons=comparisons+1;
    end
  end
  task automatic reset_controller;
    @(negedge CLK);checks=0;RSTN=0;PSEL=0;PENABLE=0;
    repeat(3) @(negedge CLK);
    RSTN=1;checks=1;
  endtask
  task automatic access(input bit write_access,input [11:0] address,input [31:0] data,
                        input bit expect_error,output reg [31:0] result);
    integer waits;
    @(negedge CLK);PSEL=1;PENABLE=0;PWRITE=write_access;PADDR=address;PWDATA=data;
    @(negedge CLK);PENABLE=1;
    waits=0;
    begin : handshake
      forever begin
        @(posedge CLK);
        if(ready0===1) begin
          result=q0;
          if(err0!==expect_error) $fatal(1,"APB_ERROR addr=%h expected=%b got=%b",address,expect_error,err0);
          disable handshake;
        end
        waits=waits+1;
        if(waits>4) $fatal(1,"APB_TIMEOUT addr=%h",address);
      end
    end
    @(negedge CLK);PSEL=0;PENABLE=0;
    transactions=transactions+1;
  endtask
  task automatic expect_register(input [11:0] address,input [31:0] expected);
    reg [31:0] result;
    access(0,address,0,0,result);
    if(result!==expected) $fatal(1,"REGISTER addr=%h expected=%h actual=%h",address,expected,result);
  endtask
  task automatic wait_done(input [31:0] expected);
    reg [31:0] result;
    integer polls;
    polls=0;
    begin : polling
      forever begin
        access(0,12'h084,0,0,result);
        if(result[1]) begin
          if(result!==expected) $fatal(1,"MBIST_STATUS expected=%h got=%h",expected,result);
          disable polling;
        end
        polls=polls+1;
        if(polls>400) $fatal(1,"MBIST_TIMEOUT");
      end
    end
  endtask
  task automatic shift_pattern(input integer kind);
    reg [SCAN_LENGTH-1:0] pattern;
    integer j;
    for(j=0;j<SCAN_LENGTH;j=j+1)
      case(kind)
        0:pattern[j]=0;
        1:pattern[j]=1;
        2:pattern[j]=(j==0);
        default:pattern[j]=j%2;
      endcase
    @(negedge CLK);SCAN_EN=1;checks=0;
    for(j=SCAN_LENGTH-1;j>=0;j=j-1) begin
      SCAN_IN=pattern[j];
      @(negedge CLK);
    end
    for(j=SCAN_LENGTH-1;j>=0;j=j-1) begin
      if(SCAN_OUT!==pattern[j]) $fatal(1,"SCAN_SHIFT kind=%0d bit=%0d",kind,j);
      scan_checks=scan_checks+1;
      SCAN_IN=0;
      @(negedge CLK);
    end
    SCAN_EN=0;
    reset_controller;
  endtask
  // The fault capture occurred in functional mode. Check 32 diagnostic data
  // flops against the independently known stuck-bit response, then reset all
  // three controllers before restarting traffic. Other chain bits are shifted
  // but are not counted as capture checks.
  task automatic shift_fault_capture;
    integer j;
    @(negedge CLK);SCAN_EN=1;checks=0;SCAN_IN=0;
    for(j=SCAN_LENGTH-1;j>=0;j=j-1) begin
      if(SCAN_CAPTURE_MASK[j]) begin
        if(SCAN_OUT!==SCAN_CAPTURE_EXPECTED[j]) $fatal(1,"SCAN_CAPTURE bit=%0d expected=%b actual=%b",j,SCAN_CAPTURE_EXPECTED[j],SCAN_OUT);
        capture_checks=capture_checks+1;
      end
      @(negedge CLK);
    end
    SCAN_EN=0;
    $display("SCAN_CAPTURE_PASS checked_bits=%0d independently_expected=fffffff7",capture_checks);
    reset_controller;
  endtask
  reg [31:0] response;
  integer i;
  initial begin
    for(i=0;i<64;i=i+1) begin
      mem0[i]=32'h9e370001^i;mem1[i]=mem0[i];mem2[i]=mem0[i];
    end
    reset_controller;
    for(i=0;i<4;i=i+1) shift_pattern(i);
    expect_register(12'h084,0);
    access(1,12'h100,32'h12345678,0,response);
    expect_register(12'h100,32'h12345678);
    access(1,12'h1fc,32'h87654321,0,response);
    expect_register(12'h1fc,32'h87654321);
    access(1,12'h084,0,1,response);
    access(0,12'h101,0,1,response);
    access(0,12'h000,0,1,response);
    access(0,12'h080,0,1,response);
    native_ops=0;native_reads=0;native_writes=0;watch_bist=1;
    access(1,12'h080,1,0,response);
    access(1,12'h100,32'hffffffff,1,response);
    access(1,12'h080,1,1,response);
    wait_done(2);
    watch_bist=0;
    if(native_ops!=640 || native_reads!=320 || native_writes!=320)
      $fatal(1,"MARCH_OPERATIONS total=%0d reads=%0d writes=%0d",native_ops,native_reads,native_writes);
    for(i=0;i<64;i=i+1) expect_register(12'h100+4*i,0);
    $display("GATE_CLEAN_MBIST native_ops=%0d reads=%0d writes=%0d",native_ops,native_reads,native_writes);
    fault=1;
    access(1,12'h080,1,0,response);
    wait_done(6);
    expect_register(12'h088,63);
    expect_register(12'h08c,32'hffffffff);
    expect_register(12'h090,32'hfffffff7);
    expect_register(12'h094,2);
    expect_register(12'h084,6);
    $display("GATE_FAULT_MBIST addr=63 step=2 expected=ffffffff actual=fffffff7");
    shift_fault_capture;
    fault=0;
    access(1,12'h080,1,0,response);
    wait_done(2);
    access(1,12'h080,1,0,response);
    repeat(7) @(negedge CLK);
    reset_controller;
    expect_register(12'h084,0);
    access(1,12'h100,32'hcafef00d,0,response);
    expect_register(12'h100,32'hcafef00d);
    $display("FRONTEND_GATE_PASS comparisons=%0d apb_transactions=%0d scan_length=%0d scan_bits_checked=%0d capture_bits_checked=%0d",comparisons,transactions,SCAN_LENGTH,scan_checks,capture_checks);
    $finish;
  end
  initial begin #1000000;$fatal(1,"GLOBAL_TIMEOUT");end
  initial begin
    $dumpfile("gate_smoke.vcd");
    $dumpvars(1,frontend_gate_smoke);
  end
endmodule
