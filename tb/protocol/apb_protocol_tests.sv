class apb_protocol_transfer extends uvm_sequence #(apb_seq_item);
  `uvm_object_utils(apb_protocol_transfer)
  apb_seq_item item;
  function new(string name="apb_protocol_transfer"); super.new(name); endfunction
  task body();
    if(item==null) `uvm_fatal("APB_REQUEST_CONFIG","Transfer requires a request item")
    start_item(item); finish_item(item);
  endtask
endclass

class apb_protocol_base_test extends uvm_test;
  `uvm_component_utils(apb_protocol_base_test)
  apb_agent agent;
  apb_protocol_checker checks;
  virtual apb_if vif;
  virtual apb_protocol_control_if control;
  int unsigned reset_aborts, timeout_aborts;
  bit scenario_done;
  function new(string name,uvm_component parent); super.new(name,parent); endfunction
  virtual function int unsigned timeout_limit(); return 16; endfunction
  virtual function int unsigned minimum_completed(); return 1; endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if(!uvm_config_db#(virtual apb_if)::get(this,"","vif",vif))
      `uvm_fatal("APB_TEST_CONFIG","Test requires apb_if")
    if(!uvm_config_db#(virtual apb_protocol_control_if)::get(this,"","control_vif",control))
      `uvm_fatal("APB_TEST_CONFIG","Test requires programmable slave controls")
    uvm_config_db#(int unsigned)::set(this,"agent.driver","timeout_cycles",timeout_limit());
    agent=apb_agent::type_id::create("agent",this);
    checks=apb_protocol_checker::type_id::create("checker",this);
  endfunction
  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    agent.monitor.ap.connect(checks.bus_in);
  endfunction
  task clocks(int unsigned count); repeat(count) @(negedge vif.clk); endtask
  task configure_slave(int unsigned waits,bit hold=0,bit error_response=0,bit poison=1);
    @(negedge vif.clk);
    control.wait_cycles=waits;
    control.hold_ready=hold;
    control.error_response=error_response;
    control.poison_wait_reads=poison;
  endtask
  task send_request(apb_seq_item request);
    apb_protocol_transfer sequence_handle=apb_protocol_transfer::type_id::create("bus_transfer");
    sequence_handle.item=request;
    sequence_handle.start(agent.sqr);
  endtask
  task access(bit wr,bit[11:0] addr,bit[31:0] value,bit[31:0] expected_read,
              int unsigned waits,bit error_response=0);
    apb_seq_item request=apb_seq_item::type_id::create("request");
    configure_slave(waits,0,error_response);
    checks.expect_transfer(wr,addr,value,expected_read,waits,error_response);
    request.write=wr; request.addr=addr; request.data=value;
    send_request(request);
    if(!request.completed || request.aborted || request.timed_out ||
       request.wait_cycles!=waits || request.slverr!=error_response ||
       (!wr && request.rdata!==expected_read))
      `uvm_error("APB_DRIVER_COMPARE",$sformatf("addr=%h completed=%b aborted=%b timeout=%b wait=%0d/%0d error=%b/%b read=%h/%h",addr,request.completed,request.aborted,request.timed_out,request.wait_cycles,waits,request.slverr,error_response,request.rdata,expected_read))
  endtask
  virtual task scenario();
    access(1,12'h000,32'h12345678,0,0);
    access(0,12'h000,0,32'h12345678,0);
  endtask
  task run_phase(uvm_phase phase);
    phase.raise_objection(this);
    wait(vif.rst_n===1'b1); clocks(2);
    scenario(); clocks(3); scenario_done=1;
    phase.drop_objection(this);
  endtask
  function void check_phase(uvm_phase phase);
    super.check_phase(phase);
    if(checks.completed<minimum_completed())
      `uvm_error("APB_MISSING_CHECKS","Too few independently observed completed transfers")
  endfunction
  function void report_phase(uvm_phase phase);
    uvm_report_server server=uvm_report_server::get_server();
    super.report_phase(phase);
    `uvm_info("APB_AGENT_STATS",$sformatf("test=%s completed=%0d reads=%0d writes=%0d wait0=%0d wait1=%0d wait3=%0d wait7=%0d max_wait=%0d reset_aborts=%0d timeout_aborts=%0d",get_type_name(),checks.completed,checks.reads,checks.writes,checks.wait0,checks.wait1,checks.wait3,checks.wait7,checks.max_wait,reset_aborts,timeout_aborts),UVM_NONE)
    if(scenario_done && server.get_severity_count(UVM_ERROR)==0 && server.get_severity_count(UVM_FATAL)==0)
      `uvm_info("APB_AGENT_TEST_PASS",$sformatf("%s independently checked",get_type_name()),UVM_NONE)
  endfunction
endclass

class apb_wait_state_test extends apb_protocol_base_test;
  `uvm_component_utils(apb_wait_state_test)
  function new(string name,uvm_component parent); super.new(name,parent); endfunction
  function int unsigned minimum_completed(); return 11; endfunction
  task scenario();
    int unsigned waits;
    bit[31:0] value;
    for(int index=0;index<4;index++) begin
      case(index) 0:waits=0; 1:waits=1; 2:waits=3; default:waits=7; endcase
      value=32'ha50000ff ^ (32'(index)*32'h01010101);
      access(1,12'(index*4),value,0,waits);
      access(0,12'(index*4),0,value,waits);
    end
    // Error responses still complete; the independent peripheral contract
    // specifies that an error write does not update its stored location.
    access(0,12'h000,0,32'ha50000ff,1,1);
    access(1,12'h000,32'h76543210,0,3,1);
    access(0,12'h000,0,32'ha50000ff,0);
    if(checks.wait0==0 || checks.wait1==0 || checks.wait3==0 || checks.wait7==0 || checks.max_wait!=7)
      `uvm_error("APB_WAIT_MATRIX","All four wait lengths must be observed on completed transfers")
  endtask
endclass

class apb_reset_abort_test extends apb_protocol_base_test;
  `uvm_component_utils(apb_reset_abort_test)
  function new(string name,uvm_component parent); super.new(name,parent); endfunction
  function int unsigned minimum_completed(); return 4; endfunction
  task scenario();
    apb_seq_item request=apb_seq_item::type_id::create("reset_interrupted_write");
    int unsigned before_abort;
    access(1,12'h004,32'hdead1234,0,1);
    before_abort=checks.completed;
    configure_slave(7);
    request.write=1; request.addr=12'h004; request.data=32'hcafef00d;
    fork
      send_request(request);
      begin
        wait(vif.psel && vif.penable && !vif.pready);
        repeat(2) @(posedge vif.clk);
        @(negedge vif.clk); vif.rst_n=0;
        // No following clock edge has occurred: cancellation must be async.
        #1ps;
        if(!request.aborted || vif.psel!==1'b0 || vif.penable!==1'b0)
          `uvm_error("APB_ASYNC_RESET","Driver did not immediately withdraw a reset-interrupted request")
        clocks(3); vif.rst_n=1;
      end
    join
    if(!request.aborted || request.completed || request.timed_out || request.wait_cycles==0)
      `uvm_error("APB_RESET_ABORT","Reset must produce an incomplete, non-timeout abort")
    reset_aborts++;
    if(checks.completed!=before_abort)
      `uvm_error("APB_ABORT_PUBLISHED","An aborted request appeared on the completion analysis port")
    // The slave reset cleared its memory; the interrupted write was not a
    // completion. Both read and write traffic must recover afterward.
    access(0,12'h004,0,0,3);
    access(1,12'h004,32'h31415926,0,7);
    access(0,12'h004,0,32'h31415926,1);
  endtask
endclass

class apb_timeout_control_test extends apb_protocol_base_test;
  `uvm_component_utils(apb_timeout_control_test)
  function new(string name,uvm_component parent); super.new(name,parent); endfunction
  function int unsigned timeout_limit(); return 8; endfunction
  function int unsigned minimum_completed(); return 2; endfunction
  task scenario();
    access(1,12'h020,32'h10203040,0,7);
    access(0,12'h020,0,32'h10203040,7);
  endtask
endclass

// Explicit negative control. This run must remain raw FAIL with exactly one
// APB_TIMEOUT error. A crash, arbitrary error or swallowed timeout is invalid.
class apb_timeout_requirement_test extends apb_protocol_base_test;
  `uvm_component_utils(apb_timeout_requirement_test)
  function new(string name,uvm_component parent); super.new(name,parent); endfunction
  function int unsigned timeout_limit(); return 8; endfunction
  function int unsigned minimum_completed(); return 3; endfunction
  task scenario();
    apb_seq_item request=apb_seq_item::type_id::create("never_ready_write");
    configure_slave(0,1);
    request.write=1; request.addr=12'h024; request.data=32'hbaddcafe;
    `uvm_info("APB_TIMEOUT_ARMED","mode=hold_ready timeout_cycles=8 address=024",UVM_NONE)
    send_request(request);
    // Timeout cleanup returns on a falling edge. Reset before the next rising
    // sample: APB does not permit silently cancelling a hung access and then
    // issuing another transaction without resetting the peripheral/bus.
    vif.rst_n=0;
    if(!request.aborted || !request.timed_out || request.completed || request.wait_cycles!=8)
      `uvm_error("APB_TIMEOUT_STATUS","The controlled timeout did not return the exact expected abort")
    timeout_aborts++;
    clocks(3); vif.rst_n=1;
    access(0,12'h024,0,0,0);
    access(1,12'h024,32'habcdef12,0,1);
    access(0,12'h024,0,32'habcdef12,3);
    `uvm_info("APB_TIMEOUT_SCENARIO_COMPLETE",$sformatf("test=apb_timeout_requirement_test timeout_wait_cycles=%0d recovery_completed=%0d",request.wait_cycles,checks.completed),UVM_NONE)
  endtask
endclass
