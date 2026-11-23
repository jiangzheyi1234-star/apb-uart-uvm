class uart_config extends uvm_object;
  `uvm_object_utils(uart_config)
  int unsigned bit_cycles = 32;
  int unsigned data_bits = 8;
  int unsigned stop_bits = 1;
  bit parity_en = 0;
  int unsigned epoch = 0;

  function new(string name = "uart_config");
    super.new(name);
  endfunction

  function void validate();
    if (bit_cycles < 8 || data_bits < 5 || data_bits > 8 ||
        stop_bits < 1 || stop_bits > 2)
      `uvm_fatal("UART_CFG", "Require bit_cycles >= 8, data_bits 5..8 and stop_bits 1..2")
  endfunction
endclass
