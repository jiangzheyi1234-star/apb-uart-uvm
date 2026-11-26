class subsystem_apb_transfer extends uvm_sequence #(apb_seq_item);
  `uvm_object_utils(subsystem_apb_transfer)
  apb_seq_item item;
  function new(string name="subsystem_apb_transfer"); super.new(name); endfunction
  task body(); start_item(item); finish_item(item); endtask
endclass

class subsystem_uart_transfer extends uvm_sequence #(uart_seq_item);
  `uvm_object_utils(subsystem_uart_transfer)
  bit [7:0] value;
  function new(string name="subsystem_uart_transfer"); super.new(name); endfunction
  task body();
    uart_seq_item item=uart_seq_item::type_id::create("serial_request");
    start_item(item); item.data=value; item.parity_error=0; item.framing_error=0;
    finish_item(item);
    if(item.aborted) `uvm_error("SUBSYSTEM_UART_ABORT","Unexpected UART request abort")
  endtask
endclass

class subsystem_base_test extends uvm_test;
  `uvm_component_utils(subsystem_base_test)
  localparam bit [11:0] START=12'h080, STATUS=12'h084, FAIL_ADDR=12'h088,
                        EXPECTED=12'h08c, ACTUAL=12'h090, FAIL_STEP=12'h094;
  apb_agent agent;
  uart_agent uart;
  uart_config cfg;
  subsystem_checker checks;
  virtual apb_if vif;
  virtual uart_if uart_vif;
  virtual subsystem_control_if control;
  int unsigned mbist_starts, mbist_passes, mbist_faults, reset_aborts;
  int unsigned host_reset_aborts;
  int unsigned uart_rbr_checks;
  bit [31:0] stimulus_checksum;
  bit scenario_done;
  function new(string name,uvm_component parent); super.new(name,parent); endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if(!uvm_config_db#(virtual apb_if)::get(this,"","vif",vif) ||
       !uvm_config_db#(virtual uart_if)::get(this,"","uart_vif",uart_vif) ||
       !uvm_config_db#(virtual subsystem_control_if)::get(this,"","control_vif",control))
      `uvm_fatal("SUBSYSTEM_CONFIG","Missing subsystem test interfaces")
    cfg=uart_config::type_id::create("cfg");
    uvm_config_db#(uart_config)::set(this,"uart*","cfg",cfg);
    agent=apb_agent::type_id::create("agent",this);
    uart=uart_agent::type_id::create("uart",this);
    checks=subsystem_checker::type_id::create("checker",this);
  endfunction
  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    agent.monitor.ap.connect(checks.apb_in);
    uart.tx_monitor.ap.connect(checks.tx_in);
    uart.rx_monitor.ap.connect(checks.rx_in);
  endfunction
  task clocks(int unsigned n); repeat(n) @(negedge vif.clk); endtask
  task access(bit wr,bit[11:0] addr,bit[31:0] value,output logic[31:0] result,
              input bit error_response=0,input bit[31:0] expected_read=0,input bit[31:0] mask=0);
    apb_seq_item request=apb_seq_item::type_id::create("request");
    subsystem_apb_transfer seq=subsystem_apb_transfer::type_id::create("bus_transfer");
    int unsigned waits;
    waits=(!wr && !error_response && addr>=12'h100 && addr<=12'h1fc)?1:0;
    checks.expect_access(wr,addr,value,expected_read,mask,waits,error_response);
    request.write=wr; request.addr=addr; request.data=value; seq.item=request;
    seq.start(agent.sqr); result=request.rdata;
    if(!request.completed || request.aborted || request.timed_out ||
       request.slverr!=error_response || request.wait_cycles!=waits ||
       (!wr && (request.rdata & mask)!==(expected_read & mask)))
      `uvm_error("SUBSYSTEM_DRIVER_COMPARE",$sformatf("addr=%03h completed=%b aborted=%b timeout=%b wait=%0d/%0d error=%b/%b read=%08h/%08h mask=%08h",addr,request.completed,request.aborted,request.timed_out,request.wait_cycles,waits,request.slverr,error_response,request.rdata,expected_read,mask))
  endtask
  task wr(bit[11:0] addr,bit[31:0] value,bit error_response=0);
    logic[31:0] unused_result;
    access(1,addr,value,unused_result,error_response);
  endtask
  task rd(bit[11:0] addr,output logic[31:0] value);
    access(0,addr,0,value);
  endtask
  task read_exact(bit[11:0] addr,bit[31:0] expected_value);
    logic[31:0] value;
    access(0,addr,0,value,0,expected_value,'1);
  endtask
  task status_is(bit[2:0] expected_status);
    logic[31:0] value;
    access(0,STATUS,0,value,0,32'(expected_status),'1);
  endtask
  task ram_write(int unsigned index,bit[31:0] value);
    wr(12'('h100+4*index),value);
    stimulus_checksum={stimulus_checksum[26:0],stimulus_checksum[31:27]} ^ value ^ 32'(index);
  endtask
  task ram_read(int unsigned index);
    if(!checks.ram_valid[index]) `uvm_fatal("SUBSYSTEM_MODEL","Read of uninitialized reference word")
    read_exact(12'('h100+4*index),checks.ram_model[index]);
  endtask
  task seeded_ram_roundtrip(int unsigned operations=24);
    int unsigned index;
    bit[31:0] value;
    ram_write(0,32'h00000008); ram_write(63,32'hfffffffe);
    ram_read(0); ram_read(63);
    for(int unsigned n=0;n<operations;n++) begin
      index=$urandom_range(0,63); value=$urandom();
      ram_write(index,value); ram_read(index);
    end
  endtask
  task configure_uart();
    // Fixed 8N1/divisor31 is independent of the MBIST control register bank.
    wr(12'h003,32'h83); wr(12'h000,31); wr(12'h001,0);
    wr(12'h003,3); wr(12'h002,7); wr(12'h001,1);
  endtask
  task uart_exchange(bit[7:0] tx_value,bit[7:0] rx_value);
    subsystem_uart_transfer seq=subsystem_uart_transfer::type_id::create("rx_injection");
    logic[31:0] lsr;
    int unsigned before_tx, before_rx;
    before_tx=checks.tx_count; before_rx=checks.rx_count;
    checks.expected_tx.push_back(tx_value); checks.expected_rx.push_back(rx_value);
    seq.value=rx_value;
    fork
      seq.start(uart.sqr);
      wr(12'h000,32'(tx_value));
    join
    for(int unsigned n=0;n<64 && (checks.tx_count==before_tx || checks.rx_count==before_rx);n++) clocks(1);
    if(checks.tx_count!=before_tx+1 || checks.rx_count!=before_rx+1)
      `uvm_error("SUBSYSTEM_UART_PROGRESS","Both serial directions must complete")
    rd(12'h005,lsr);
    if((lsr & 32'h0d)!==32'h01 || uart_vif.irq!==1'b1)
      `uvm_error("SUBSYSTEM_UART_STATUS",$sformatf("RX ready/clean interrupt missing LSR=%08h IRQ=%b",lsr,uart_vif.irq))
    read_exact(12'h000,32'(rx_value)); uart_rbr_checks++;
    clocks(2);
    if(uart_vif.irq!==1'b0) `uvm_error("SUBSYSTEM_UART_IRQ_CLEAR","RX pop must clear enabled receive interrupt")
  endtask
  task start_mbist();
    checks.invalidate_ram(); wr(START,1); mbist_starts++;
    status_is(3'b001);
  endtask
  task wait_mbist(bit expect_failure);
    logic[31:0] status_value;
    bit finished;
    finished=0;
    for(int unsigned poll=0;poll<512;poll++) begin
      access(0,STATUS,0,status_value,0,0,32'hfffffff8);
      if(status_value[0]===1'b0) begin finished=1; break; end
      clocks(1);
    end
    if(!finished) `uvm_fatal("SUBSYSTEM_MBIST_TIMEOUT","MBIST failed to release RAM within bounded polling window")
    if(status_value!==32'(expect_failure?6:2))
      `uvm_error("SUBSYSTEM_MBIST_RESULT",$sformatf("actual=%08h expected=%08h",status_value,expect_failure?6:2))
    if(expect_failure) mbist_faults++;
    else begin mbist_passes++; checks.expect_mbist_zeroes(); end
    `uvm_info("SUBSYSTEM_MBIST_RESULT",$sformatf("expected_failure=%b status=%08h",expect_failure,status_value),UVM_NONE)
  endtask
  task verify_zero_memory();
    for(int unsigned index=0;index<64;index++) ram_read(index);
  endtask
  task check_busy_rejections();
    logic[31:0] ignored;
    access(0,12'h100,0,ignored,1);
    wr(12'h1fc,32'hdeadbeef,1);
    wr(START,1,1);
    // Zero is explicitly a no-op, even while busy.
    wr(START,0); status_is(3'b001);
  endtask
  task abort_host_read();
    apb_seq_item request=apb_seq_item::type_id::create("interrupted_ram_read");
    subsystem_apb_transfer seq=subsystem_apb_transfer::type_id::create("interrupted_bus_transfer");
    int unsigned before_count;
    ram_write(0,32'h13579bdf);
    before_count=checks.completed;
    request.write=0; request.addr=12'h100; request.data=0; seq.item=request;
    // No completion is expected for this transfer. Reset after the native RAM
    // read issue but before its APB response may complete on the next edge.
    fork
      seq.start(agent.sqr);
      begin
        wait(vif.psel && vif.penable && !vif.pready);
        @(posedge vif.clk); #2ns; vif.rst_n=0; cfg.epoch++;
        #1ps;
        if(!request.aborted || vif.psel!==1'b0 || vif.penable!==1'b0 || control.ram_en!==1'b0)
          `uvm_error("SUBSYSTEM_HOST_RESET","Pending RAM read was not cancelled asynchronously")
        clocks(4); vif.rst_n=1;
      end
    join
    if(!request.aborted || request.completed || request.timed_out || request.wait_cycles!=1 ||
       checks.completed!=before_count)
      `uvm_error("SUBSYSTEM_HOST_ABORT_STATUS","Aborted RAM read must have one wait and no completion")
    host_reset_aborts++;
    // RAM contents survive reset, but the pending response does not. This
    // fresh read must independently issue and complete with one new wait.
    ram_read(0); status_is(0);
  endtask
  virtual task scenario(); seeded_ram_roundtrip(); uart_exchange(8'ha6,8'h59); endtask
  task run_phase(uvm_phase phase);
    phase.raise_objection(this);
    wait(vif.rst_n===1'b1); clocks(2);
    control.fault_enable=0; checks.invalidate_ram();
    status_is(0); configure_uart(); scenario();
    clocks(3); scenario_done=1;
    phase.drop_objection(this);
  endtask
  function void check_phase(uvm_phase phase);
    super.check_phase(phase);
    if(checks.completed<12 || checks.ram_reads<2 || checks.ram_writes<2 ||
       checks.tx_count<1 || checks.rx_count<1 || uart_rbr_checks<1 ||
       checks.wait0==0 || checks.wait1==0 || checks.max_wait!=1)
      `uvm_error("SUBSYSTEM_MISSING_CHECKS","Required RAM, wait-state or UART checks were not exercised")
  endfunction
  function void report_phase(uvm_phase phase);
    uvm_report_server server=uvm_report_server::get_server();
    super.report_phase(phase);
    `uvm_info("SUBSYSTEM_STATS",$sformatf("test=%s apb_completed=%0d reads=%0d writes=%0d errors=%0d wait0=%0d wait1=%0d ram_reads=%0d ram_writes=%0d tx=%0d rx=%0d rbr_checks=%0d mbist_starts=%0d mbist_passes=%0d mbist_faults=%0d reset_aborts=%0d host_reset_aborts=%0d stimulus_checksum=%08h",get_type_name(),checks.completed,checks.reads,checks.writes,checks.error_responses,checks.wait0,checks.wait1,checks.ram_reads,checks.ram_writes,checks.tx_count,checks.rx_count,uart_rbr_checks,mbist_starts,mbist_passes,mbist_faults,reset_aborts,host_reset_aborts,stimulus_checksum),UVM_NONE)
    if(scenario_done && server.get_severity_count(UVM_ERROR)==0 && server.get_severity_count(UVM_FATAL)==0)
      `uvm_info("SUBSYSTEM_UVM_TEST_PASS",$sformatf("%s independently checked",get_type_name()),UVM_NONE)
  endfunction
endclass

class subsystem_apb_test extends subsystem_base_test;
  `uvm_component_utils(subsystem_apb_test)
  function new(string name,uvm_component parent); super.new(name,parent); endfunction
  task scenario();
    logic[31:0] ignored;
    for(int unsigned index=0;index<64;index++) ram_write(index,$urandom());
    for(int unsigned index=0;index<64;index++) ram_read(index);
    seeded_ram_roundtrip(32);
    // Byte aliases are confined to UART 0..7, with no RAM wraparound.
    access(0,12'h008,0,ignored,1); access(0,12'h07f,0,ignored,1);
    access(0,12'h098,0,ignored,1); access(0,12'h0fc,0,ignored,1);
    access(0,12'h200,0,ignored,1); access(0,12'hffc,0,ignored,1);
    access(0,12'h101,0,ignored,1); wr(12'h1ff,32'h12345678,1);
    access(0,START,0,ignored,1);
    wr(STATUS,'1,1); wr(FAIL_ADDR,'1,1); wr(EXPECTED,'1,1);
    wr(ACTUAL,'1,1); wr(FAIL_STEP,'1,1);
    wr(START,0); status_is(0); ram_read(0); ram_read(63);
    read_exact(FAIL_ADDR,0); read_exact(EXPECTED,0); read_exact(ACTUAL,0); read_exact(FAIL_STEP,0);
    uart_exchange(8'h96,8'h69);
  endtask
endclass

class subsystem_mbist_test extends subsystem_base_test;
  `uvm_component_utils(subsystem_mbist_test)
  function new(string name,uvm_component parent); super.new(name,parent); endfunction
  task scenario();
    seeded_ram_roundtrip(8); start_mbist(); check_busy_rejections();
    uart_exchange(8'ha5,8'h5a); status_is(3'b001);
    wait_mbist(0); status_is(3'b010);
    read_exact(FAIL_ADDR,0); read_exact(EXPECTED,0); read_exact(ACTUAL,0); read_exact(FAIL_STEP,0);
    verify_zero_memory(); seeded_ram_roundtrip(8); status_is(3'b010);
  endtask
endclass

class subsystem_mbist_fault_test extends subsystem_base_test;
  `uvm_component_utils(subsystem_mbist_fault_test)
  function new(string name,uvm_component parent); super.new(name,parent); endfunction
  task scenario();
    seeded_ram_roundtrip(4);
    @(negedge vif.clk); control.fault_enable=1;
    start_mbist(); wait_mbist(1); status_is(3'b110);
    read_exact(FAIL_ADDR,63); read_exact(EXPECTED,32'hffffffff);
    read_exact(ACTUAL,32'hfffffff7); read_exact(FAIL_STEP,2);
    clocks(4); status_is(3'b110);
    `uvm_info("SUBSYSTEM_FAULT_CHECK","word=63 step=2 expected=ffffffff actual=fffffff7 fault=read_bit3_stuck_zero",UVM_NONE)
    @(negedge vif.clk); control.fault_enable=0;
    // A read-return impairment must not modify the production memory array.
    read_exact(12'h1fc,32'hffffffff);
    start_mbist(); check_busy_rejections();
    uart_exchange(8'hc3,8'h3c); status_is(3'b001);
    wait_mbist(0); verify_zero_memory();
    read_exact(FAIL_ADDR,0); read_exact(EXPECTED,0); read_exact(ACTUAL,0); read_exact(FAIL_STEP,0);
    seeded_ram_roundtrip(4);
  endtask
endclass

class subsystem_mbist_reset_test extends subsystem_base_test;
  `uvm_component_utils(subsystem_mbist_reset_test)
  function new(string name,uvm_component parent); super.new(name,parent); endfunction
  task scenario();
    seeded_ram_roundtrip(4); abort_host_read(); start_mbist(); clocks(80); status_is(3'b001);
    @(negedge vif.clk); #2ns; vif.rst_n=0; cfg.epoch++;
    #1ps;
    if(control.ram_en!==1'b0)
      `uvm_error("SUBSYSTEM_RESET_OWNERSHIP","Async reset did not release native RAM ownership")
    reset_aborts++; checks.invalidate_ram();
    clocks(4); vif.rst_n=1; clocks(2);
    status_is(0); read_exact(FAIL_ADDR,0); read_exact(EXPECTED,0);
    read_exact(ACTUAL,0); read_exact(FAIL_STEP,0);
    // No RAM reset value is assumed: establish new contents through APB.
    seeded_ram_roundtrip(4); configure_uart(); start_mbist();
    uart_exchange(8'hf0,8'h0f); status_is(3'b001);
    wait_mbist(0); verify_zero_memory(); seeded_ram_roundtrip(4);
  endtask
endclass
