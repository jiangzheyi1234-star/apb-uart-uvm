// Copyright 2017 ETH Zurich and University of Bologna.
// Copyright and related rights are licensed under the Solderpad Hardware
// License, Version 0.51 (the “License”); you may not use this file except in
// compliance with the License.  You may obtain a copy of the License at
// http://solderpad.org/licenses/SHL-0.51. Unless required by applicable law
// or agreed to in writing, software, hardware and materials distributed under
// this License is distributed on an “AS IS” BASIS, WITHOUT WARRANTIES OR
// CONDITIONS OF ANY KIND, either express or implied. See the License for the
// specific language governing permissions and limitations under the License.

// Local revision: derive pending sources explicitly and acknowledge persistent
// TX-empty/line-error conditions without losing the no-pending indicator bit.
module uart_interrupt #(
    parameter TX_FIFO_DEPTH = 32,
    parameter RX_FIFO_DEPTH = 32
)(
    input  logic clk_i,
    input  logic rstn_i,
    input  logic [2:0] IER_i,
    input  logic RDA_i,
    input  logic CTI_i,
    input  logic error_i,
    input  logic [$clog2(RX_FIFO_DEPTH):0] rx_elements_i,
    input  logic [$clog2(TX_FIFO_DEPTH):0] tx_elements_i,
    input  logic [1:0] trigger_level_i,
    input  logic [3:0] clr_int_i,
    output logic interrupt_o,
    output logic [3:0] IIR_o
);
    logic tx_acknowledged, line_acknowledged;
    logic [4:0] trigger_count;
    logic line_pending, rx_pending, tx_pending;

    always_comb begin
        case (trigger_level_i)
            2'b00: trigger_count = 5'd1;
            2'b01: trigger_count = 5'd4;
            2'b10: trigger_count = 5'd8;
            2'b11: trigger_count = 5'd14;
            default: trigger_count = 5'd1;
        endcase
    end

    // Reading IIR acknowledges THRE. A write that makes the FIFO nonempty,
    // or disabling/re-enabling the source, arms the next empty notification.
    // Reading LSR acknowledges a head-byte error. Popping RBR arms the next
    // head byte, including adjacent erroneous frames with no clean gap.
    always_ff @(posedge clk_i or negedge rstn_i) begin
        if (!rstn_i) begin
            tx_acknowledged <= 1'b0;
            line_acknowledged <= 1'b0;
        end else begin
            if (!IER_i[1] || tx_elements_i != 0)
                tx_acknowledged <= 1'b0;
            else if (clr_int_i == 4'b0100 && IIR_o == 4'b0100)
                tx_acknowledged <= 1'b1;

            if (!IER_i[2] || !error_i || clr_int_i == 4'b1000)
                line_acknowledged <= 1'b0;
            else if (clr_int_i == 4'b1100)
                line_acknowledged <= 1'b1;
        end
    end

    always_comb begin
        line_pending = IER_i[2] && error_i && !line_acknowledged;
        // RDA is correctly driven by RX nonempty in the revised top-level.
        // >= preserves the event when software misses the exact threshold.
        rx_pending = IER_i[0] && ((RDA_i && ($unsigned(rx_elements_i) >= trigger_count)) || CTI_i);
        tx_pending = IER_i[1] && (tx_elements_i == 0) && !tx_acknowledged;
        IIR_o = 4'b0001;
        if (line_pending)
            IIR_o = 4'b1100;
        else if (rx_pending)
            IIR_o = 4'b1000;
        else if (tx_pending)
            IIR_o = 4'b0100;
        interrupt_o = !IIR_o[0];
    end
endmodule
