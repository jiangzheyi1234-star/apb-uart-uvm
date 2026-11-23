class uart_seq_item extends uvm_sequence_item;
  rand bit [7:0] data;
  rand bit parity_error;
  rand bit framing_error;
  logic sampled_parity;
  bit aborted;
  int unsigned epoch;
  time start_time;
  time end_time;

  constraint default_clean_frame {
    soft parity_error == 0;
    soft framing_error == 0;
  }

  `uvm_object_utils_begin(uart_seq_item)
    `uvm_field_int(data, UVM_DEFAULT | UVM_HEX)
    `uvm_field_int(parity_error, UVM_DEFAULT)
    `uvm_field_int(framing_error, UVM_DEFAULT)
    `uvm_field_int(sampled_parity, UVM_DEFAULT)
    `uvm_field_int(aborted, UVM_DEFAULT)
    `uvm_field_int(epoch, UVM_DEFAULT)
    `uvm_field_int(start_time, UVM_DEFAULT)
    `uvm_field_int(end_time, UVM_DEFAULT)
  `uvm_object_utils_end

  function new(string name = "uart_seq_item");
    super.new(name);
  endfunction
endclass
