// Copyright 2017 ETH Zurich and University of Bologna.
// Copyright and related rights are licensed under the Solderpad Hardware
// License, Version 0.51 (the “License”); you may not use this file except in
// compliance with the License.  You may obtain a copy of the License at
// http://solderpad.org/licenses/SHL-0.51. Unless required by applicable law
// or agreed to in writing, software, hardware and materials distributed under
// this License is distributed on an “AS IS” BASIS, WITHOUT WARRANTIES OR
// CONDITIONS OF ANY KIND, either express or implied. See the License for the
// specific language governing permissions and limitations under the License.

// Local verification-project revision: receive a complete checked frame before
// making it valid. Keep the original data/ready interface and add a framing flag.
module uart_rx (
    input  logic        clk_i,
    input  logic        rstn_i,
    input  logic        rx_i,
    input  logic [15:0] cfg_div_i,
    input  logic        cfg_en_i,
    input  logic        cfg_parity_en_i,
    input  logic [1:0]  cfg_bits_i,
    output logic        busy_o,
    output logic        err_o,
    output logic        framing_err_o,
    input  logic        err_clr_i,
    output logic [7:0]  rx_data_o,
    output logic        rx_valid_o,
    input  logic        rx_ready_i
);
    typedef enum logic [2:0] {IDLE, START_BIT, DATA, PARITY, STOP_BIT, SAVE_DATA} state_t;
    state_t state;
    logic [2:0] rx_sync;
    logic rx_previous;
    logic [15:0] sample_count;
    logic [2:0] bit_index;
    logic [7:0] frame_data;
    logic parity_accumulator;
    logic [2:0] last_bit;

    assign last_bit = 3'd4 + {1'b0, cfg_bits_i};
    assign busy_o = (state != IDLE);
    assign rx_data_o = frame_data;
    assign rx_valid_o = (state == SAVE_DATA) && cfg_en_i;

    always_ff @(posedge clk_i or negedge rstn_i) begin
        if (!rstn_i) begin
            rx_sync <= 3'b111;
            rx_previous <= 1'b1;
        end else if (!cfg_en_i) begin
            rx_sync <= 3'b111;
            rx_previous <= 1'b1;
        end else begin
            rx_sync <= {rx_sync[1:0], rx_i};
            rx_previous <= rx_sync[2];
        end
    end

    // Loading D and then counting down to zero gives D+1 clocks per bit.
    // The synchronized falling edge starts a half-bit validation interval;
    // subsequent samples occur at the centers of the data/parity/stop bits.
    always_ff @(posedge clk_i or negedge rstn_i) begin
        if (!rstn_i) begin
            state <= IDLE;
            sample_count <= '0;
            bit_index <= '0;
            frame_data <= '0;
            parity_accumulator <= 1'b0;
            err_o <= 1'b0;
            framing_err_o <= 1'b0;
        end else if (!cfg_en_i) begin
            state <= IDLE;
            sample_count <= '0;
            bit_index <= '0;
            frame_data <= '0;
            parity_accumulator <= 1'b0;
            err_o <= 1'b0;
            framing_err_o <= 1'b0;
        end else begin
            if (err_clr_i) begin
                err_o <= 1'b0;
                framing_err_o <= 1'b0;
            end
            case (state)
                IDLE: begin
                    if (rx_previous && !rx_sync[2]) begin
                        sample_count <= {1'b0, cfg_div_i[15:1]};
                        bit_index <= '0;
                        frame_data <= '0;
                        parity_accumulator <= 1'b0;
                        err_o <= 1'b0;
                        framing_err_o <= 1'b0;
                        state <= START_BIT;
                    end
                end
                START_BIT: begin
                    if (sample_count != 0)
                        sample_count <= sample_count - 1'b1;
                    else if (rx_sync[2])
                        state <= IDLE; // Reject a short low glitch.
                    else begin
                        sample_count <= cfg_div_i;
                        state <= DATA;
                    end
                end
                DATA: begin
                    if (sample_count != 0)
                        sample_count <= sample_count - 1'b1;
                    else begin
                        frame_data[bit_index] <= rx_sync[2];
                        parity_accumulator <= parity_accumulator ^ rx_sync[2];
                        sample_count <= cfg_div_i;
                        if (bit_index == last_bit)
                            state <= cfg_parity_en_i ? PARITY : STOP_BIT;
                        else
                            bit_index <= bit_index + 1'b1;
                    end
                end
                PARITY: begin
                    if (sample_count != 0)
                        sample_count <= sample_count - 1'b1;
                    else begin
                        err_o <= (rx_sync[2] != parity_accumulator);
                        sample_count <= cfg_div_i;
                        state <= STOP_BIT;
                    end
                end
                STOP_BIT: begin
                    if (sample_count != 0)
                        sample_count <= sample_count - 1'b1;
                    else begin
                        framing_err_o <= !rx_sync[2];
                        state <= SAVE_DATA;
                    end
                end
                SAVE_DATA: begin
                    // Preserve data AND both flags while the FIFO is full.
                    if (rx_ready_i)
                        state <= IDLE;
                end
                default: state <= IDLE;
            endcase
        end
    end
endmodule
