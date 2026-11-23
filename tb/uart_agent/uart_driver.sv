class uart_driver extends uvm_driver #(uart_seq_item);
  `uvm_component_utils(uart_driver)
  virtual uart_if vif;
  uart_config cfg;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(virtual uart_if)::get(this, "", "vif", vif))
      `uvm_fatal("UART_VIF", "UART virtual interface was not configured")
    if (!uvm_config_db#(uart_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("UART_CFG", "UART configuration was not configured")
  endfunction

  task drive_bit(bit value, int unsigned cycles);
    // Every transition occurs at a falling clock edge, away from DUT sampling.
    vif.rx = value;
    repeat (cycles) @(negedge vif.clk);
  endtask

  task drive_frame(uart_seq_item item);
    int unsigned cycles, bits, stops;
    bit parity, use_parity;
    cfg.validate();
    cycles = cfg.bit_cycles;
    bits = cfg.data_bits;
    stops = cfg.stop_bits;
    use_parity = cfg.parity_en;
    item.epoch = cfg.epoch;
    parity = 0;
    @(negedge vif.clk);
    item.start_time = $time;
    drive_bit(0, cycles);
    for (int unsigned i = 0; i < bits; i++) begin
      drive_bit(item.data[i], cycles);
      parity ^= item.data[i];
    end
    if (use_parity)
      drive_bit(parity ^ item.parity_error, cycles);
    for (int unsigned i = 0; i < stops; i++)
      drive_bit(!item.framing_error, cycles);
    // Leave a full idle bit for the RTL synchronizer and next start detection.
    drive_bit(1, cycles);
    item.end_time = $time;
  endtask

  task run_phase(uvm_phase phase);
    vif.rx = 1;
    forever begin
      seq_item_port.get_next_item(req);
      req.aborted = 0;
      wait (vif.rst_n === 1'b1);
      fork
        drive_frame(req);
        begin
          @(negedge vif.rst_n);
          req.aborted = 1;
        end
      join_any
      disable fork;
      vif.rx = 1;
      seq_item_port.item_done();
    end
  endtask
endclass
