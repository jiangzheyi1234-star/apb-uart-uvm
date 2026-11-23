class uart_monitor extends uvm_monitor;
  `uvm_component_utils(uart_monitor)
  virtual uart_if vif;
  uart_config cfg;
  bit observe_tx = 1;
  uvm_analysis_port #(uart_seq_item) ap;

  function new(string name, uvm_component parent);
    super.new(name, parent);
    ap = new("ap", this);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(virtual uart_if)::get(this, "", "vif", vif))
      `uvm_fatal("UART_VIF", "UART virtual interface was not configured")
    if (!uvm_config_db#(uart_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("UART_CFG", "UART configuration was not configured")
  endfunction

  function logic pin_value();
    return observe_tx ? vif.tx : vif.rx;
  endfunction

  task sample_frame(uart_seq_item item, output bit valid_frame);
    int unsigned cycles, bits, stops;
    bit parity, use_parity;
    logic sample;
    cfg.validate();
    cycles = cfg.bit_cycles;
    bits = cfg.data_bits;
    stops = cfg.stop_bits;
    use_parity = cfg.parity_en;
    item.epoch = cfg.epoch;
    item.start_time = $time;
    valid_frame = 0;
    parity = 0;
    // We detected the falling edge at a rising clock edge. Sample centrally.
    repeat (cycles / 2) @(posedge vif.clk);
    if (pin_value() !== 1'b0)
      return;  // A short low pulse is not a complete UART frame.
    for (int unsigned i = 0; i < bits; i++) begin
      repeat (cycles) @(posedge vif.clk);
      sample = pin_value();
      if ($isunknown(sample))
        `uvm_error("UART_X", "Unknown UART data bit")
      item.data[i] = sample;
      parity ^= sample;
    end
    if (use_parity) begin
      repeat (cycles) @(posedge vif.clk);
      item.sampled_parity = pin_value();
      item.parity_error = (item.sampled_parity !== parity);
    end
    for (int unsigned i = 0; i < stops; i++) begin
      repeat (cycles) @(posedge vif.clk);
      if (pin_value() !== 1'b1)
        item.framing_error = 1;
    end
    item.end_time = $time;
    valid_frame = 1;
  endtask

  task run_phase(uvm_phase phase);
    logic previous;
    uart_seq_item item;
    bit valid_frame;
    previous = 1;
    forever begin
      @(posedge vif.clk);
      if (vif.rst_n !== 1'b1)
        previous = 1;
      else begin
        if (previous === 1'b1 && pin_value() === 1'b0) begin
          item = uart_seq_item::type_id::create("observed");
          valid_frame = 0;
          fork
            sample_frame(item, valid_frame);
            begin
              @(negedge vif.rst_n);
              item.aborted = 1;
            end
          join_any
          disable fork;
          if (valid_frame && !item.aborted && vif.rst_n === 1'b1 && item.epoch == cfg.epoch)
            ap.write(item);
        end
        previous = pin_value();
      end
    end
  endtask
endclass
