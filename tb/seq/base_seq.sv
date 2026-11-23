class apb_access_seq extends uvm_sequence#(apb_seq_item);
  `uvm_object_utils(apb_access_seq)
  bit wr;
  bit[11:0] address;
  bit[31:0] value;
  logic[31:0] read_value;
  function new(string name="apb_access_seq"); super.new(name); endfunction
  task body();
    apb_seq_item req=apb_seq_item::type_id::create("req");
    start_item(req); req.write=wr; req.addr=address; req.data=value; finish_item(req);
    if(req.aborted) `uvm_fatal("ABORTED_APB","Unexpected reset aborted APB request")
    read_value=req.rdata;
  endtask
endclass
class uart_send_seq extends uvm_sequence#(uart_seq_item);
  `uvm_object_utils(uart_send_seq)
  bit[7:0] value;
  bit bad_parity,bad_stop;
  function new(string name="uart_send_seq"); super.new(name); endfunction
  task body();
    uart_seq_item req=uart_seq_item::type_id::create("req");
    start_item(req); req.data=value; req.parity_error=bad_parity; req.framing_error=bad_stop; finish_item(req);
  endtask
endclass
