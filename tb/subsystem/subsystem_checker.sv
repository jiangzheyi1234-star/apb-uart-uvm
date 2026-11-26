`uvm_analysis_imp_decl(_subsystem_tx)
`uvm_analysis_imp_decl(_subsystem_rx)

// Reuse the protocol suite's raw-pin SETUP/access/stability checker. The only
// extension to transaction expectations is a mask for volatile STATUS/LSR.
// RAM contents come from completed APB writes, never from an RTL array read.
class subsystem_checker extends apb_protocol_checker;
  `uvm_component_utils(subsystem_checker)
  uvm_analysis_imp #(apb_seq_item,subsystem_checker) apb_in;
  uvm_analysis_imp_subsystem_tx #(uart_seq_item,subsystem_checker) tx_in;
  uvm_analysis_imp_subsystem_rx #(uart_seq_item,subsystem_checker) rx_in;
  bit [31:0] read_masks[$];
  bit [31:0] ram_model[64];
  bit ram_valid[64];
  bit [7:0] expected_tx[$], expected_rx[$];
  int unsigned error_responses, ram_reads, ram_writes, tx_count, rx_count;

  function new(string name,uvm_component parent);
    super.new(name,parent);
    // The reused checker has a nonvirtual write() and a base-typed analysis
    // implementation. Use a correctly typed endpoint for this specialization.
    apb_in=new("apb_in",this);
    tx_in=new("tx_in",this);
    rx_in=new("rx_in",this);
  endfunction
  function void expect_access(bit wr,bit[11:0] addr,bit[31:0] value,
                              bit[31:0] expected_read,bit[31:0] read_mask,
                              int unsigned stalls,bit error_response);
    expect_transfer(wr,addr,value,expected_read,stalls,error_response);
    read_masks.push_back(read_mask);
  endfunction
  function void invalidate_ram();
    foreach(ram_valid[i]) ram_valid[i]=0;
  endfunction
  function void expect_mbist_zeroes();
    // The final documented March element is an ascending read of zero.
    // Predict the final background independently of native RAM transactions.
    foreach(ram_model[i]) begin ram_model[i]=0; ram_valid[i]=1; end
  endfunction
  function void write(apb_seq_item tr);
    apb_seq_item plan;
    bit [31:0] mask;
    int unsigned index;
    if(expected.size()==0 || read_masks.size()==0) begin
      `uvm_error("SUBSYSTEM_UNEXPECTED_APB","An unplanned APB completion was observed")
      return;
    end
    plan=expected.pop_front(); mask=read_masks.pop_front();
    if(!tr.completed || tr.aborted || tr.timed_out || tr.write!=plan.write ||
       tr.addr!=plan.addr || tr.data!=plan.data || tr.slverr!=plan.slverr ||
       tr.wait_cycles!=plan.wait_cycles ||
       (!tr.write && (tr.rdata & mask)!==(plan.rdata & mask)))
      `uvm_error("SUBSYSTEM_APB_COMPARE",$sformatf("addr=%03h wr=%b wait=%0d/%0d error=%b/%b data=%08h/%08h mask=%08h",tr.addr,tr.write,tr.wait_cycles,plan.wait_cycles,tr.slverr,plan.slverr,tr.rdata,plan.rdata,mask))
    completed++;
    if(tr.write) writes++; else reads++;
    case(tr.wait_cycles) 0:wait0++; 1:wait1++; 3:wait3++; 7:wait7++; default:; endcase
    if(tr.wait_cycles>max_wait) max_wait=tr.wait_cycles;
    if(tr.slverr) error_responses++;
    else if(tr.addr>=12'h100 && tr.addr<=12'h1fc && tr.addr[1:0]==0) begin
      index=(int'(tr.addr)-'h100)/4;
      if(tr.write) begin
        ram_model[index]=tr.data; ram_valid[index]=1; ram_writes++;
      end else begin
        if(ram_valid[index] && tr.rdata!==ram_model[index])
          `uvm_error("SUBSYSTEM_RAM_MODEL",$sformatf("word=%0d actual=%08h expected=%08h",index,tr.rdata,ram_model[index]))
        ram_reads++;
      end
    end
  endfunction
  function void write_subsystem_tx(uart_seq_item tr);
    bit [7:0] value;
    if(expected_tx.size()==0) begin
      `uvm_error("SUBSYSTEM_UART_TX_UNEXPECTED","Unplanned serial transmit frame")
      return;
    end
    value=expected_tx.pop_front();
    if(tr.aborted || tr.data!==value || tr.parity_error || tr.framing_error)
      `uvm_error("SUBSYSTEM_UART_TX",$sformatf("actual=%02h expected=%02h",tr.data,value))
    tx_count++;
  endfunction
  function void write_subsystem_rx(uart_seq_item tr);
    bit [7:0] value;
    if(expected_rx.size()==0) begin
      `uvm_error("SUBSYSTEM_UART_RX_UNEXPECTED","Unplanned serial receive frame")
      return;
    end
    value=expected_rx.pop_front();
    if(tr.aborted || tr.data!==value || tr.parity_error || tr.framing_error)
      `uvm_error("SUBSYSTEM_UART_RX",$sformatf("actual=%02h expected=%02h",tr.data,value))
    rx_count++;
  endfunction
  function void check_phase(uvm_phase phase);
    super.check_phase(phase);
    if(read_masks.size()!=0 || expected_tx.size()!=0 || expected_rx.size()!=0)
      `uvm_error("SUBSYSTEM_PENDING","Unobserved APB or UART expectations remain")
  endfunction
endclass
