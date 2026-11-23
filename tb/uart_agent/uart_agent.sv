class uart_agent extends uvm_agent;
  `uvm_component_utils(uart_agent)
  uart_sequencer sqr;
  uart_driver driver;
  uart_monitor tx_monitor;
  uart_monitor rx_monitor;
  uart_config cfg;

  function new(string name, uvm_component parent);
    super.new(name, parent);
  endfunction

  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    if (!uvm_config_db#(uart_config)::get(this, "", "cfg", cfg))
      `uvm_fatal("UART_CFG", "UART agent configuration was not configured")
    uvm_config_db#(uart_config)::set(this, "*", "cfg", cfg);
    tx_monitor = uart_monitor::type_id::create("tx_monitor", this);
    rx_monitor = uart_monitor::type_id::create("rx_monitor", this);
    tx_monitor.observe_tx = 1;
    rx_monitor.observe_tx = 0;
    if (get_is_active() == UVM_ACTIVE) begin
      sqr = uart_sequencer::type_id::create("sqr", this);
      driver = uart_driver::type_id::create("driver", this);
    end
  endfunction

  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    if (get_is_active() == UVM_ACTIVE)
      driver.seq_item_port.connect(sqr.seq_item_export);
  endfunction
endclass
