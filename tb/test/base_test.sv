class base_test extends uvm_test;
  `uvm_component_utils(base_test)
  apb_uart_env env;
  uart_config cfg;
  virtual apb_if vif;
  bit scenario_done;
  bit rtl_fixed;
  function new(string name,uvm_component parent); super.new(name,parent); endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    rtl_fixed=$test$plusargs("RTL_FIXED");
    if(!uvm_config_db#(virtual apb_if)::get(this,"","vif",vif))
      `uvm_fatal("NO_VIF","test requires apb_if")
    cfg=uart_config::type_id::create("cfg");
    uvm_config_db#(uart_config)::set(this,"env.*","cfg",cfg);
    env=apb_uart_env::type_id::create("env",this);
  endfunction
  task clocks(int unsigned n);
    repeat(n) @(negedge vif.clk);
  endtask
  task access(bit wr,bit[11:0] addr,bit[31:0] value,output logic[31:0] result);
    apb_access_seq seq=apb_access_seq::type_id::create("access");
    seq.wr=wr; seq.address=addr; seq.value=value;
    seq.start(env.apb.sqr); result=seq.read_value;
  endtask
  task wr(bit[11:0] addr,bit[31:0] value);
    logic[31:0] unused;
    access(1,addr,value,unused);
  endtask
  task rd(bit[11:0] addr,output logic[31:0] result);
    access(0,addr,0,result);
  endtask
  task expect_bits(bit[11:0] addr,bit[31:0] mask,bit[31:0] expected);
    logic[31:0] actual;
    rd(addr,actual);
    if((actual & mask) !== expected)
      `uvm_error("STATUS",$sformatf("addr=%h mask=%h expected=%h actual=%h",addr,mask,expected,actual))
  endtask
  task expect_irq(bit expected);
    clocks(4);
    if(env.uart.driver.vif.irq !== expected)
      `uvm_error("IRQ",$sformatf("expected IRQ=%b actual=%b",expected,env.uart.driver.vif.irq))
  endtask
  task expect_iir(bit[7:0] expected);
    expect_bits(2,32'hff,{24'b0,expected});
  endtask
  task wait_status(bit[31:0] mask,bit[31:0] expected);
    logic[31:0] actual;
    for(int i=0;i<20000;i++) begin
      rd(5,actual);
      if((actual & mask) === expected) return;
    end
    `uvm_fatal("STATUS_TIMEOUT",$sformatf("LSR mask=%h expected=%h",mask,expected))
  endtask
  task configure(int bits_n=8,bit parity=0,int stops=1,int divisor=31);
    bit[7:0] format_bits;
    logic[31:0] unused;
    format_bits={4'b0,parity,(stops==2),2'(bits_n-5)};
    wr(3,{24'b0,1'b1,format_bits[6:0]});
    wr(0,divisor & 255); wr(1,(divisor>>8)&255);
    rd(0,unused); rd(1,unused); // DLAB readback checked by scoreboard.
    wr(3,{24'b0,format_bits}); wr(1,0);
    rd(3,unused); rd(1,unused);
    clocks(8);
  endtask
  task inject(bit[7:0] value,bit bad_parity=0,bit bad_stop=0);
    uart_send_seq seq=uart_send_seq::type_id::create("inject");
    seq.value=value; seq.bad_parity=bad_parity; seq.bad_stop=bad_stop;
    seq.start(env.uart.sqr);
  endtask
  task drain_rx(int n);
    logic[31:0] data;
    repeat(n) begin wait_status(1,1); rd(0,data); end
    clocks(8);
  endtask
  task wait_tx_done();
    wait_status(32'h60,32'h60);
    clocks(cfg.bit_cycles);
  endtask
  task exchange(bit[7:0] tx_data,bit[7:0] rx_data);
    fork
      wr(0,{24'b0,tx_data});
      inject(rx_data);
    join
    drain_rx(1); wait_tx_done();
  endtask
  virtual task scenario();
    exchange(8'h55,8'haa);
  endtask
  task run_phase(uvm_phase phase);
    phase.raise_objection(this);
    wait(vif.rst_n===1'b1); clocks(8);
    configure(); scenario(); wait_tx_done(); clocks(16);
    scenario_done=1;
    phase.drop_objection(this);
  endtask
  function void report_phase(uvm_phase phase);
    uvm_report_server server=uvm_report_server::get_server();
    super.report_phase(phase);
    if(scenario_done && server.get_severity_count(UVM_ERROR)==0 && server.get_severity_count(UVM_FATAL)==0)
      `uvm_info("UART_UVM_TEST_PASS",$sformatf("%s completed with scoreboard checks",get_type_name()),UVM_NONE)
  endfunction
endclass
