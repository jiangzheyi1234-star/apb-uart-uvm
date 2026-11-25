# 验证工作台源模板

这些文件是浏览时无需构建、CDN 或网络数据请求的工程报告 UI 模板，包含预构建的本地图表资源。它们不含演示运行、替身计数或预填统计。发布生成器把模板复制到：

```text
docs/index.html             ← index.html
docs/assets/app.js          ← app.js
docs/assets/styles.css      ← styles.css
docs/assets/chart-view.js   ← chart-view.js
docs/assets/vendor/         ← vendor/（图表子集、许可、SHA256SUMS）
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
- `defects`：id、title、summary、test_ids、suite_ids、upstream/fixed 的 description/source_url、evidence_urls。test_ids 关联 run.test，suite_ids 明确缺陷统计和回归跳转范围；缺省采用 `uart_core`，同名的故障控制和协议运行不混入 DUT 缺陷对照。
- `inputs`：path、sha256、bytes；`limitations`：实现范围字符串。

未知值使用 `null` 或缺字段，UI 显示“未记录”，不会补成零或 PASS。所有 URL 相对 `docs/` 根目录，或为明确的 HTTP(S) 源码/证据地址。数据文本通过 DOM 文本节点插入；只有严格需求结果矩阵使用本地 Apache ECharts SVG 渲染，概览时间轴、数字波形与架构图使用原生 SVG。

概览的错误关联对照读取已归档 VCD，在一条共用时间轴上显示原版、修复版两条 `PRDATA`。轴以所选 LSR 完成为零点显示前后各 20 ns，旁边保留该次完成的绝对时间；`PENABLE` 仅在两版对应采样一致时共用。三个 RBR 队首字节 `0x10 / 0x96 / 0x20` 可切换，默认选择 `0x96`。共享轴必须通过时间单位及所选事务的对齐检查，不能对齐的数据不强行叠加。日志、原始 VCD、完整波形与源码入口保留各自来源；此视图不运行新仿真。

当前“缺陷对照”矩阵为 4 项严格需求 × 原版/修复版 × seeds 1/2/3，共 24 个原始运行状态。每格只接受一条匹配的 UART 核心记录；缺失或歧义保留“未记录”。点击格子或使用键盘下拉框可选择同次日志、报告、源码和回归记录，已归档波形才提供波形入口。ECharts 不可用或渲染失败时，矩阵使用可点击 HTML 表格；原生 SVG 时间轴独立于 ECharts。

图表资源来自 `scripts/dashboard-charts/` 的固定依赖：ECharts 6.1.0、zrender 6.1.0、tslib 2.3.0；构建工具为 esbuild 0.25.12。在项目根目录执行以下命令可重新生成 `vendor/`：

```bash
npm --prefix scripts/dashboard-charts ci
npm --prefix scripts/dashboard-charts run build
```

入口仅注册 `HeatmapChart`、`GridComponent`、`TooltipComponent`、`VisualMapPiecewiseComponent` 和 `SVGRenderer`，输出 IIFE 设置 `window.UARTECharts`；`chart-view.js` 仅提供 `window.UARTCharts.renderMatrix`。生成器复制这些资源，页面使用本地 classic script，无运行时模块导入。`vendor/SHA256SUMS`、许可和版权通知须随 bundle 保留；许可范围见根目录 `NOTICE.md`。

波形：滚轮缩放，背景拖拽平移，单击设置游标，红色手柄拖动游标；聚焦波形后可用左右键移动游标、`+/-` 缩放、`Shift+左右` 平移、`Home` 查看全程。APB 事件时间可点击定位。只绘制当前窗口内的记录区间，首个事件之前保留“未记录”。

首次打开含 UART 的波形时，默认选择已有的 reset、APB 握手/读值及 RX/TX/IRQ；独立协议波形选择 reset、APB 控制、地址和读写值，默认最多九个已有信号。绘制顺序优先显示握手信号，之后保留该波形的用户选择，全部信号仍可勾选。

本地原始 VCD 链接始终独立保留。完整信号层次与波形分析可使用 Surfer：仅当 VCD 属于项目已发布的路径白名单、且 SHA-256 与输入清单匹配时，才显示该可选入口。链接使用 `load_url` 引用项目 GitHub Pages 上的公开 VCD，以 `startup_commands` 携带有效游标和窗口；它需要网络，并不成为离线图表或本地 VCD 的依赖。
