// SPDX-License-Identifier: MIT
// 64 x 32 synchronous single-port RAM. Contents and read output are deliberately
// uninitialized; neither asynchronous nor synchronous reset touches the array.
`timescale 1ns/1ps

module apb_sync_ram (
    input  logic        CLK,
    input  logic        ram_en,
    input  logic        ram_we,
    input  logic [5:0]  ram_addr,
    input  logic [31:0] ram_wdata,
    output logic [31:0] ram_rdata
);
    logic [31:0] memory [0:63];

    always_ff @(posedge CLK) begin
        if (ram_en) begin
            if (ram_we)
                memory[ram_addr] <= ram_wdata;
            else
                ram_rdata <= memory[ram_addr];
        end
    end
endmodule
