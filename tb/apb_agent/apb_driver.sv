class apb_driver extends uvm_driver #(apb_seq_item);
  `uvm_component_utils(apb_driver)
  virtual apb_if vif;
  int unsigned timeout_cycles = 64;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(virtual apb_if)::get(this, "", "vif", vif))
      `uvm_fatal("APB_VIF", "APB virtual interface was not configured")
  endfunction

  function void idle_bus();
    vif.psel = 0;
    vif.penable = 0;
    vif.pwrite = 0;
    vif.paddr = '0;
    vif.pwdata = '0;
  endfunction

  task transfer(apb_seq_item item);
    item.wait_cycles = 0;
    item.slverr = 0;
    item.aborted = 0;
    item.rdata = '0;
    wait (vif.rst_n === 1'b1);
    @(negedge vif.clk);
    if (vif.rst_n !== 1'b1) begin
      item.aborted = 1;
      return;
    end
    vif.psel = 1;
    vif.penable = 0;
    vif.pwrite = item.write;
    vif.paddr = item.addr;
    vif.pwdata = item.data;
    @(negedge vif.clk);
    if (vif.rst_n !== 1'b1) begin
      item.aborted = 1;
      idle_bus();
      return;
    end
    vif.penable = 1;
    // Outputs are sampled before the DUT's sequential NBA updates.
    forever begin
      @(posedge vif.clk);
      if (vif.rst_n !== 1'b1) begin
        item.aborted = 1;
        break;
      end
      if (vif.pready === 1'b1) begin
        item.rdata = vif.prdata;
        item.slverr = (vif.pslverr !== 1'b0);
        break;
      end
      item.wait_cycles++;
      if (item.wait_cycles >= timeout_cycles) begin
        item.aborted = 1;
        `uvm_error("APB_TIMEOUT", $sformatf("No PREADY at address 0x%03h", item.addr))
        break;
      end
    end
    @(negedge vif.clk);
    idle_bus();
  endtask

  task run_phase(uvm_phase phase);
    idle_bus();
    forever begin
      seq_item_port.get_next_item(req);
      transfer(req);
      seq_item_port.item_done();
    end
  endtask
endclass
