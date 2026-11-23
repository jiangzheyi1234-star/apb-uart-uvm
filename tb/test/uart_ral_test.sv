// Optional RAL feature test; existing transaction-based tests remain unchanged.
class uart_ral_test extends base_test;
  `uvm_component_utils(uart_ral_test)
  uart_reg_block regmodel;
  uart_apb_reg_adapter reg_adapter;
  uart_bank_predictor reg_predictor;
  int unsigned ral_writes, ral_mirror_reads;

  function new(string name,uvm_component parent); super.new(name,parent); endfunction
  function void build_phase(uvm_phase phase);
    super.build_phase(phase);
    regmodel=uart_reg_block::type_id::create("regmodel");
    regmodel.configure(null,""); regmodel.build(); regmodel.lock_model();
    reg_adapter=uart_apb_reg_adapter::type_id::create("reg_adapter");
    reg_predictor=uart_bank_predictor::type_id::create("reg_predictor",this);
    reg_predictor.regmodel=regmodel;
    reg_predictor.adapter=reg_adapter;
    reg_predictor.map=regmodel.normal_map;
  endfunction
  function void connect_phase(uvm_phase phase);
    super.connect_phase(phase);
    regmodel.normal_map.set_sequencer(env.apb.sqr,reg_adapter);
    regmodel.banked_map.set_sequencer(env.apb.sqr,reg_adapter);
    regmodel.normal_map.set_check_on_read(1);
    regmodel.banked_map.set_check_on_read(1);
    regmodel.ier_frontdoor.apb_adapter=reg_adapter;
    regmodel.dll_frontdoor.apb_adapter=reg_adapter;
    regmodel.dlm_frontdoor.apb_adapter=reg_adapter;
    env.apb.monitor.ap.connect(reg_predictor.bus_in);
  endfunction

  function void expect_mirror(uvm_reg target,bit[7:0] expected);
    if(target.get_mirrored_value()!==uvm_reg_data_t'(expected))
      `uvm_error("RAL_MIRROR",$sformatf("%s mirror expected=%02h actual=%h",target.get_full_name(),expected,target.get_mirrored_value()))
  endfunction
  task mirror_checked(uvm_reg target,uvm_reg_map selected_map);
    uvm_status_e status;
    target.mirror(status,UVM_CHECK,UVM_FRONTDOOR,selected_map);
    if(status!=UVM_IS_OK)
      `uvm_error("RAL_STATUS",$sformatf("%s frontdoor mirror failed",target.get_full_name()))
    ral_mirror_reads++;
  endtask
  task write_checked(uvm_reg target,bit[7:0] value,uvm_reg_map selected_map);
    uvm_status_e status;
    target.write(status,uvm_reg_data_t'(value),UVM_FRONTDOOR,selected_map);
    if(status!=UVM_IS_OK)
      `uvm_error("RAL_STATUS",$sformatf("%s frontdoor write failed",target.get_full_name()))
    ral_writes++;
    // No auto-prediction: this assertion depends on the passive bus predictor.
    expect_mirror(target,value);
    mirror_checked(target,selected_map);
  endtask

  task scenario();
    bit[7:0] lcr_value, ier_value, dll_value, dlm_value;
    // Reset when the bus/serial interfaces are idle. The predictor must reset
    // all four mirrors without receiving any register read or write first.
    vif.rst_n=0; clocks(8); vif.rst_n=1; clocks(8);
    expect_mirror(regmodel.ier,0); expect_mirror(regmodel.lcr,0);
    expect_mirror(regmodel.dll,0); expect_mirror(regmodel.dlm,0);
    mirror_checked(regmodel.ier,regmodel.normal_map);
    mirror_checked(regmodel.lcr,regmodel.normal_map);
    mirror_checked(regmodel.dll,regmodel.banked_map);
    mirror_checked(regmodel.dlm,regmodel.banked_map);

    for(int iteration=0;iteration<12;iteration++) begin
      lcr_value=8'($urandom_range(3,0) | ($urandom_range(1,0)<<2) |
                   ($urandom_range(1,0)<<3) | ((iteration%2)<<7));
      ier_value=8'($urandom_range(255,0));
      dll_value=8'($urandom_range(255,1));
      dlm_value=8'($urandom_range(3,0));
      write_checked(regmodel.lcr,lcr_value,regmodel.normal_map);
      write_checked(regmodel.ier,ier_value,regmodel.normal_map);
      expect_mirror(regmodel.lcr,lcr_value);
      mirror_checked(regmodel.lcr,regmodel.normal_map);
      write_checked(regmodel.dll,dll_value,regmodel.banked_map);
      expect_mirror(regmodel.lcr,lcr_value);
      mirror_checked(regmodel.lcr,regmodel.normal_map);
      write_checked(regmodel.dlm,dlm_value,regmodel.banked_map);
      expect_mirror(regmodel.lcr,lcr_value);
      mirror_checked(regmodel.lcr,regmodel.normal_map);
      expect_mirror(regmodel.ier,ier_value);
      expect_mirror(regmodel.dll,dll_value); expect_mirror(regmodel.dlm,dlm_value);
    end

    // Independent register sequences contend for the APB sequencer. Each bank
    // selection/target/restoration group must hold its lock across all beats.
    write_checked(regmodel.lcr,8'h83,regmodel.normal_map);
    fork
      write_checked(regmodel.ier,8'ha5,regmodel.normal_map);
      write_checked(regmodel.dll,8'h17,regmodel.banked_map);
      write_checked(regmodel.dlm,8'h02,regmodel.banked_map);
    join
    expect_mirror(regmodel.lcr,8'h83);
    mirror_checked(regmodel.lcr,regmodel.normal_map);
    expect_mirror(regmodel.ier,8'ha5);
    expect_mirror(regmodel.dll,8'h17); expect_mirror(regmodel.dlm,8'h02);

    // Raw APB transfers also update mirrors; alias 1 must never predict both
    // IER and DLM. High address aliases exercise predictor canonicalization.
    wr(3,32'h83); wr(0,32'h29); wr(1,32'h12);
    expect_mirror(regmodel.dll,8'h29); expect_mirror(regmodel.dlm,8'h12);
    expect_mirror(regmodel.ier,8'ha5);
    wr(3,3); wr(1,32'h65);
    expect_mirror(regmodel.ier,8'h65); expect_mirror(regmodel.dlm,8'h12);
    wr(12'h9ab,32'h83); wr(12'h9a9,32'h34);
    expect_mirror(regmodel.lcr,8'h83); expect_mirror(regmodel.dlm,8'h34);
    expect_mirror(regmodel.ier,8'h65);

    // Restore a working format using RAL only, then prove that FIFO side-effect
    // traffic still passes the independent transaction-level scoreboard.
    write_checked(regmodel.lcr,8'h03,regmodel.normal_map);
    write_checked(regmodel.ier,0,regmodel.normal_map);
    write_checked(regmodel.dll,31,regmodel.banked_map);
    write_checked(regmodel.dlm,0,regmodel.banked_map);
    expect_mirror(regmodel.lcr,3); clocks(8);
    exchange(8'h5a,8'ha5);
    if(reg_predictor.resets_seen<2 || reg_predictor.normal_predictions<20 || reg_predictor.banked_predictions<20)
      `uvm_error("RAL_PREDICTION_COUNT","Missing reset/normal/banked passive prediction evidence")
    `uvm_info("RAL_STATS",$sformatf("registers=4 random_iterations=12 RAL_writes=%0d mirror_reads=%0d predicted_normal=%0d predicted_banked=%0d resets=%0d",ral_writes,ral_mirror_reads,reg_predictor.normal_predictions,reg_predictor.banked_predictions,reg_predictor.resets_seen),UVM_LOW)
  endtask
endclass
