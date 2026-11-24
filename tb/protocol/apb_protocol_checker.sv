// Two independent observations: the passive agent publishes completed items;
// this checker also samples the raw protocol phases and wait-state controls.
class apb_protocol_checker extends uvm_component;
  `uvm_component_utils(apb_protocol_checker)
  virtual apb_if vif;
  uvm_analysis_imp #(apb_seq_item,apb_protocol_checker) bus_in;
  apb_seq_item expected[$];
  int unsigned completed, reads, writes, wait0, wait1, wait3, wait7, max_wait;
  bit previous_selected, previous_wait, previous_complete;
  logic [44:0] previous_controls;

  function new(string name,uvm_component parent);
    super.new(name,parent);
    bus_in=new("bus_in",this);
  endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if(!uvm_config_db#(virtual apb_if)::get(this,"","vif",vif))
      `uvm_fatal("APB_CHECKER_CONFIG","Independent checker requires apb_if")
  endfunction
  function void expect_transfer(bit wr,bit[11:0] addr,bit[31:0] data,
                                bit[31:0] read_value,int unsigned stalls,bit error_response);
    apb_seq_item plan=apb_seq_item::type_id::create("expected_transfer");
    plan.write=wr; plan.addr=addr; plan.data=data; plan.rdata=read_value;
    plan.wait_cycles=stalls; plan.slverr=error_response;
    expected.push_back(plan);
  endfunction
  function void write(apb_seq_item tr);
    apb_seq_item plan;
    if(expected.size()==0) begin
      `uvm_error("APB_UNEXPECTED_COMPLETION","Monitor published an unplanned or aborted transfer")
      return;
    end
    plan=expected.pop_front();
    if(!tr.completed || tr.aborted || tr.timed_out)
      `uvm_error("APB_MONITOR_STATUS","Completed observation has inconsistent completion flags")
    if(tr.write!=plan.write || tr.addr!=plan.addr || tr.data!=plan.data ||
       tr.slverr!=plan.slverr || tr.wait_cycles!=plan.wait_cycles ||
       (!tr.write && tr.rdata!==plan.rdata))
      `uvm_error("APB_MONITOR_COMPARE",$sformatf("addr=%h wait=%0d/%0d error=%b/%b read=%h/%h",tr.addr,tr.wait_cycles,plan.wait_cycles,tr.slverr,plan.slverr,tr.rdata,plan.rdata))
    completed++;
    if(tr.write) writes++; else reads++;
    case(tr.wait_cycles) 0:wait0++; 1:wait1++; 3:wait3++; 7:wait7++; default:; endcase
    if(tr.wait_cycles>max_wait) max_wait=tr.wait_cycles;
  endfunction
  function void clear_phase_history();
    previous_selected=0; previous_wait=0; previous_complete=0;
    previous_controls='0;
  endfunction
  function void check_cycle();
    logic [44:0] controls;
    controls={vif.paddr,vif.pwrite,vif.pwdata};
    if(vif.rst_n!==1'b1) begin clear_phase_history(); return; end
    if(vif.penable && !vif.psel)
      `uvm_error("APB_PHASE","PENABLE without PSEL")
    if(previous_wait && (!vif.psel || !vif.penable))
      `uvm_error("APB_WAIT_ABANDONED","Access was withdrawn before PREADY without reset")
    if(vif.psel && vif.penable) begin
      if(!previous_selected || previous_complete)
        `uvm_error("APB_SETUP","Access did not follow SETUP or an extended wait")
      if(previous_selected && controls!==previous_controls)
        `uvm_error("APB_CONTROL_STABILITY","Address/direction/write data changed between SETUP/access or during wait")
      if($isunknown({vif.pready,vif.pslverr}))
        `uvm_error("APB_RESPONSE_UNKNOWN","Unknown response control in an active access")
    end
    previous_selected=vif.psel;
    previous_wait=vif.psel && vif.penable && vif.pready===1'b0;
    previous_complete=vif.psel && vif.penable && vif.pready===1'b1;
    previous_controls=controls;
  endfunction
  task run_phase(uvm_phase phase);
    clear_phase_history();
    fork
      forever begin @(negedge vif.rst_n); clear_phase_history(); end
      forever begin @(posedge vif.clk); check_cycle(); end
    join
  endtask
  function void check_phase(uvm_phase phase);
    super.check_phase(phase);
    if(expected.size()!=0)
      `uvm_error("APB_PENDING",$sformatf("%0d expected transfers were not observed",expected.size()))
  endfunction
endclass
