// SPDX-License-Identifier: MIT
// APB register/RAM controller with a destructive, word-oriented March C- test.
// Native RAM contract: a read enabled at a rising CLK updates ram_rdata after
// that edge; writes leave ram_rdata unchanged. The RAM itself has no reset.
`timescale 1ns/1ps

module apb_ram_mbist (
    input  logic        CLK,
    input  logic        RSTN,
    input  logic [11:0] PADDR,
    input  logic [31:0] PWDATA,
    input  logic        PWRITE,
    input  logic        PSEL,
    input  logic        PENABLE,
    output logic [31:0] PRDATA,
    output logic        PREADY,
    output logic        PSLVERR,
    output logic        ram_en,
    output logic        ram_we,
    output logic [5:0]  ram_addr,
    output logic [31:0] ram_wdata,
    input  logic [31:0] ram_rdata
);
    localparam [11:0] START_ADDR     = 12'h080;
    localparam [11:0] STATUS_ADDR    = 12'h084;
    localparam [11:0] FAIL_ADDR_ADDR = 12'h088;
    localparam [11:0] EXPECT_ADDR    = 12'h08c;
    localparam [11:0] ACTUAL_ADDR    = 12'h090;
    localparam [11:0] FAIL_STEP_ADDR = 12'h094;

    localparam [2:0] MB_IDLE    = 3'd0;
    localparam [2:0] MB_WRITE_0 = 3'd1;
    localparam [2:0] MB_READ    = 3'd2;
    localparam [2:0] MB_COMPARE = 3'd3;
    localparam [2:0] MB_REWRITE = 3'd4;

    logic [2:0] state_q, step_q;
    logic [5:0] address_q;
    logic busy_q, done_q, fail_q;
    logic [5:0] fail_address_q;
    logic [2:0] fail_step_q;
    logic [31:0] expected_q, actual_q;
    logic apb_read_pending_q;
    logic ram_word_selected, apb_access, apb_ram_request;
    logic apb_read_issue, start_accepted;
    logic descending, last_address;
    logic [31:0] expected_word;

    assign apb_access = PSEL && PENABLE;
    assign ram_word_selected = (PADDR[11:8] == 4'h1) && (PADDR[1:0] == 2'b00);
    assign apb_ram_request = apb_access && ram_word_selected && !busy_q;
    assign apb_read_issue = RSTN && apb_ram_request && !PWRITE && !apb_read_pending_q;
    assign start_accepted = RSTN && apb_access && PWRITE &&
                            (PADDR == START_ADDR) && PWDATA[0] && !busy_q;
    assign descending = (step_q == 3'd3) || (step_q == 3'd4);
    assign last_address = descending ? (address_q == 6'd0) : (address_q == 6'd63);
    assign expected_word = ((step_q == 3'd2) || (step_q == 3'd4)) ?
                           32'hffffffff : 32'h00000000;

    // RAM writes and register accesses complete immediately. A RAM read first
    // issues the synchronous read, then completes in the following Access cycle.
    // Only a completed, valid write may change RAM or start a destructive test.
    always_comb begin
        PRDATA = 32'h00000000;
        PREADY = 1'b1;
        PSLVERR = 1'b0;
        if (RSTN && apb_access) begin
            if (ram_word_selected) begin
                if (busy_q) begin
                    PSLVERR = 1'b1;
                end else if (!PWRITE) begin
                    PREADY = apb_read_pending_q;
                    if (apb_read_pending_q)
                        PRDATA = ram_rdata;
                end
            end else begin
                case (PADDR)
                    START_ADDR: begin
                        // Bit 0 is write-one-to-start; zero and reserved bits
                        // alone are no-ops. A real retrigger while busy fails.
                        PSLVERR = !PWRITE || (PWDATA[0] && busy_q);
                    end
                    STATUS_ADDR: begin
                        PRDATA = {29'b0, fail_q, done_q, busy_q};
                        PSLVERR = PWRITE;
                    end
                    FAIL_ADDR_ADDR: begin
                        PRDATA = {26'b0, fail_address_q};
                        PSLVERR = PWRITE;
                    end
                    EXPECT_ADDR: begin
                        PRDATA = expected_q;
                        PSLVERR = PWRITE;
                    end
                    ACTUAL_ADDR: begin
                        PRDATA = actual_q;
                        PSLVERR = PWRITE;
                    end
                    FAIL_STEP_ADDR: begin
                        PRDATA = {29'b0, fail_step_q};
                        PSLVERR = PWRITE;
                    end
                    default: PSLVERR = 1'b1;
                endcase
            end
        end
    end

    // BIST owns the native port for its entire busy interval, even in compare
    // cycles. APB memory accesses during that interval complete with an error.
    always_comb begin
        ram_en = 1'b0;
        ram_we = 1'b0;
        ram_addr = 6'd0;
        ram_wdata = 32'h00000000;
        if (RSTN) begin
            if (busy_q) begin
                ram_addr = address_q;
                case (state_q)
                    MB_WRITE_0: begin
                        ram_en = 1'b1;
                        ram_we = 1'b1;
                    end
                    MB_READ: ram_en = 1'b1;
                    MB_REWRITE: begin
                        ram_en = 1'b1;
                        ram_we = 1'b1;
                        ram_wdata = ~expected_word;
                    end
                    default: begin end
                endcase
            end else if (apb_ram_request) begin
                ram_addr = PADDR[7:2];
                ram_wdata = PWDATA;
                if (PWRITE) begin
                    ram_en = 1'b1;
                    ram_we = 1'b1;
                end else if (!apb_read_pending_q) begin
                    ram_en = 1'b1;
                end
            end
        end
    end

    // Reset aborts a pending APB read without clearing or initializing RAM.
    // An illegal master withdrawal also drops the pending bus response; it
    // cannot undo a native read that already occurred.
    always_ff @(posedge CLK or negedge RSTN) begin
        if (!RSTN) begin
            apb_read_pending_q <= 1'b0;
        end else if (apb_read_pending_q) begin
            apb_read_pending_q <= 1'b0;
        end else if (apb_read_issue) begin
            apb_read_pending_q <= 1'b1;
        end
    end

    // Six March elements, with both endpoints included on every sweep:
    // 0: up(w0), 1: up(r0,w1), 2: up(r1,w0),
    // 3: down(r0,w1), 4: down(r1,w0), 5: up(r0).
    // READ and COMPARE are separate states for the synchronous RAM latency.
    // A mismatch stops before any subsequent rewrite and latches first failure.
    always_ff @(posedge CLK or negedge RSTN) begin
        if (!RSTN) begin
            state_q <= MB_IDLE;
            step_q <= 3'd0;
            address_q <= 6'd0;
            busy_q <= 1'b0;
            done_q <= 1'b0;
            fail_q <= 1'b0;
            fail_address_q <= 6'd0;
            fail_step_q <= 3'd0;
            expected_q <= 32'h00000000;
            actual_q <= 32'h00000000;
        end else begin
            case (state_q)
                MB_IDLE: begin
                    if (start_accepted) begin
                        state_q <= MB_WRITE_0;
                        step_q <= 3'd0;
                        address_q <= 6'd0;
                        busy_q <= 1'b1;
                        done_q <= 1'b0;
                        fail_q <= 1'b0;
                        fail_address_q <= 6'd0;
                        fail_step_q <= 3'd0;
                        expected_q <= 32'h00000000;
                        actual_q <= 32'h00000000;
                    end
                end
                MB_WRITE_0: begin
                    if (address_q == 6'd63) begin
                        step_q <= 3'd1;
                        address_q <= 6'd0;
                        state_q <= MB_READ;
                    end else begin
                        address_q <= address_q + 6'd1;
                    end
                end
                MB_READ: state_q <= MB_COMPARE;
                MB_COMPARE: begin
                    if (ram_rdata != expected_word) begin
                        fail_address_q <= address_q;
                        fail_step_q <= step_q;
                        expected_q <= expected_word;
                        actual_q <= ram_rdata;
                        busy_q <= 1'b0;
                        done_q <= 1'b1;
                        fail_q <= 1'b1;
                        state_q <= MB_IDLE;
                    end else if (step_q == 3'd5) begin
                        if (last_address) begin
                            busy_q <= 1'b0;
                            done_q <= 1'b1;
                            state_q <= MB_IDLE;
                        end else begin
                            address_q <= address_q + 6'd1;
                            state_q <= MB_READ;
                        end
                    end else begin
                        state_q <= MB_REWRITE;
                    end
                end
                MB_REWRITE: begin
                    if (last_address) begin
                        step_q <= step_q + 3'd1;
                        // Elements 3 and 4 start from the upper endpoint.
                        address_q <= ((step_q == 3'd2) || (step_q == 3'd3)) ? 6'd63 : 6'd0;
                    end else if (descending) begin
                        address_q <= address_q - 6'd1;
                    end else begin
                        address_q <= address_q + 6'd1;
                    end
                    state_q <= MB_READ;
                end
                default: begin
                    // Fail closed if control state is corrupted; release RAM.
                    state_q <= MB_IDLE;
                    busy_q <= 1'b0;
                    done_q <= 1'b1;
                    fail_q <= 1'b1;
                end
            endcase
        end
    end
endmodule
