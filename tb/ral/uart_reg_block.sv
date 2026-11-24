// A deliberately scoped model of the four implemented stored RW registers.
// FIFO ports and status/control aliases are verified by transaction-level tests,
// not mirrored as ordinary storage registers.
class uart_byte_reg extends uvm_reg;
  `uvm_object_utils(uart_byte_reg)
  uvm_reg_field value;
  function new(string name="uart_byte_reg");
    super.new(name,8,UVM_NO_COVERAGE);
  endfunction
  virtual function void build();
    value=uvm_reg_field::type_id::create("value");
    value.configure(this,8,0,"RW",0,0,1,0,0);
  endfunction
endclass

class uart_lcr_reg extends uvm_reg;
  `uvm_object_utils(uart_lcr_reg)
  uvm_reg_field word_length, stop_select, parity_enable, stored_format_bits, dlab;
  function new(string name="uart_lcr_reg");
    super.new(name,8,UVM_NO_COVERAGE);
  endfunction
  virtual function void build();
    word_length=uvm_reg_field::type_id::create("word_length");
    stop_select=uvm_reg_field::type_id::create("stop_select");
    parity_enable=uvm_reg_field::type_id::create("parity_enable");
    stored_format_bits=uvm_reg_field::type_id::create("stored_format_bits");
    dlab=uvm_reg_field::type_id::create("dlab");
    word_length.configure(this,2,0,"RW",0,0,1,0,0);
    stop_select.configure(this,1,2,"RW",0,0,1,0,0);
    parity_enable.configure(this,1,3,"RW",0,0,1,0,0);
    // These bits are stored by this RTL, but odd/stick parity is not implemented.
    stored_format_bits.configure(this,3,4,"RW",0,0,1,0,0);
    dlab.configure(this,1,7,"RW",0,0,1,0,0);
  endfunction
endclass

class uart_reg_block extends uvm_reg_block;
  `uvm_object_utils(uart_reg_block)
  uart_byte_reg ier, dll, dlm;
  uart_lcr_reg lcr;
  uvm_reg_map normal_map, banked_map;
  uart_dlab_frontdoor ier_frontdoor, dll_frontdoor, dlm_frontdoor;

  function new(string name="uart_reg_block");
    super.new(name,UVM_NO_COVERAGE);
  endfunction

  virtual function void build();
    ier=uart_byte_reg::type_id::create("ier"); ier.configure(this); ier.build();
    dll=uart_byte_reg::type_id::create("dll"); dll.configure(this); dll.build();
    dlm=uart_byte_reg::type_id::create("dlm"); dlm.configure(this); dlm.build();
    lcr=uart_lcr_reg::type_id::create("lcr"); lcr.configure(this); lcr.build();
    // The physical APB bus is 32 bits; register offsets are byte addresses,
    // including the unusual consecutive byte offsets 0/1/3 of this controller.
    normal_map=create_map("normal_map",0,4,UVM_LITTLE_ENDIAN,1);
    banked_map=create_map("banked_map",0,4,UVM_LITTLE_ENDIAN,1);
    default_map=normal_map;
    ier_frontdoor=uart_dlab_frontdoor::type_id::create("ier_frontdoor");
    dll_frontdoor=uart_dlab_frontdoor::type_id::create("dll_frontdoor");
    dlm_frontdoor=uart_dlab_frontdoor::type_id::create("dlm_frontdoor");
    ier_frontdoor.required_dlab=0; ier_frontdoor.target_address=12'h001;
    dll_frontdoor.required_dlab=1; dll_frontdoor.target_address=12'h000;
    dlm_frontdoor.required_dlab=1; dlm_frontdoor.target_address=12'h001;
    // Bind frontdoors while adding registers. set_frontdoor() queries map
    // information that UVM initializes only when the top block is locked;
    // calling it here would query an unfinished map and emit RegModel warnings.
    // Keep unmapped=0: the passive predictor still needs these byte offsets.
    normal_map.add_reg(ier,1,"RW",0,ier_frontdoor);
    normal_map.add_reg(lcr,3,"RW");
    banked_map.add_reg(dll,0,"RW",0,dll_frontdoor);
    banked_map.add_reg(dlm,1,"RW",0,dlm_frontdoor);
    banked_map.add_reg(lcr,3,"RW");
    normal_map.set_auto_predict(0); banked_map.set_auto_predict(0);
  endfunction
endclass
