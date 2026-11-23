class apb_uart_coverage extends uvm_component;
  `uvm_component_utils(apb_uart_coverage)
  uvm_analysis_imp_cov_apb #(apb_seq_item,apb_uart_coverage) apb_imp;
  uvm_analysis_imp_cov_tx #(uart_seq_item,apb_uart_coverage) tx_imp;
  uvm_analysis_imp_cov_rx #(uart_seq_item,apb_uart_coverage) rx_imp;
  virtual apb_if vif;
  uart_config cfg;
  bit [7:0] last_lcr;
  bit [2:0] last_ier;
  bit [1:0] last_trigger;
  bit activity_since_reset;
  covergroup bus_cg with function sample(bit wr, bit [2:0] addr, bit dlab, bit mirrored);
    option.per_instance=1;
    direction: coverpoint wr;
    address: coverpoint addr {bins registers[]={[0:7]};}
    bank: coverpoint dlab;
    high_address_alias: coverpoint mirrored;
    access: cross direction,address,bank;
    aliases: cross direction,address,high_address_alias;
  endgroup
  // IIR is observed through completed APB reads. The interrupt test separately
  // checks the external IRQ pin and acknowledgement ordering.
  covergroup interrupt_cg with function sample(bit [3:0] cause, bit [2:0] enabled,
                                              bit [1:0] trigger);
    option.per_instance=1;
    source: coverpoint cause {
      bins none={4'h1}; bins receive={4'h8}; bins transmit={4'h4};
      bins line_error={4'hc}; bins invalid_pending={4'h0};
    }
    enables: coverpoint enabled;
    trigger_level: coverpoint trigger;
    receive_threshold: cross source,trigger_level;
  endgroup
  covergroup frame_cg with function sample(bit tx, bit[7:0] data, int bits_n,
                                          bit parity, int stops, bit pe, bit fe, int cycles);
    option.per_instance=1;
    direction: coverpoint tx;
    payload: coverpoint data {bins zero={0}; bins ones={255}; bins alternating={8'h55,8'haa}; bins other=default;}
    width: coverpoint bits_n {bins supported[]={[5:8]};}
    parity_enabled: coverpoint parity;
    stop_count: coverpoint stops {bins one={1}; bins two={2};}
    parity_fault: coverpoint pe;
    stop_fault: coverpoint fe;
    bit_period: coverpoint cycles {
      bins div31={32}; bins div47={48}; bins div63={64}; bins other=default;
    }
    format: cross direction,width,parity_enabled,stop_count;
    baud_format: cross direction,width,parity_enabled,stop_count,bit_period;
  endgroup
  // A reset after observed activity is distinct from the initial/idle reset.
  // This covergroup does not claim that a frame was in flight at assertion.
  covergroup reset_cg with function sample(bit had_activity);
    option.per_instance=1;
    reset_context: coverpoint had_activity {
      bins initial_or_idle={0};
      bins after_activity={1};
    }
  endgroup
  function new(string name,uvm_component parent);
    super.new(name,parent);
    apb_imp=new("apb_imp",this); tx_imp=new("tx_imp",this); rx_imp=new("rx_imp",this);
    bus_cg=new(); frame_cg=new(); reset_cg=new(); interrupt_cg=new();
  endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if(!uvm_config_db#(uart_config)::get(this,"","cfg",cfg))
      `uvm_fatal("NO_CFG","coverage requires uart_config")
    if(!uvm_config_db#(virtual apb_if)::get(this,"","vif",vif))
      `uvm_fatal("NO_VIF","coverage requires apb_if")
  endfunction
  task run_phase(uvm_phase phase);
    // Sample an initial reset already low when run_phase begins, too.
    wait(vif.rst_n === 1'b0);
    forever begin
      reset_cg.sample(activity_since_reset);
      last_lcr=0;
      last_ier=0;
      last_trigger=0;
      activity_since_reset=0;
      @(posedge vif.rst_n);
      @(negedge vif.rst_n);
    end
  endtask
  function void write_cov_apb(apb_seq_item t);
    if(t.aborted || vif.rst_n !== 1'b1) return;
    bus_cg.sample(t.write,t.addr[2:0],last_lcr[7],|t.addr[11:3]);
    activity_since_reset=1;
    if(!t.write && t.addr[2:0]==2)
      interrupt_cg.sample(t.rdata[3:0],last_ier,last_trigger);
    if(t.write && !t.slverr && t.addr[2:0]==1 && !last_lcr[7]) last_ier=t.data[2:0];
    if(t.write && !t.slverr && t.addr[2:0]==2) last_trigger=t.data[7:6];
    if(t.write && !t.slverr && t.addr[2:0]==3) last_lcr=t.data[7:0];
  endfunction
  function void write_cov_tx(uart_seq_item t);
    if(!t.aborted && vif.rst_n === 1'b1 && t.epoch==cfg.epoch) begin
      frame_cg.sample(1,t.data,cfg.data_bits,cfg.parity_en,cfg.stop_bits,t.parity_error,t.framing_error,cfg.bit_cycles);
      activity_since_reset=1;
    end
  endfunction
  function void write_cov_rx(uart_seq_item t);
    if(!t.aborted && vif.rst_n === 1'b1 && t.epoch==cfg.epoch) begin
      frame_cg.sample(0,t.data,cfg.data_bits,cfg.parity_en,cfg.stop_bits,t.parity_error,t.framing_error,cfg.bit_cycles);
      activity_since_reset=1;
    end
  endfunction
endclass
