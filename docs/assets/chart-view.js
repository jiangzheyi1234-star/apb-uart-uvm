/* ECharts rendering for the archived comparison data. */
(() => {
  "use strict";

  const engine = window.UARTECharts;
  if (!engine) return;

  const ink = "#243c4d";
  const muted = "#526b7b";
  const rule = "#d8e5eb";
  const accent = "#087f83";
  const typography = { color: ink, fontFamily: 'system-ui, "Microsoft YaHei", sans-serif' };
  const tooltip = {
    trigger: "item",
    renderMode: "richText",
    confine: true,
    backgroundColor: "#172f40",
    borderWidth: 0,
    textStyle: { ...typography, color: "#fff" },
  };

  function mount(host, option, resize) {
    const chart = engine.init(host, null, { renderer: "svg" });
    try {
      chart.setOption({ animation: false, textStyle: typography, ...option });
    } catch (error) {
      chart.dispose();
      throw error;
    }
    const relayout = () => {
      if (!host.clientWidth) return;
      chart.resize();
      if (resize) chart.setOption(resize(host.clientWidth));
    };
    const observer = typeof ResizeObserver === "function" ? new ResizeObserver(relayout) : null;
    if (observer) observer.observe(host);
    else window.addEventListener("resize", relayout);
    return {
      chart,
      dispose() {
        if (observer) observer.disconnect();
        else window.removeEventListener("resize", relayout);
        chart.dispose();
      },
    };
  }

  function renderParity(host, { samples, onSelect }) {
    const bytes = [...new Set(samples.map(sample => sample.byte))];
    const configs = [
      { variant: "upstream", label: "原版", symbol: "circle", offset: -10, fill: "#fff", border: muted },
      { variant: "fixed", label: "修复版", symbol: "roundRect", offset: 10, fill: accent, border: accent },
    ];
    const option = {
      grid: { left: 57, right: 11, top: 14, bottom: 30 },
      tooltip: { ...tooltip, formatter: item => item.data.detail },
      xAxis: {
        type: "category", data: bytes, axisTick: { show: false },
        axisLabel: { color: ink, interval: 0, fontSize: 13, fontWeight: 650 },
        axisLine: { lineStyle: { color: rule } },
        splitArea: { show: true, areaStyle: { color: bytes.map((_, i) => i === 1 ? "#ecf7f3" : "#fff") } },
      },
      yAxis: {
        type: "category", data: ["PE=0", "PE=1"], axisTick: { show: false },
        axisLine: { show: false }, axisLabel: { color: muted, fontSize: 12 },
        splitLine: { show: true, lineStyle: { color: rule, type: "dashed" } },
      },
      series: configs.map(config => ({
        name: config.label, type: "scatter", symbol: config.symbol, symbolSize: 16,
        symbolOffset: [config.offset, 0],
        itemStyle: { color: config.fill, borderColor: config.border, borderWidth: 2, opacity: 1 },
        emphasis: { scale: 1.3 },
        data: samples.filter(sample => sample.variant === config.variant).map(sample => ({
          id: sample.id, detail: sample.detail, value: [sample.byte, `PE=${sample.bit}`],
        })),
      })),
    };
    const view = mount(host, option);
    view.chart.on("click", "series.scatter", event => onSelect(event.data.id));
    return view;
  }

  const states = [
    { value: 0, color: "#e9eff3", glyph: "–", ink: muted },
    { value: 1, color: "#c5e8db", glyph: "✓", ink: "#15513e" },
    { value: 2, color: "#f5d2ce", glyph: "×", ink: "#812b35" },
    { value: 3, color: "#ffe8bf", glyph: "!", ink: "#71480c" },
  ];

  function renderMatrix(host, { rows, columns, cells, selectedRunId, onSelect }) {
    const rowLabels = new Map(rows.map(row => [row.id, row.label]));
    const columnById = new Map(columns.map(column => [column.id, column]));
    const versions = [...new Set(columns.map(column => column.variant))];
    const topAxis = { type: "category", position: "top", axisLine: { show: false }, axisTick: { show: false } };
    const data = selected => cells.map(cell => {
      const tone = states[cell.status === "PASS" ? 1 : cell.status === "FAIL" ? 2 : cell.status ? 3 : 0];
      const isSelected = cell.runId && cell.runId === selected;
      return {
        id: `${cell.rowId}:${cell.columnId}`,
        runId: cell.runId,
        value: [cell.columnId, cell.rowId, tone.value],
        status: cell.status,
        glyph: tone.glyph,
        itemStyle: { borderColor: isSelected ? accent : "#fff", borderWidth: isSelected ? 3 : 4 },
        label: { color: tone.ink },
      };
    });
    const layout = width => ({
      grid: { top: 45, bottom: 6, left: width < 490 ? 106 : 152, right: 6 },
      yAxis: { axisLabel: { width: width < 490 ? 97 : 142, fontSize: width < 490 ? 11 : 13 } },
    });
    const labels = layout(host.clientWidth);
    const option = {
      grid: labels.grid,
      tooltip: { ...tooltip, formatter: ({ data: item }) =>
        `${rowLabels.get(item.value[1])}\n${columnById.get(item.value[0])?.label} · ${item.status || "未记录"}` },
      xAxis: [{
        ...topAxis, data: columns.map(column => column.id),
        axisLabel: { color: muted, interval: 0, fontSize: 11, margin: 4,
          formatter: value => columnById.get(value)?.seed ?? value },
      }, {
        ...topAxis, data: versions, offset: 21,
        axisLabel: { color: ink, interval: 0, fontSize: 13, fontWeight: 650,
          formatter: value => value === "upstream" ? "原版" : "修复版" },
      }],
      yAxis: {
        type: "category", inverse: true, data: rows.map(row => row.id),
        axisLine: { show: false }, axisTick: { show: false }, splitArea: { show: false },
        axisLabel: { ...labels.yAxis.axisLabel, color: ink, interval: 0, overflow: "truncate",
          formatter: value => rowLabels.get(value) || value },
      },
      visualMap: { type: "piecewise", dimension: 2, show: false, seriesIndex: 0, pieces: states },
      series: [{
        id: "outcomes", type: "heatmap", data: data(selectedRunId),
        label: { show: true, fontSize: 16, fontWeight: 700, formatter: item => item.data.glyph },
        emphasis: { itemStyle: { borderColor: accent, borderWidth: 2 } },
      }],
    };
    const view = mount(host, option, layout);
    view.chart.on("click", "series.heatmap", event => {
      if (event.data.runId) onSelect(event.data.runId);
    });
    return {
      dispose: view.dispose,
      setSelected(runId) { view.chart.setOption({ series: [{ id: "outcomes", data: data(runId) }] }); },
    };
  }

  window.UARTCharts = { renderParity, renderMatrix };
})();
