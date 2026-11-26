// SPDX-License-Identifier: MIT
// Production wrapper: subsystem plus the generic synchronous RAM. No simulation
// controls or fault-injection paths are present in this hierarchy.
`timescale 1ns/1ps

module apb_peripheral_top (
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
    input  logic        rx_i,
    output logic        tx_o,
    output logic        event_o
);
    logic ram_en, ram_we;
    logic [5:0] ram_addr;
    logic [31:0] ram_wdata, ram_rdata;

    apb_peripheral_subsystem subsystem_i (
        .CLK(CLK), .RSTN(RSTN), .PADDR(PADDR), .PWDATA(PWDATA),
        .PWRITE(PWRITE), .PSEL(PSEL), .PENABLE(PENABLE),
        .PRDATA(PRDATA), .PREADY(PREADY), .PSLVERR(PSLVERR),
        .rx_i(rx_i), .tx_o(tx_o), .event_o(event_o),
        .ram_en(ram_en), .ram_we(ram_we), .ram_addr(ram_addr),
        .ram_wdata(ram_wdata), .ram_rdata(ram_rdata)
    );

    apb_sync_ram ram_i (
        .CLK(CLK), .ram_en(ram_en), .ram_we(ram_we), .ram_addr(ram_addr),
        .ram_wdata(ram_wdata), .ram_rdata(ram_rdata)
    );
endmodule
