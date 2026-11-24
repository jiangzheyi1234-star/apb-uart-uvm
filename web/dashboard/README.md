# 验证工作台源模板

这些文件是无构建、无 CDN、无网络数据请求的工程报告 UI 模板。它们不含演示运行、替身计数或预填统计。发布生成器把模板复制到：

```text
docs/index.html             ← index.html
docs/assets/app.js          ← app.js
docs/assets/styles.css      ← styles.css
docs/data/dashboard.js      ← 由实际证据生成的数据
```

数据脚本必须设置 `window.UART_DASHBOARD`，并声明 `schema_version: 1`。页面不使用 `fetch`，保留上述目录后可通过 `file://` 阅读；直接打开尚未装配数据/资源的源模板不会产生虚构结果。

数据字段约定：

- `project`：title、version、source_url、commit、generated_utc；可附 toolchain、source_note。
- `suites`：id、title、kind、scope、note。`headline.suite_ids` 与 `headline.variant` 明确 UART 核心/RAL 汇总范围；协议与故障对照保持独立。
- `runs`：id、suite_id、variant、test、seed、raw_status、classification、expected、phase、metrics、log_url、report_url。`DETECTED` 是独立分类，不能替换原始 `FAIL`。
- `coverage`：id、title、suite_id、variant、scope、note；metrics 分为 functional_bins、rtl_lines、rtl_branches，分别提供 `{hit,total}`。groups 提供相同计数，gaps 保留 bin、hits、at_least 与已记录原因。
- `waveforms`：id、title、run_id、unit、range、可选 default_window；signals 提供 id、label、width 以及有序 `[time,"binary bitvector"]` events，允许 `x/z`；apb_events 提供 start/end、address、write、write_data/read_data、status，按需提供 wait_cycles/slverr；source 提供原始 VCD URL、SHA-256 和采样说明。
- `architecture`：nodes 提供 id、label、detail、x/y、可选 width/height 和 source_url；edges 提供 from/to/label。坐标按 SVG 视图提供。
- `defects`：id、title、summary、test_ids、upstream/fixed 的 description/source_url、evidence_urls。test_ids 关联 run.test。
- `inputs`：path、sha256、bytes；`limitations`：实现范围字符串。

未知值使用 `null` 或缺字段，UI 显示“未记录”，不会补成零或 PASS。所有 URL 相对 `docs/` 根目录，或为明确的 HTTP(S) 源码/证据地址。数据文本通过 DOM 文本节点插入；图形直接使用原生 SVG。

波形：滚轮缩放，背景拖拽平移，单击设置游标，红色手柄拖动游标；聚焦波形后可用左右键移动游标、`+/-` 缩放、`Shift+左右` 平移、`Home` 查看全程。APB 事件时间可点击定位。只绘制当前窗口内的记录区间，首个事件之前保留“未记录”。
