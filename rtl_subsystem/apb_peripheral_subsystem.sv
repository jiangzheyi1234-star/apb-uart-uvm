// SPDX-License-Identifier: MIT
// Production APB address router plus MBIST controller. The native RAM port is
// exposed so a technology-specific RAM wrapper can replace the generic array.
// UART is the separately attributed PULP implementation selected by the filelist.
`timescale 1ns/1ps

module apb_peripheral_subsystem (
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
    output logic        event_o,
    output logic        ram_en,
    output logic        ram_we,
    output logic [5:0]  ram_addr,
    output logic [31:0] ram_wdata,
    input  logic [31:0] ram_rdata
);
    logic uart_selected;
    logic [31:0] uart_prdata, memory_prdata;
    logic uart_pready, uart_pslverr, memory_pready, memory_pslverr;

    // UART alone retains its original byte-spaced register addressing. Upper
    // address aliases are not forwarded into it through the subsystem router.
    assign uart_selected = (PADDR[11:3] == 9'd0);

    apb_uart_sv #(.APB_ADDR_WIDTH(12)) uart_i (
        .CLK(CLK), .RSTN(RSTN), .PADDR(PADDR), .PWDATA(PWDATA),
        .PWRITE(PWRITE), .PSEL(PSEL && uart_selected), .PENABLE(PENABLE),
        .PRDATA(uart_prdata), .PREADY(uart_pready), .PSLVERR(uart_pslverr),
        .rx_i(rx_i), .tx_o(tx_o), .event_o(event_o)
    );

    apb_ram_mbist memory_controller_i (
        .CLK(CLK), .RSTN(RSTN), .PADDR(PADDR), .PWDATA(PWDATA),
        .PWRITE(PWRITE), .PSEL(PSEL && !uart_selected), .PENABLE(PENABLE),
        .PRDATA(memory_prdata), .PREADY(memory_pready), .PSLVERR(memory_pslverr),
        .ram_en(ram_en), .ram_we(ram_we), .ram_addr(ram_addr),
        .ram_wdata(ram_wdata), .ram_rdata(ram_rdata)
    );

    assign PRDATA = uart_selected ? uart_prdata : memory_prdata;
    assign PREADY = uart_selected ? uart_pready : memory_pready;
    assign PSLVERR = uart_selected ? uart_pslverr : memory_pslverr;
endmodule
