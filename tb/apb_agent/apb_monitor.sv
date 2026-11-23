class apb_monitor extends uvm_monitor;
  `uvm_component_utils(apb_monitor)
  virtual apb_if vif;
  uvm_analysis_port #(apb_seq_item) ap;
  int unsigned wait_cycles;

  function new(string name, uvm_component parent);
    super.new(name, parent);
    ap = new("ap", this);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(virtual apb_if)::get(this, "", "vif", vif))
      `uvm_fatal("APB_VIF", "APB virtual interface was not configured")
  endfunction

  task run_phase(uvm_phase phase);
    apb_seq_item item;
    wait_cycles = 0;
    forever begin
      @(posedge vif.clk);
      if (vif.rst_n !== 1'b1 || vif.psel !== 1'b1 || vif.penable !== 1'b1)
        wait_cycles = 0;
      else if (vif.pready === 1'b1) begin
        item = apb_seq_item::type_id::create("observed");
        item.write = vif.pwrite;
        item.addr = vif.paddr;
        item.data = vif.pwdata;
        item.rdata = vif.prdata;
        item.slverr = (vif.pslverr !== 1'b0);
        item.wait_cycles = wait_cycles;
        ap.write(item);
        wait_cycles = 0;
      end else
        wait_cycles++;
    end
  endtask
endclass
