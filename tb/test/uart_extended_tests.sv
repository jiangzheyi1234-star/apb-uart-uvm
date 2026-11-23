// Optional tests extend the four-test compatibility suite. All data predictions
// still originate from observed APB transfers and independently decoded pins.
class uart_tx_overflow_test extends base_test;
  `uvm_component_utils(uart_tx_overflow_test)
  function new(string name,uvm_component parent); super.new(name,parent); endfunction
  task scenario();
    // 21 writes complete within the first start bit: one serializer word and
    // sixteen FIFO slots accept 17; the following four writes must be dropped.
    configure(8,0,1,127);
    for(int i=0;i<21;i++) wr(0,32'h30+i);
    expect_bits(5,32'h20,0);
    wait_tx_done();
    if(env.sb.tx_accepted!=17 || env.sb.tx_dropped!=4 || env.sb.tx_checked!=17)
      `uvm_error("TX_OVERFLOW",$sformatf("accepted=%0d dropped=%0d pin_frames=%0d",env.sb.tx_accepted,env.sb.tx_dropped,env.sb.tx_checked))
    // Check recovery with data not present in the rejected burst.
    configure(); exchange(8'he7,8'h9b);
    env.sb.min_tx_checks=18;
  endtask
endclass

class uart_rx_retention_test extends base_test;
  `uvm_component_utils(uart_rx_retention_test)
  function new(string name,uvm_component parent); super.new(name,parent); endfunction
  task scenario();
    for(int i=0;i<17;i++) inject(8'(32'h70+i));
    if(env.sb.max_rx_pending!=17)
      `uvm_error("RX_RETENTION","Pin monitor must observe all 17 frames before software drains")
    expect_bits(5,1,1);
    // The receiver holds the 17th word until a read creates a FIFO slot.
    drain_rx(17); expect_bits(5,1,0);
    for(int i=0;i<3;i++) inject(8'(32'h21+i));
    drain_rx(3); expect_bits(5,1,0);
    exchange(8'ha7,8'hd3);
    env.sb.min_rx_checks=21;
  endtask
endclass

class uart_empty_read_test extends base_test;
  `uvm_component_utils(uart_empty_read_test)
  function new(string name,uvm_component parent); super.new(name,parent); endfunction
  task scenario();
    logic[31:0] unspecified_data;
    env.sb.allow_empty_rbr_reads=1;
    repeat(4) begin rd(0,unspecified_data); expect_bits(5,1,0); end
    inject(8'h56); drain_rx(1);
    repeat(2) begin rd(0,unspecified_data); expect_bits(5,1,0); end
    inject(8'hbc); wr(2,2); clocks(8);
    rd(0,unspecified_data); expect_bits(5,1,0);
    // Empty reads must not underflow the FIFO or corrupt a later valid frame.
    exchange(8'h1d,8'he2);
    if(env.sb.empty_rbr_reads!=7)
      `uvm_error("EMPTY_READ_COUNT","Expected seven independently observed empty RBR reads")
    env.sb.min_rx_checks=2;
  endtask
endclass

class uart_address_mirror_test extends base_test;
  `uvm_component_utils(uart_address_mirror_test)
  function new(string name,uvm_component parent); super.new(name,parent); endfunction
  task scenario();
    logic[31:0] data;
    // Only PADDR[2:0] selects a register. Upper address and write-data bits
    // must not change the value seen through another alias of that register.
    wr(12'hffb,32'h12340083);
    wr(12'h9a8,32'hdeadbe1f); wr(12'h9a9,32'h76540000);
    rd(12'h000,data); rd(12'h7f9,data); rd(12'h803,data);
    wr(12'h803,3); wr(12'hff9,32'habcd0000); clocks(8);
    fork wr(12'hff8,32'hdeadbe5a); inject(8'ha5); join
    wait_status(1,1); rd(12'h800,data); wait_tx_done();
    // Close the observed DLAB/address-alias access gaps with behavior checks:
    // DLL/DLM keep the run divisor, IER stays disabled, FCR clears idle FIFOs,
    // and writes to read-only/unimplemented registers must be ignored.
    env.sb.allow_empty_rbr_reads=1;
    for(int bank=0;bank<2;bank++) begin
      wr(3,bank!=0?32'h83:32'h03);
      for(int mirrored=0;mirrored<2;mirrored++) begin
        for(int low=0;low<8;low++) begin
          case(low)
            0: if(bank!=0) wr(12'((mirrored!=0?32'hff8:0)+low),31);
            1: wr(12'((mirrored!=0?32'hff8:0)+low),0);
            2: wr(12'((mirrored!=0?32'hff8:0)+low),6);
            3: wr(12'((mirrored!=0?32'hff8:0)+low),bank!=0?32'h83:32'h03);
            default: wr(12'((mirrored!=0?32'hff8:0)+low),32'hffffffff);
          endcase
          rd(12'((mirrored!=0?32'hff8:0)+low),data);
          if(low==2 && data!==32'hc1)
            `uvm_error("ALIAS_IIR","Disabled interrupt sources must read no-pending through every IIR alias")
          if(low==5 && data!==32'h60)
            `uvm_error("ALIAS_LSR","Ignored LSR write must preserve the empty/idle status")
          // Each access must preserve the current DLAB/format bank.
          expect_bits(3,32'hff,bank!=0?32'h83:32'h03);
        end
      end
      if(bank!=0) begin expect_bits(0,32'hff,31); expect_bits(1,32'hff,0); end
      else expect_bits(5,1,0); // Empty RBR reads must not underflow the FIFO.
    end
    wr(3,3); clocks(8);
    expect_bits(12'hffd,32'h61,32'h60);
  endtask
endclass

class uart_framing_requirement_test extends base_test;
  `uvm_component_utils(uart_framing_requirement_test)
  function new(string name,uvm_component parent); super.new(name,parent); endfunction
  task scenario();
    exchange(8'h5a,8'ha5);
    inject(8'hc9,0,1);
    expect_bits(5,8,8); // A real FAIL on unmodified RTL, PASS requires detection.
    drain_rx(1);
    env.sb.min_rx_checks=2;
  endtask
endclass

// Error status belongs to the FIFO head, not the most recently received frame.
// This strict requirement test intentionally fails on the original RTL.
class uart_error_association_test extends base_test;
  `uvm_component_utils(uart_error_association_test)
  function new(string name,uvm_component parent); super.new(name,parent); endfunction
  task scenario();
    logic[31:0] data;
    configure(8,1,1); exchange(8'h55,8'haa);
    inject(8'h10); inject(8'h96,1,0); inject(8'h20);
    expect_bits(5,12,0); rd(0,data); clocks(4);
    expect_bits(5,12,4); rd(0,data); clocks(4);
    expect_bits(5,12,0); rd(0,data); clocks(4);
    expect_bits(5,13,0);
    if(env.sb.rx_parity_faults!=1)
      `uvm_error("ERROR_ASSOCIATION","Expected one independently decoded parity error")
    env.sb.min_rx_checks=4;
  endtask
endclass

class uart_irq_test extends base_test;
  `uvm_component_utils(uart_irq_test)
  function new(string name,uvm_component parent); super.new(name,parent); endfunction

  task upstream_characterization();
    logic[31:0] unspecified_data;
    exchange(8'h5a,8'ha5);
    // F03: an idle, empty receiver incorrectly asserts RX IRQ because its
    // RDA input is connected to TX-empty. F04 then prevents deassertion.
    wr(1,1); expect_irq(1); expect_iir(8'hc8);
    wr(1,0); expect_irq(1); expect_iir(8'hc8);
    env.sb.allow_empty_rbr_reads=1;
    rd(0,unspecified_data); clocks(4);
    expect_iir(8'hc0); expect_irq(1);
    `uvm_warning("KNOWN_IRQ_LIMITATION","Observed upstream F03 false RX interrupt and F04 stuck IRQ; strict requirements remain separate")
  endtask

  task strict_irq_checks();
    int threshold;
    logic[31:0] data;
    exchange(8'h5a,8'ha5);
    wr(1,0); expect_irq(0); expect_iir(8'hc1);
    for(int level=0;level<4;level++) begin
      case(level) 0:threshold=1; 1:threshold=4; 2:threshold=8; default:threshold=14; endcase
      wr(1,0); wr(2,(level<<6)|2); clocks(8);
      wr(1,1); expect_irq(0); expect_iir(8'hc1);
      for(int i=0;i<threshold-1;i++) inject(8'(32'h40+i));
      expect_irq(0);
      inject(8'(32'h90+level));
      expect_irq(1); expect_iir(8'hc8); expect_irq(1);
      // Above-threshold occupancy must retain a level-sensitive interrupt.
      inject(8'(32'ha0+level)); expect_irq(1);
      rd(0,data); expect_irq(1); // occupancy is exactly threshold now
      rd(0,data); expect_irq(0); // occupancy is below threshold now
      drain_rx(threshold-1); expect_bits(5,1,0);
    end
    // Disabling a pending source removes its event; the payload remains.
    wr(2,0); inject(8'h83); expect_irq(1);
    wr(1,0); expect_irq(0); expect_iir(8'hc1); drain_rx(1);

    // IIR acknowledges THRE until another nonempty-to-empty transition or
    // disable/re-enable. RX and line-status reads must not consume its latch.
    wr(1,2); expect_irq(1); expect_iir(8'hc4); expect_irq(0);
    wr(0,32'h38); wait_tx_done();
    expect_irq(1); expect_iir(8'hc4); expect_irq(0);
    wr(1,0); expect_irq(0); wr(1,2); expect_irq(1);
    wr(1,0); expect_irq(0);

    // Simultaneous line-error, RX-data and TX-empty sources: line > RX > TX.
    configure(8,1,1); wr(2,2); clocks(8); wr(1,7);
    inject(8'h96,1,0);
    expect_irq(1); expect_iir(8'hcc); expect_irq(1);
    expect_bits(5,4,4); // acknowledges line IRQ, preserves head's error flag
    expect_iir(8'hc8); expect_irq(1);
    drain_rx(1); expect_iir(8'hc4); expect_irq(0);

    // Each errored FIFO head gets its own line IRQ acknowledgement lifetime.
    wr(1,4); inject(8'h69,0,1); inject(8'hc3,1,0);
    expect_irq(1); expect_iir(8'hcc); expect_bits(5,12,8); expect_irq(0);
    rd(0,data); expect_irq(1); expect_iir(8'hcc);
    expect_bits(5,12,4); rd(0,data); expect_irq(0);
    expect_bits(5,12,0); wr(1,0);

    // Exercise the previously unobserved enable combinations with no RX data:
    // RX+TX and line+TX select THRE, while RX+line alone selects no source.
    for(int combination=0;combination<3;combination++) begin
      case(combination) 0:threshold=3; 1:threshold=5; default:threshold=6; endcase
      wr(2,2); clocks(8); wr(1,32'(threshold));
      expect_irq(threshold!=5); expect_iir(threshold==5?8'hc1:8'hc4);
      expect_irq(0); wr(1,0); expect_iir(8'hc1);
    end

    // The TX-empty and line-error sources are independent of the programmed
    // RX threshold. Check their IIR encodings/acknowledgements at every level.
    for(int level=0;level<4;level++) begin
      wr(2,(level<<6)|2); clocks(8);
      wr(1,2); expect_irq(1); expect_iir(8'hc4); expect_irq(0);
      wr(1,4); inject(8'(32'hb4+level),1,0);
      expect_irq(1); expect_iir(8'hcc);
      expect_bits(5,4,4); expect_irq(0);
      drain_rx(1); expect_bits(5,13,0);
      wr(1,0); expect_irq(0); expect_iir(8'hc1);
    end
    env.sb.min_tx_checks=2; env.sb.min_rx_checks=40;
  endtask

  task scenario();
    if(rtl_fixed) strict_irq_checks();
    else upstream_characterization();
  endtask
endclass

// Always enforce the fixed interrupt contract, even without +RTL_FIXED.
// It must fail rather than characterize defective original RTL.
class uart_irq_requirement_test extends uart_irq_test;
  `uvm_component_utils(uart_irq_requirement_test)
  function new(string name,uvm_component parent); super.new(name,parent); endfunction
  task scenario(); strict_irq_checks(); endtask
endclass

class uart_random_stress_test extends base_test;
  `uvm_component_utils(uart_random_stress_test)
  function new(string name,uvm_component parent); super.new(name,parent); endfunction
  task scenario();
    int bits_n, parity, stops, divisor, tx_count, rx_count;
    int total_tx, total_rx;
    bit[7:0] tx_values[17], rx_values[16];
    bit[7:0] mask;
    bit[31:0] tx_hash, rx_hash, format_hash;
    total_tx=0; total_rx=0;
    tx_hash=32'h811c9dc5; rx_hash=32'h811c9dc5; format_hash=32'h811c9dc5;
    for(int batch=0;batch<16;batch++) begin
      bits_n=$urandom_range(5,8);
      parity=$urandom_range(0,1);
      stops=$urandom_range(1,2);
      case($urandom_range(0,2))
        0:divisor=31;
        1:divisor=47;
        default:divisor=63;
      endcase
      tx_count=$urandom_range(8,17);
      rx_count=$urandom_range(8,16);
      mask=8'((1<<bits_n)-1);
      // Generate all payloads in one process before the concurrent streams.
      // These checksums describe the exact masked stimulus for seed replay;
      // pass/fail still comes from independent pin and APB comparisons.
      for(int i=0;i<tx_count;i++) begin
        tx_values[i]=8'($urandom_range(0,255));
        tx_hash=(tx_hash ^ {24'b0,(tx_values[i]&mask)})*32'h01000193;
      end
      for(int i=0;i<rx_count;i++) begin
        rx_values[i]=8'($urandom_range(0,255));
        rx_hash=(rx_hash ^ {24'b0,(rx_values[i]&mask)})*32'h01000193;
      end
      format_hash=(format_hash ^ ((bits_n<<24)|(parity<<16)|(stops<<8)|divisor))*32'h01000193;
      configure(bits_n,bit'(parity),stops,divisor);
      fork
        begin
          for(int i=0;i<tx_count;i++) wr(0,{24'b0,tx_values[i]});
        end
        begin
          for(int i=0;i<rx_count;i++) inject(rx_values[i]);
        end
      join
      // No format change until both streams have drained. RX batches fit its
      // sixteen-entry FIFO; TX batches fit one serializer plus sixteen slots.
      drain_rx(rx_count); wait_tx_done();
      total_tx+=tx_count; total_rx+=rx_count;
      `uvm_info("STRESS_BATCH",$sformatf("batch=%0d bits=%0d parity=%0d stops=%0d divisor=%0d TX=%0d RX=%0d",batch,bits_n,parity,stops,divisor,tx_count,rx_count),UVM_MEDIUM)
    end
    env.sb.min_tx_checks=total_tx; env.sb.min_rx_checks=total_rx;
    if(env.sb.tx_checked!=total_tx || env.sb.rx_checked!=total_rx || env.sb.tx_dropped!=0)
      `uvm_error("STRESS_COUNTS",$sformatf("TX=%0d/%0d RX=%0d/%0d unexpected_drops=%0d",env.sb.tx_checked,total_tx,env.sb.rx_checked,total_rx,env.sb.tx_dropped))
    `uvm_info("STRESS_STATS",$sformatf("batches=16 TX=%0d RX=%0d tx_hash=%08h rx_hash=%08h format_hash=%08h",total_tx,total_rx,tx_hash,rx_hash,format_hash),UVM_LOW)
  endtask
endclass

// Directed closure of the configured-speed x frame-format coverage matrix.
// This checks three exact baud periods, not clock-mismatch tolerance.
class uart_baud_sweep_test extends base_test;
  `uvm_component_utils(uart_baud_sweep_test)
  function new(string name,uvm_component parent); super.new(name,parent); endfunction
  task scenario();
    int divisor;
    for(int speed=0;speed<3;speed++) begin
      case(speed) 0:divisor=31; 1:divisor=47; default:divisor=63; endcase
      for(int bits_n=5;bits_n<=8;bits_n++)
        for(int parity=0;parity<=1;parity++)
          for(int stops=1;stops<=2;stops++) begin
            configure(bits_n,bit'(parity),stops,divisor);
            exchange(8'h55,8'haa);
          end
    end
    env.sb.min_tx_checks=48; env.sb.min_rx_checks=48;
  endtask
endclass
