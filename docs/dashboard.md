# 离线交互验证工作台

工作台将已归档的 UVM 日志、原生覆盖数据库及 VCD 接成可追溯的诊断视图。它提供回归筛选、覆盖缺口、交互波形、源码架构和原版/修复版缺陷对照。页面中的统计来自输入证据；生成页面本身不执行仿真，也不产生新的 PASS。

总览的错误关联案例配对同一 seed 的原版和修复版运行，从 `uart_error_association_test` 的 VCD 解码结果中找出 `0x10 / 0x96 / 0x20` 三次队首读取。点图按队首字节比较读到的 `LSR.PE`。中间字节的原版 LSR 为 `0x61`，修复版为 `0x65`。每个采样点都能定位对应版本和字节的 LSR 读事务。展开“原始日志”查看同次运行，展开“全部验证结果与证据来源”核对各套件结果、实测提交及输入清单。

## 图表与严格需求矩阵

概览点图和“缺陷对照”矩阵使用本地捆绑的 Apache ECharts 6.1.0 SVG 渲染器。当前矩阵显示 **4 项严格需求 × 2 个 RTL 版本 × 3 个 seed，共 24 格**；每格对应一次 UART 核心归档运行，按原始 `PASS`、`FAIL` 或其他状态显示。缺失或存在多条匹配记录时保留“未记录”，不推定通过。该矩阵不加入 RAL、APB 协议或检查器故障对照，也不增加运行次数或覆盖率。

点击矩阵格，或使用“选中运行”下拉框进行键盘选择，可查看该次运行的测试、版本、seed、原始状态、诊断计数及说明，并打开原始日志、报告、对应源码和回归记录；只有归档了该次运行波形时才提供波形入口。图表依赖缺失或渲染失败时，概览保留原生点图，矩阵回退到可点击的 HTML 表格，证据选择仍可使用。

## 验证套件与判定

| 范围 | 执行入口与标记 | 工作台统计 |
| --- | --- | --- |
| UART 核心 | 默认 `--suite uart`；`UART_UVM_TEST_PASS` | 原版与修复版分别列出，数据帧与核心覆盖率单独汇总 |
| UART RAL | `uart_ral_test`；`UART_UVM_TEST_PASS` | 四配置寄存器的访问、镜像预测和双向数据比对，不合并专项稀疏覆盖到核心 |
| 检查器对照 | `run_mutation.py`；激活标记与指定错误 ID | 原始 `FAIL` 与审计 `DETECTED` 分列，正常控制单独展示 |
| 独立 APB Agent | `--suite apb_protocol`；`APB_AGENT_TEST_PASS` | APB 完成/读/写、等待和中止次数，不加入 UART 帧数或功能覆盖率 |

UART DUT 的 `PREADY` 恒为 1，因此 APB 等待、错误响应、复位中止和超时由独立可编程从设备提供。该套件使用 `sim/files_protocol.f`、独立包及顶层实例；每次编译的顶层名仍为 `tb_top`。ASCII 暂存目录和编译缓存与 UART 隔离，不使用 UART 的 `RTL_FIXED` 运行标记，也不导出 UART 功能覆盖率。

```bash
# Linux/WSL：完整协议审计的默认矩阵
python3 py/run_protocol_checks.py --trace --out results/protocol

# 仅一个正向类；默认套件仍为 uart，协议访问须明确选择
python3 py/run_linux_regression.py --suite apb_protocol \
  --test apb_wait_state_test --seeds 1 --trace --out results/protocol_wait
```

默认协议矩阵为三类正向 × seeds 1/2/3，共 9 次；专门超时需求类 × 3，共 3 次；随后正常等待类恢复对照 × 3，共 3 次。15 次进程的原始结果分别保存。审计仅接受同一二进制和源码快照，且超时负向必须恰好出现一次 `APB_TIMEOUT`、零 FATAL、正常退出、无正常 PASS 标记，以及按顺序出现的 `APB_TIMEOUT_ARMED` 和 `APB_TIMEOUT_SCENARIO_COMPLETE`。后者还必须记录超时后的恢复传输。协议要求见 [APB 文档](apb_protocol.md)；实际结论以对应提交的运行报告为准。

## 从证据生成页面

页面生成器读取三个已审计的证据目录：`release/`、`features/`、`protocol/`。前两者保存 UART 核心/RAL 与检查器证据；协议证据由下列命令从真实审计结果打包。输出目录必须为空或尚不存在。

```bash
python3 py/build_protocol_evidence.py \
  --report results/protocol/protocol_report.json --out docs/protocol

# 已准备好 docs/release、docs/features 和 docs/protocol 后生成工作台
python3 py/build_dashboard.py --evidence-root docs --out docs --version 1.2.0
```

发布时可增加 `--commit` 参数并传入实际受测提交 SHA，使架构、覆盖源码和缺陷链接固定到对应版本。省略时源码链接指向 `main`；报告中的编译快照仍保存实际源码身份。

协议打包器重读全部 15 份日志，调用与运行审计相同的纯判定函数，核对日志 SHA-256、原始状态、统计及分类；同时校验各阶段报告、源码快照与暂存映射的一致性。它原样复制报告、日志、版本/编译记录，以及 seed 1 的等待、复位中止和超时负向三份代表性 VCD。二进制身份来自执行时记录，跨系统打包不要求 Linux 可执行文件仍存在。

工作台生成器重新检查各目录 `inputs.json` 中的文件大小和 SHA-256，从原始日志核对计数，并读取原生 `coverage.dat` 与 LCOV 重算功能 bins 和 RTL 覆盖。缺少输入、哈希不符或摘要与原始记录矛盾时，生成失败。工具测试和页面校验不能代替动态 RTL 仿真；环境终止或不完整运行不能作为通过证据。

## 真实 VCD 与 APB 解码

[`waveform_data.py`](../py/waveform_data.py) 仅提取归档 VCD 中的 APB/UART 接口信号，将其声明的时间单位换算为 ns，保留实际离散变化及 `X/Z`。没有记录的区间保持未知，界面不补造状态。缺少时间单位、时间倒退、无有效接口采样等输入会被拒绝。

APB 解码在上升沿使用严格早于该时间戳的信号值，即 **pre-edge** 值。这样可以保留握手发生时的 PRDATA，避免将从设备沿后更新的数据当作该次已采样读值。等待周期统计为 Access 阶段采到 `PREADY=0` 的次数；只有有效握手才记录完成。复位按断言时间处理，将待完成访问标为 `RESET_ABORT`；提前撤销或不完整访问保持相应诊断状态。独立协议从设备的地址不会被错误标成 UART 寄存器。

波形视图支持：

- 滚轮或 `+/-` 缩放，拖动背景平移；`Home` 恢复完整记录范围。
- 单击设置游标、拖动红色手柄移动游标，或直接输入时间；左右键移动，`Shift+左右` 平移窗口。
- 在波形的 APB 事务轨选择一笔访问，核对地址、数据和等待周期。事务区间与时间游标分别标记，信号标签下显示游标值。展开图下的“信号、缩放与运行证据”，可调整视图、选择信号、查阅日志和原始 VCD。
- 从总览直达原始 FAIL、APB 超时波形和核心覆盖缺口。波形上方可跳到下一个等待或异常事件，事件表可按类型筛选。
- 从波形打开同次运行的日志和报告，或定位到回归表中的唯一一行。从回归表进入波形后，可恢复原筛选、排序和页码。
- 窄屏回归列表优先显示测试、seed、原始状态和证据链接，次要计数可从每行的更多运行信息展开。
- 打开对应原始日志、报告和 VCD；每份 VCD 保留 SHA-256，便于使用外部波形工具独立查看。

“信号、缩放与运行证据”内保留本地“打开原始 VCD”，并为项目已发布、列入白名单且 SHA-256 与输入清单一致的 VCD 提供可选“用 Surfer 打开”入口。该入口在外部 [Surfer 浏览器版](https://app.surfer-project.org/) 中加载 GitHub Pages 上的公开归档 URL，并携带有效的当前游标与时间窗口。使用 Surfer 需要网络；离线工作台、原始 VCD 和本地波形查看不依赖该服务。

波形解码是诊断视图，不是新的验证 oracle。`RESET_ABORT` 等视图标签也不等于 UVM 的通过判定；结果仍来自原始测试和审计记录。功能 bins、RTL 行和分支覆盖分别保留实测分母，未知计数显示“未记录”。

覆盖页按所选报告显示三个独立进度条，其后可搜索未命中功能 bin 并跳到源码。展开分组和证据可查原生数据、LCOV 和统计定义。

## 离线使用与分发

| 路径 | 来源与用途 |
| --- | --- |
| `web/dashboard/` | 源码包中的 HTML/CSS/JavaScript 模板及预构建本地图表资源；浏览无需构建、CDN 或在线数据请求 |
| `docs/index.html`、`docs/assets/` | 证据包中的生成首页与运行资源 |
| `docs/assets/vendor/` | ECharts 子集、依赖许可、版权通知及 `SHA256SUMS` |
| `docs/data/dashboard.js` | 本地数据脚本，设置 `window.UART_DASHBOARD`，页面无需 `fetch` |
| `docs/data/dashboard.json` | 同一数据的机器可读版本 |
| `docs/release/`、`docs/features/`、`docs/protocol/` | 保留的静态报告、原始输入和 SHA-256 清单 |

将同一 Release 的源码包与证据包叠加解压到一个根目录，直接打开 `docs/index.html` 即可离线使用，无需启动 HTTP 服务。单独打开尚未装配数据的源模板只会提示缺失，不会生成示例通过记录。原始 HTML 报告仍可从各自 `index.html` 独立打开。

维护图表依赖时，在项目根目录运行：

```bash
npm --prefix scripts/dashboard-charts ci
npm --prefix scripts/dashboard-charts run build
```

锁文件固定 ECharts 6.1.0 及构建工具；[构建入口](../scripts/dashboard-charts/entry.js) 仅注册散点图、热力图、所需组件和 SVG 渲染器。[构建脚本](../scripts/dashboard-charts/build.mjs) 输出 classic-script IIFE、许可文件及 SHA-256 清单到 `web/dashboard/vendor/`。重新运行页面生成器即可将它们复制到 `docs/assets/`；浏览已生成报告不需要 Node.js 或 npm。第三方许可范围见 [NOTICE](../NOTICE.md)。

源码包不包含生成数据、日志或波形；证据包不替代可复跑的验证源码。保留完整相对目录结构并核对独立清单，具体下载和校验方法见 [发布说明](../RELEASE.md)。
