// Explicit prediction follows the actual completed APB stream. The selected
// bank changes only after an observed LCR transfer, not when a RAL API is called.
class uart_bank_predictor extends uvm_reg_predictor #(apb_seq_item);
  `uvm_component_utils(uart_bank_predictor)
  uart_reg_block regmodel;
  virtual apb_if vif;
  bit observed_dlab;
  int unsigned normal_predictions, banked_predictions, resets_seen;

  function new(string name,uvm_component parent);
    super.new(name,parent);
  endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if(!uvm_config_db#(virtual apb_if)::get(this,"","vif",vif))
      `uvm_fatal("RAL_PREDICTOR_VIF","Bank-aware predictor requires apb_if")
  endfunction
  task run_phase(uvm_phase phase);
    wait(vif.rst_n===1'b0);
    forever begin
      if(regmodel==null)
        `uvm_fatal("RAL_PREDICTOR_CFG","Bank-aware predictor requires a register block")
      regmodel.reset("HARD");
      observed_dlab=0;
      resets_seen++;
      @(posedge vif.rst_n);
      @(negedge vif.rst_n);
    end
  endtask

  virtual function void write(apb_seq_item tr);
    apb_seq_item canonical;
    uvm_reg_bus_op operation;
    if(tr.aborted || vif.rst_n!==1'b1) return;
    if(regmodel==null || adapter==null)
      `uvm_fatal("RAL_PREDICTOR_CFG","Register block/adapter was not connected")
    canonical=apb_seq_item::type_id::create("canonical_observation");
    canonical.copy(tr);
    // High APB address bits are aliases, not a different register space.
    canonical.addr={9'b0,tr.addr[2:0]};
    adapter.bus2reg(canonical,operation);
    if(operation.status!=UVM_IS_OK) begin
      `uvm_error("RAL_PREDICTOR_BUS","Failed bus transfer must not update a register mirror")
      return;
    end
    map=observed_dlab?regmodel.banked_map:regmodel.normal_map;
    // Addresses outside this scoped model include destructive FIFO reads and
    // writes. They deliberately do not participate in automatic prediction.
    if(map.get_reg_by_offset(operation.addr,operation.kind==UVM_READ)==null) return;
    if(observed_dlab) banked_predictions++; else normal_predictions++;
    super.write(canonical);
    if(canonical.addr==12'h003)
      observed_dlab=canonical.write?canonical.data[7]:canonical.rdata[7];
  endfunction
endclass
