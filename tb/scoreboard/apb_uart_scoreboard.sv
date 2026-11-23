// Predictions come exclusively from APB transfers and independently decoded pins.
class apb_uart_scoreboard extends uvm_scoreboard;
  `uvm_component_utils(apb_uart_scoreboard)
  uvm_analysis_imp_apb #(apb_seq_item, apb_uart_scoreboard) apb_imp;
  uvm_analysis_imp_tx #(uart_seq_item, apb_uart_scoreboard) tx_imp;
  uvm_analysis_imp_rx #(uart_seq_item, apb_uart_scoreboard) rx_imp;
  virtual apb_if vif;
  uart_config cfg;
  byte unsigned expected_tx[$], expected_rx[$];
  bit [7:0] lcr, ier, dll, dlm;
  int unsigned tx_checked, rx_checked, resets_seen, rx_parity_faults, rx_stop_faults;
  int unsigned max_tx_pending, max_rx_pending;
  int unsigned min_tx_checks = 1, min_rx_checks = 1;
  int unsigned tx_accepted, tx_dropped, empty_rbr_reads;
  bit allow_empty_rbr_reads;
  // External reference model: 16 FIFO entries plus one serializer. The model
  // uses APB transfers and the configured frame timing, never DUT hierarchy.
  int unsigned tx_fifo_count, tx_busy_cycles;
  bit pending_thr_write, pending_tx_clear, tx_clear_due;
  byte unsigned pending_thr_data;

  covergroup capacity_cg with function sample(int tx_fifo, int rx_pending,
                                             bit dropped, bit empty_read);
    option.per_instance=1;
    tx_occupancy: coverpoint tx_fifo {
      bins empty={0}; bins one={1}; bins partial={[2:15]}; bins full={16};
    }
    // RX pending includes a possible 17th frame held by the receiver.
    rx_outstanding: coverpoint rx_pending {
      bins empty={0}; bins partial={[1:15]}; bins fifo_capacity={16}; bins retained={17};
    }
    full_write_drop: coverpoint dropped;
    empty_read_observed: coverpoint empty_read;
  endgroup

  function new(string name, uvm_component parent);
    super.new(name, parent);
    apb_imp = new("apb_imp", this);
    tx_imp = new("tx_imp", this);
    rx_imp = new("rx_imp", this);
    capacity_cg = new();
  endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(virtual apb_if)::get(this,"","vif",vif))
      `uvm_fatal("NO_VIF", "scoreboard requires apb_if")
    if (!uvm_config_db#(uart_config)::get(this,"","cfg",cfg))
      `uvm_fatal("NO_CFG", "scoreboard requires shared uart_config")
  endfunction
  function void reset_model();
    expected_tx.delete(); expected_rx.delete();
    lcr=0; ier=0; dll=0; dlm=0;
    tx_fifo_count=0; tx_busy_cycles=0;
    pending_thr_write=0; pending_tx_clear=0; tx_clear_due=0;
    cfg.epoch++; cfg.bit_cycles=1; cfg.data_bits=5;
    cfg.parity_en=0; cfg.stop_bits=1;
    resets_seen++;
  endfunction
  task run_phase(uvm_phase phase);
    fork
      begin
        // Include the initial reset, even if it was asserted before run_phase.
        wait(vif.rst_n === 1'b0);
        forever begin
          reset_model();
          @(posedge vif.rst_n);
          @(negedge vif.rst_n);
        end
      end
      begin
        forever begin
          @(posedge vif.clk);
          // All passive APB callbacks run before this reference-state update.
          #1ps;
          if(vif.rst_n === 1'b1) advance_tx_model();
        end
      end
    join
  endtask
  function void advance_tx_model();
    bit full_before, consume_before;
    int unsigned frame_bits;
    full_before=(tx_fifo_count==16);
    consume_before=(tx_busy_cycles==0 && tx_fifo_count!=0);
    frame_bits=1+cfg.data_bits+int'(cfg.parity_en)+cfg.stop_bits;
    if(tx_busy_cycles!=0) tx_busy_cycles--;
    else if(consume_before) begin
      // First start bit is one cycle longer because bit_done is registered.
      // The following idle clock accepts the next FIFO word.
      tx_busy_cycles=frame_bits*cfg.bit_cycles+1;
    end
    if(tx_clear_due) tx_fifo_count=0;
    else begin
      if(consume_before) tx_fifo_count--;
      if(pending_thr_write) begin
        // A full FIFO rejects the write even when it also pops this cycle.
        if(full_before) begin
          tx_dropped++;
          capacity_cg.sample(tx_fifo_count,expected_rx.size(),1,0);
        end else begin
          tx_fifo_count++;
          expected_tx.push_back(pending_thr_data);
          tx_accepted++;
          if(expected_tx.size()>max_tx_pending) max_tx_pending=expected_tx.size();
        end
      end
    end
    tx_clear_due=pending_tx_clear;
    pending_tx_clear=0;
    pending_thr_write=0;
    capacity_cg.sample(tx_fifo_count,expected_rx.size(),0,0);
  endfunction
  function byte unsigned mask_data(bit [7:0] data);
    return data & ((1 << cfg.data_bits)-1);
  endfunction
  function void compare_register(apb_seq_item t, bit [7:0] expected);
    if(t.rdata !== {24'b0, expected})
      `uvm_error("REG_MISMATCH", $sformatf("addr=%h expected=%02h actual=%h",t.addr,expected,t.rdata))
  endfunction
  function void write_apb(apb_seq_item t);
    byte unsigned expected;
    if(vif.rst_n !== 1'b1 || t.aborted) return;
    if(t.slverr) `uvm_error("APB_ERROR", "Unexpected PSLVERR")
    if(t.write) begin
      case(t.addr[2:0])
        0: if(lcr[7]) dll=t.data[7:0]; else begin
          if(pending_thr_write)
            `uvm_fatal("MODEL_ORDER","More than one APB THR write in a clock")
          pending_thr_write=1;
          pending_thr_data=mask_data(t.data[7:0]);
        end
        1: if(lcr[7]) dlm=t.data[7:0]; else ier=t.data[7:0];
        2: begin
          if(t.data[1]) expected_rx.delete();
          // Test contract: TX clear is issued only when the serializer is idle.
          if(t.data[2] && expected_tx.size()!=0)
            `uvm_error("MODEL_SCOPE", "TX clear during traffic needs an in-flight frame model")
          pending_tx_clear=t.data[2];
        end
        3: lcr=t.data[7:0];
        default: ;
      endcase
      cfg.bit_cycles=int'({dlm,dll})+1;
      cfg.data_bits=5+int'(lcr[1:0]);
      cfg.parity_en=lcr[3]; cfg.stop_bits=lcr[2]?2:1;
    end else begin
      if($isunknown(t.rdata)) `uvm_error("APB_X", "Unknown read data")
      case(t.addr[2:0])
        0: if(lcr[7]) compare_register(t,dll); else if(expected_rx.size()==0) begin
             if(!allow_empty_rbr_reads)
               `uvm_error("RX_UNEXPECTED", "RBR read without a completed expected frame")
             // Empty FIFO data is unspecified; only zero-extension is defined.
             if(t.rdata[31:8] !== 0)
               `uvm_error("UPPER_BITS", "Empty RBR must still be zero extended")
             empty_rbr_reads++;
             capacity_cg.sample(tx_fifo_count,0,0,1);
           end
           else begin
             expected=expected_rx.pop_front();
             if(t.rdata !== {24'b0,expected})
               `uvm_error("RX_MISMATCH",$sformatf("expected=%02h actual=%h",expected,t.rdata))
             rx_checked++;
           end
        1: compare_register(t,lcr[7]?dlm:ier);
        3: compare_register(t,lcr);
        4,6,7: compare_register(t,0);
        default: if(t.rdata[31:8] !== 0) `uvm_error("UPPER_BITS", "Register must be zero extended")
      endcase
    end
  endfunction
  function void write_tx(uart_seq_item t);
    byte unsigned expected;
    if(t.aborted || t.epoch!=cfg.epoch || vif.rst_n!==1'b1) return;
    if(expected_tx.size()==0) begin
      `uvm_error("TX_UNEXPECTED","TX frame without a THR write")
      return;
    end
    expected=expected_tx.pop_front();
    if(t.data !== expected || t.parity_error || t.framing_error)
      `uvm_error("TX_MISMATCH",$sformatf("expected=%02h actual=%02h parity=%b stop=%b",expected,t.data,t.parity_error,t.framing_error))
    tx_checked++;
  endfunction
  function void write_rx(uart_seq_item t);
    if(t.aborted || t.epoch!=cfg.epoch || vif.rst_n!==1'b1) return;
    expected_rx.push_back(t.data);
    if(expected_rx.size()>17)
      `uvm_error("MODEL_SCOPE","More than 17 unread RX frames requires an overrun model")
    if(t.parity_error) rx_parity_faults++;
    if(t.framing_error) rx_stop_faults++;
    if(expected_rx.size()>max_rx_pending) max_rx_pending=expected_rx.size();
    capacity_cg.sample(tx_fifo_count,expected_rx.size(),0,0);
  endfunction
  function void check_phase(uvm_phase phase);
    super.check_phase(phase);
    if(expected_tx.size()!=0 || expected_rx.size()!=0 || tx_fifo_count!=0 || pending_thr_write)
      `uvm_error("PENDING",$sformatf("Uncompared TX=%0d RX=%0d",expected_tx.size(),expected_rx.size()))
    if(tx_checked<min_tx_checks || rx_checked<min_rx_checks)
      `uvm_error("NO_CHECKS",$sformatf("Compared TX=%0d/%0d RX=%0d/%0d",tx_checked,min_tx_checks,rx_checked,min_rx_checks))
    `uvm_info("SB_COUNTS",$sformatf("TX=%0d RX=%0d resets=%0d max_tx=%0d max_rx=%0d",tx_checked,rx_checked,resets_seen,max_tx_pending,max_rx_pending),UVM_LOW)
    `uvm_info("SB_BOUNDARIES",$sformatf("TX accepted=%0d dropped=%0d empty_RBR_reads=%0d",tx_accepted,tx_dropped,empty_rbr_reads),UVM_LOW)
  endfunction
endclass
