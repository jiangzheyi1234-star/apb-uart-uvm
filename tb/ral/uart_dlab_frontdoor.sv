// Addresses 0/1 change meaning with LCR.DLAB. A banked register operation is
// an atomic bus sequence: read LCR, select bank, access target, restore LCR.
// Reading the actual LCR avoids relying on a possibly stale software mirror.
class uart_dlab_frontdoor extends uvm_reg_frontdoor;
  `uvm_object_utils(uart_dlab_frontdoor)
  uart_apb_reg_adapter apb_adapter;
  bit required_dlab;
  bit [11:0] target_address;

  function new(string name="uart_dlab_frontdoor");
    super.new(name);
  endfunction

  task physical_access(uvm_access_e kind, bit [11:0] address,
                       inout uvm_reg_data_t value, output uvm_status_e status);
    uvm_reg_bus_op operation;
    uvm_sequence_item generic_item;
    apb_seq_item item;
    operation.kind=kind;
    operation.addr=uvm_reg_addr_t'(address);
    operation.data=value;
    operation.n_bits=8;
    operation.byte_en='1;
    operation.status=UVM_NOT_OK;
    generic_item=apb_adapter.reg2bus(operation);
    if(!$cast(item,generic_item))
      `uvm_fatal("RAL_FRONTDOOR_TYPE","Adapter returned a non-APB request")
    start_item(item);
    finish_item(item);
    apb_adapter.bus2reg(item,operation);
    value=operation.data;
    status=operation.status;
  endtask

  virtual task body();
    uvm_reg_data_t saved_lcr, selected_lcr, transfer_value;
    uvm_status_e step_status, target_status, restore_status;
    bit changed_bank;
    if(apb_adapter==null || rw_info==null)
      `uvm_fatal("RAL_FRONTDOOR_CFG","Frontdoor requires an adapter and register operation")
    if(sequencer==null) sequencer=get_sequencer();
    if(sequencer==null)
      `uvm_fatal("RAL_FRONTDOOR_CFG","Frontdoor requires the APB sequencer")
    rw_info.status=UVM_NOT_OK;
    target_status=UVM_NOT_OK;
    changed_bank=0;
    lock(sequencer);
    saved_lcr='0;
    physical_access(UVM_READ,12'h003,saved_lcr,step_status);
    if(step_status==UVM_IS_OK) begin
      selected_lcr=saved_lcr;
      selected_lcr[7]=required_dlab;
      if(selected_lcr!=saved_lcr) begin
        physical_access(UVM_WRITE,12'h003,selected_lcr,step_status);
        changed_bank=(step_status==UVM_IS_OK);
      end
      if(step_status==UVM_IS_OK) begin
        transfer_value=rw_info.value[0];
        physical_access(rw_info.kind,target_address,transfer_value,target_status);
        if(rw_info.kind==UVM_READ && target_status==UVM_IS_OK)
          rw_info.value[0]=transfer_value;
      end
      // An error on the target transfer must still release the lock and try
      // to restore the previous bank/format before returning a failed status.
      if(changed_bank) begin
        physical_access(UVM_WRITE,12'h003,saved_lcr,restore_status);
        if(restore_status!=UVM_IS_OK) target_status=UVM_NOT_OK;
      end
      rw_info.status=target_status;
    end
    unlock(sequencer);
  endtask
endclass
