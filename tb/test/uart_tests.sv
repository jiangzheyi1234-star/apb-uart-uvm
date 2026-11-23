class uart_smoke_test extends base_test;
  `uvm_component_utils(uart_smoke_test)
  function new(string name,uvm_component parent); super.new(name,parent); endfunction
  task scenario();
    logic[31:0] unused;
    // Exercise DLL/DLM aliases using nonzero high byte, then restore run speed.
    configure(8,0,1,32'h00000123);
    for(int bits_n=5;bits_n<=8;bits_n++)
      for(int parity=0;parity<=1;parity++)
        for(int stops=1;stops<=2;stops++) begin
          configure(bits_n,bit'(parity),stops);
          exchange(8'h55,8'haa);
          exchange(8'($urandom_range(0,255)),8'($urandom_range(0,255)));
        end
    configure();
    exchange(8'h00,8'hff); exchange(8'hff,8'h00);
    foreach_reserved: for(int addr=4;addr<=7;addr++) if(addr!=5) begin
      wr(12'(addr),32'hffffffff); rd(12'(addr),unused);
    end
    env.sb.min_tx_checks=34; env.sb.min_rx_checks=34;
  endtask
endclass

class uart_fifo_boundary_test extends base_test;
  `uvm_component_utils(uart_fifo_boundary_test)
  function new(string name,uvm_component parent); super.new(name,parent); endfunction
  task scenario();
    // In this fast burst the first frame shifts while 16 more fill the FIFO.
    repeat(2) begin
      for(int i=0;i<17;i++) wr(0,32'h20+i);
      wait_tx_done();
    end
    for(int i=0;i<16;i++) inject(8'(32'h80+i));
    expect_bits(5,1,1); drain_rx(16); expect_bits(5,1,0);
    // Pointer wrap after draining a completely full RX FIFO.
    inject(8'h31); inject(8'h72); drain_rx(2);
    // Clear populated RX FIFO and verify a fresh transfer afterward.
    repeat(4) inject(8'($urandom_range(0,255)));
    wr(2,2); clocks(8); expect_bits(5,1,0);
    exchange(8'h5a,8'ha5);
    wr(2,4); clocks(8); expect_bits(5,32'h60,32'h60);
    if(env.sb.max_tx_pending<17 || env.sb.max_rx_pending<16)
      `uvm_error("BOUNDARY_NOT_REACHED","Expected TX outstanding=17 and RX queued=16")
    env.sb.min_tx_checks=35; env.sb.min_rx_checks=19;
  endtask
endclass

// Upstream mode characterizes missing error reporting; +RTL_FIXED additionally
// requires PE/FE on the corresponding FIFO head. In both modes the independent
// pin monitor must observe each injected error and payload data must compare.
class uart_error_test extends base_test;
  `uvm_component_utils(uart_error_test)
  function new(string name,uvm_component parent); super.new(name,parent); endfunction
  task scenario();
    configure(8,1,1);
    exchange(8'hc3,8'h3c);
    inject(8'ha6,1,0);
    expect_bits(5,4,rtl_fixed?4:0); drain_rx(1);
    inject(8'h69,0,1);
    expect_bits(5,8,rtl_fixed?8:0); drain_rx(1);
    if(env.sb.rx_parity_faults!=1 || env.sb.rx_stop_faults!=1)
      `uvm_error("INJECTION_NOT_OBSERVED","Pin monitor must independently detect both injected faults")
    if(!rtl_fixed)
      `uvm_warning("KNOWN_RTL_LIMITATION","Parity/framing status remain zero in pinned RTL; see docs/rtl_findings.md")
    env.sb.min_rx_checks=3;
  endtask
endclass

// Opt-in requirement test. Expected to FAIL on the unmodified upstream RTL.
class uart_parity_requirement_test extends base_test;
  `uvm_component_utils(uart_parity_requirement_test)
  function new(string name,uvm_component parent); super.new(name,parent); endfunction
  task scenario();
    configure(8,1,1); exchange(8'h5a,8'ha5);
    inject(8'h96,1,0);
    expect_bits(5,4,4); // This is intentionally a real error, never reclassified PASS.
    drain_rx(1);
  endtask
endclass

class uart_reset_test extends base_test;
  `uvm_component_utils(uart_reset_test)
  function new(string name,uvm_component parent); super.new(name,parent); endfunction
  task scenario();
    wr(0,32'hf0); wr(0,32'h0f); wr(0,32'hcc);
    fork
      inject(8'he7);
      begin
        clocks(cfg.bit_cycles*3);
        // Shared asynchronous reset aborts both monitors and flushes predictions.
        vif.rst_n=0; clocks(8); vif.rst_n=1;
      end
    join
    clocks(8); configure();
    expect_bits(5,32'h61,32'h60);
    exchange(8'hc3,8'h3c);
    if(env.sb.resets_seen<2) `uvm_error("RESET_NOT_OBSERVED","Mid-frame reset was not modeled")
  endtask
endclass
