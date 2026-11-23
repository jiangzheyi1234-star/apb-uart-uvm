class apb_uart_env extends uvm_env;
  `uvm_component_utils(apb_uart_env)
  apb_agent apb;
  uart_agent uart;
  apb_uart_scoreboard sb;
  apb_uart_coverage cov;
  function new(string name,uvm_component parent); super.new(name,parent); endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    apb=apb_agent::type_id::create("apb",this);
    uart=uart_agent::type_id::create("uart",this);
    sb=apb_uart_scoreboard::type_id::create("sb",this);
    cov=apb_uart_coverage::type_id::create("cov",this);
  endfunction
  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    apb.monitor.ap.connect(sb.apb_imp); apb.monitor.ap.connect(cov.apb_imp);
    uart.tx_monitor.ap.connect(sb.tx_imp); uart.tx_monitor.ap.connect(cov.tx_imp);
    uart.rx_monitor.ap.connect(sb.rx_imp); uart.rx_monitor.ap.connect(cov.rx_imp);
  endfunction
endclass
