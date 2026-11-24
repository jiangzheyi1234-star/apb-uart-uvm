class apb_seq_item extends uvm_sequence_item;
  rand bit write;
  rand bit [11:0] addr;
  rand bit [31:0] data;
  logic [31:0] rdata;
  bit slverr;
  bit aborted;
  bit completed;
  bit timed_out;
  int unsigned wait_cycles;

  `uvm_object_utils_begin(apb_seq_item)
    `uvm_field_int(write, UVM_DEFAULT)
    `uvm_field_int(addr, UVM_DEFAULT | UVM_HEX)
    `uvm_field_int(data, UVM_DEFAULT | UVM_HEX)
    `uvm_field_int(rdata, UVM_DEFAULT | UVM_HEX)
    `uvm_field_int(slverr, UVM_DEFAULT)
    `uvm_field_int(aborted, UVM_DEFAULT)
    `uvm_field_int(completed, UVM_DEFAULT)
    `uvm_field_int(timed_out, UVM_DEFAULT)
    `uvm_field_int(wait_cycles, UVM_DEFAULT)
  `uvm_object_utils_end

  function new(string name = "apb_seq_item");
    super.new(name);
  endfunction
endclass
