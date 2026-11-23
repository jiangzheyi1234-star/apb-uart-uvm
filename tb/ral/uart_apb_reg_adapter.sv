// Independently authored APB adapter. The driver returns completion in the
// original request object rather than publishing a separate response item.
class uart_apb_reg_adapter extends uvm_reg_adapter;
  `uvm_object_utils(uart_apb_reg_adapter)

  function new(string name="uart_apb_reg_adapter");
    super.new(name);
    supports_byte_enable=0;
    provides_responses=0;
  endfunction

  virtual function uvm_sequence_item reg2bus(const ref uvm_reg_bus_op rw);
    apb_seq_item item=apb_seq_item::type_id::create("ral_apb_request");
    item.write=(rw.kind==UVM_WRITE);
    item.addr=rw.addr[11:0];
    item.data=rw.data[31:0];
    return item;
  endfunction

  virtual function void bus2reg(uvm_sequence_item bus_item, ref uvm_reg_bus_op rw);
    apb_seq_item item;
    if(!$cast(item,bus_item)) begin
      rw.status=UVM_NOT_OK;
      `uvm_fatal("RAL_ADAPTER_TYPE","Expected an apb_seq_item")
      return;
    end
    rw.kind=item.write?UVM_WRITE:UVM_READ;
    rw.addr=uvm_reg_addr_t'(item.addr);
    rw.data=uvm_reg_data_t'(item.write?item.data:item.rdata);
    rw.n_bits=32;
    rw.byte_en='1;
    rw.status=(item.aborted || item.slverr || (!item.write && $isunknown(item.rdata)))?UVM_NOT_OK:UVM_IS_OK;
  endfunction
endclass
