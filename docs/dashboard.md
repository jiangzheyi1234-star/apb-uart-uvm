# 离线交互验证工作台

工作台将已归档的 UVM 日志、原生覆盖数据库及 VCD 接成可追溯的诊断视图。它提供回归筛选、覆盖缺口、交互波形、源码架构和原版/修复版缺陷对照。页面中的统计来自输入证据；生成页面本身不执行仿真，也不产生新的 PASS。

总览的错误关联案例配对同一 seed 的原版和修复版运行，从 `uart_error_association_test` 的归档 VCD 中提取真实信号，在一条共用时间轴上比较两版 `PRDATA`。轴以所选 LSR 完成为零点显示前后各 20 ns，旁边显示该次完成的精确绝对时间。对应片段的 `PENABLE` 采样一致时共用一条握手信号；存在差异时不强行合并。`0x10 / 0x96 / 0x20` 三个 RBR 队首字节可切换，默认选择 `0x96`；该字节对应的原版 LSR 为 `0x61`，修复版为 `0x65`。

三个字节的预期 `PE` 为 `0 → 1 → 0`；`0x96` 对应错误偶校验，且 `FE` 应为 0。seed 1 的关键 LSR 完成时间为 **t = 16,875 ns**，检查期望为 `(LSR & 0x0C) == 0x04`，掩码限定 LSR[3:2]。原始 `0x61 / 0x65` 的差异保留在图中。

展开“需求、检查与修复”，可沿 [RX FIFO 错误状态关联需求](verification_plan.md#rx-fifo-错误状态关联) 查看定向测试、`STATUS` 位检查、Scoreboard 的 RBR 数据比对职责、FIFO/LSR 修复源码，以及原版和修复版的同次日志。“查看此用例回归”打开现有严格需求矩阵，当前证据默认精确选中 `uart_core:upstream:uart_error_association_test:1`，随后可比较这个测试的两版、三个 seed。该定向矩阵为原版 3 次原始 FAIL、修复版 3 次 PASS，不扩展为更广的覆盖声明。

共享轴会核对时间单位和所选事务的对齐条件，不把不匹配的时间轴拼接为同一采样。图旁可打开对应完整波形，完整波形页保留原始 VCD 和 Surfer 入口；缺陷对照与架构视图保留源码链接。展开“全部验证结果与证据来源”可核对各套件结果、实测提交及输入清单。这些图使用原生 SVG，只重绘既有证据，不启动新仿真。

## 计划与回归

在「验证范围」选择「APB 外设子系统 · RAM / MBIST」，展开验证项并选择具体 seed，即可打开同次日志、回归报告与 VCD。故障用例同时展示首错诊断摘录，波形默认定位到 `MBIST fail` 上升沿。子系统的 12 次 UVM 执行有独立的报告和源文件快照。

「实现与 DFT」先对比相同约束和工艺库下的 setup、hold、单元数量与面积，再列出综合、STA、门级仿真和扫描链的两版证据。时序行提供 SDC、完整 min/max 路径和变更记录。门级与扫描行可分别进入修复前后同次执行的波形。[在线实现与 DFT](https://jiangzheyi1234-star.github.io/apb-uart-uvm/#frontend)

QoR 对照采用基线与候选并排的读法，参考 OpenROAD 的差值表。检查阶段与各自产物的对应关系沿用 OpenTitan 的验证计划和结果分层。[OpenROAD QoR Dashboard](https://openroad-flow-scripts.readthedocs.io/en/latest/user/QoRDashboard.html) · [OpenTitan DV 数据](https://opentitan.org/dvdata/)

「Hold 路径分析」用共同的 ps 时间轴对照数据到达与最早允许到达，分别标出基线违例路径、修复后的同一条路径和修复后全局最差路径。选择路径可查看每级引脚、单元、增量延时、累计到达及对应的 STA 原文。所有时间和余量来自已归档的 OpenSTA 报告，图上显示的精度与报告一致。查看同一路径可定位新增的 `BUF_X1`，切到全局最差路径可核对新的终点。[OpenROAD 时序查看器](https://openroad.readthedocs.io/en/latest/main/openroad/web/README.html)

侧栏“计划与回归”默认打开“验证计划”，可切换到“全部运行”使用原有筛选和 CSV 导出。计划由 [`verification-plan.json`](../web/dashboard/verification-plan.json) 声明，通过套件、UVM 测试、RTL 版本和阶段绑定到精确归档运行；当前为 **6 组、15 个验证项、118 个独立运行身份**。

1. 在“验证范围”选择 APB/寄存器、UART 数据流与 FIFO、错误状态/中断/复位、RAL、独立 APB 或检查器对照。
2. 点击验证项查看关联运行，或点击其原始 FAIL 数量，只查看失败记录。
3. 点击具体运行的状态，查看测试、版本、seed、阶段及原始结果。失败运行提供日志摘录，并可打开完整“原始日志”、“原始报告”和已有的“查看同次波形”。从波形“返回验证计划”后保留当前验证项和运行。

当前 **19 条原始 FAIL** 分别为 12 条上游严格需求失败、4 条指定检查器故障和 3 条 APB 超时负向记录；后两类另有审计 `DETECTED`。这些指定用例在 CI 中保留红色 FAIL，由审计检查预期错误及运行完整性，不能把记录数当作独立 DUT 缺陷数或改写为普通 PASS。

19 条原始 FAIL 中，**13 条具备经校验的同次原始 VCD**：12 条上游严格需求和 APB 超时 seed 1。其中 11 份 UART 波形由保留副本补回，逐份匹配原 CI 清单已记录的 SHA-256 和字节数，来源见 [补充清单](release/recovered-vcd/index.json) 与 [恢复说明](release/recovered-vcd/README.md)。其余 6 条显示缺失原因：4 条检查器故障运行未启用 TRACE，APB 超时 seeds 2/3 的 VCD 未保留。原封存输入清单、摘要、报告和运行结果保持原样；补回文件不产生新仿真。

验证项与实际测试的映射方式参考 [OpenTitan Testplanner](https://opentitan.org/book/util/dvsim/doc/testplanner.html)。本项目的映射范围见 [验证计划](verification_plan.md#计划与归档运行映射)。

### TRACE 复现

六条原始 VCD 缺失的失败记录各关联一份独立 TRACE 复现。运行明细保留原始日志、原始 FAIL 和波形缺失原因，并提供“查看复现波形”和“复现日志”。波形页显示复现身份、对应原始运行及双方的源码和二进制 SHA-256。原始回归仍为 118 条，原始 FAIL 仍为 19 条。

复现沿用原记录中的用例、seed、套件、RTL 版本、故障开关和模拟器版本。重编译前核对源码快照及编译选项，两份重编译 ELF 的 SHA-256 均与原 CI 记录相同。运行时启用 TRACE 并指定独立输出文件。六次复现均为原始 FAIL，经指定错误、结束标志与波形字节校验后标记 DETECTED。[复现清单](reproductions/index.json) · [复跑工具](../py/reproduce_failures.py)

## 图表与严格需求矩阵

Apache ECharts 6.1.0 仅用于“缺陷对照”的结果矩阵，资源与 SVG 渲染器均本地捆绑。当前矩阵显示 **4 项严格需求 × 2 个 RTL 版本 × 3 个 seed，共 24 格**；每格对应一次 UART 核心归档运行，按原始 `PASS`、`FAIL` 或其他状态显示。缺失或存在多条匹配记录时保留“未记录”，不推定通过。该矩阵不加入 RAL、APB 协议或检查器故障对照，也不增加运行次数或覆盖率。

点击矩阵格，或使用“选中运行”下拉框进行键盘选择，可查看该次运行的测试、版本、seed、原始状态、诊断计数及说明，并打开原始日志、报告、对应源码和回归记录；只有归档了该次运行波形时才提供波形入口。ECharts 缺失或渲染失败时，矩阵回退到可点击的 HTML 表格，证据选择仍可使用。概览时间轴和数字波形独立于该图表依赖。

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

## 接入其他项目

[`py/workbench.py`](../py/workbench.py) 接收项目自己的测试结果和证据，生成可离线打开的计划、回归和波形视图。生成工具使用 Python 3.10 及以上的标准库，推荐 Python 3.12。已有仿真流程继续负责执行用例并输出结果。

### JUnit XML 快速导入

已有 JUnit 报告时，生成并打开 `results/junit-workbench/index.html`。

```text
python py/workbench.py build --junit results/junit.xml --title "My IP" --out results/junit-workbench
```

工作台按 `testcase` 记录导入 `PASS`、`FAIL`、`ERROR`、`SKIP`，并附上原始 XML。省略 `--title` 时使用不含扩展名的报告名，seed 显示为未记录。需要验证计划、单次日志和 VCD 时，用下方的清单模式补充关联。

### 清单模式演示

```text
python py/workbench.py init --out results/review-input
python py/workbench.py build results/review-input/manifest.json --out results/review-site
```

`init` 提供标明为演示的计数器记录及其配套日志和 VCD。打开 `results/review-site/index.html`，进入「验证计划」，展开验证项并选择 FAIL，可查看该次运行关联的日志和波形。正式接入时，由项目自己的回归脚本生成清单，并为每次 `build` 使用新目录。

### 输入格式 v1

将 `manifest.json` 和所引用的产物放在同一个输入目录下，产物可以位于子目录。以下示例为桥接模块的一次回归，`runs` 中的状态与 seed 由回归流程提供。

```json
{
  "schema_version": 1,
  "project": {"title": "Bridge IP", "version": "nightly"},
  "suites": [{"id": "bridge", "title": "桥接模块回归"}],
  "runs": [
    {
      "id": "bridge-write-42",
      "suite_id": "bridge",
      "test": "write_smoke",
      "seed": 42,
      "raw_status": "FAIL",
      "failure_excerpt": ["Expected write response after request handshake."],
      "log": "runs/write-42/simulation.log",
      "report": "runs/write-42/result.json",
      "vcd": "runs/write-42/waves.vcd",
      "signals": ["tb.dut.clk", "tb.dut.write_valid", "tb.dut.write_data"]
    }
  ],
  "verification_plan": {
    "groups": [{
      "id": "bus",
      "title": "写通路",
      "items": [{
        "id": "write-handshake",
        "title": "写事务握手",
        "summary": "检查写请求与响应的握手顺序。",
        "checks": [{"suite_id": "bridge", "tests": ["write_smoke"]}]
      }]
    }]
  }
}
```

| 字段 | 约定 |
| --- | --- |
| `schema_version` | 固定为 `1`。 |
| `project` | `title` 必填。可选 `version`、`commit` 和 `source_note` 用于标识构建和证据来源。 |
| `suites` | 每个套件声明唯一的 `id` 与可读的 `title`。 |
| `runs` | 每次执行声明唯一的 `id`、已登记的 `suite_id`、`test` 和 `raw_status`，可选 `seed`、`variant` 和 `phase`。seed 为 `0` 到 `2^53−1` 的整数，空值表示未记录。重复执行同一测试时给各次运行独立 ID。 |
| `raw_status` | `PASS`、`FAIL`、`SKIP`、`ERROR`、`TIMEOUT` 或 `DRY_RUN`。状态沿用回归输出。 |
| `failure_excerpt` | 可选的诊断文本行列表，便于从失败记录直接查看关键信息。 |
| `log`、`report`、`vcd` | 可选产物。使用相对于清单目录的文件路径，以 `/` 分隔。工具复制已声明文件并记录 SHA-256，可从对应运行打开。 |
| `signals` | 可选的 VCD 信号完整层级名列表。选择有时间范围和采样值的 1–64 位数字信号，可在浏览器查看交互波形。仅提供 `vcd` 时，可打开原始文件。 |
| `verification_plan` | 可选。每个验证项通过 `suite_id` 和 `tests` 关联套件与用例，可用 `variants` 或 `phases` 缩小范围。没有匹配运行的验证项显示为未记录。 |

### CI 归档

生成目录包含 `index.html`、本地资源、数据及声明的 `evidence/` 产物。SHA-256 用于核验复制后的文件完整性，运行状态来自输入报告或清单。归档整个目录，解压后用浏览器打开 `index.html`。工程内部的日志或波形可按团队已有的权限在本地或内部制品库共享。

以下两步可加到已准备 Python 和工作台脚本的 GitHub Actions job。只要仿真留下了 JUnit XML，失败后也会生成报告，仿真步骤保留原来的状态。清单模式可替换其中的生成命令。

```yaml
- name: Build verification workbench
  id: workbench
  if: ${{ !cancelled() && hashFiles('results/junit.xml') != '' }}
  run: python py/workbench.py build --junit results/junit.xml --title "My IP" --out results/junit-workbench

- name: Archive verification workbench
  if: ${{ !cancelled() && steps.workbench.outcome == 'success' }}
  uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9 # v7
  with:
    name: verification-workbench
    path: results/junit-workbench/
    if-no-files-found: error
```

## 从证据生成页面

页面生成器读取三个已审计的证据目录：`release/`、`features/`、`protocol/`。前两者保存 UART 核心/RAL 与检查器证据；协议证据由下列命令从真实审计结果打包。输出目录必须为空或尚不存在。

```bash
python3 py/build_protocol_evidence.py \
  --report results/protocol/protocol_report.json --out docs/protocol

# 已准备好 docs/release、docs/features 和 docs/protocol 后生成工作台
python3 py/build_dashboard.py --evidence-root docs --out docs --version 1.2.0
```

发布报告时应通过 `--commit` 参数传入实际受测提交 SHA，使架构、覆盖源码和缺陷链接固定到对应版本。省略时源码链接指向 `main`；报告中的编译快照仍保存实际源码身份。

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
- 从波形打开同次运行的日志和报告，或定位到回归表中的唯一一行。“返回总览”、“返回验证计划”和“返回缺陷对照”恢复原案例或选中运行；“返回筛选结果”保留原筛选、排序和页码。
- 窄屏回归列表优先显示测试、seed、原始状态和证据链接，次要计数可从每行的更多运行信息展开。
- 打开对应原始日志、报告和 VCD；每份 VCD 保留 SHA-256，便于使用外部波形工具独立查看。

“信号、缩放与运行证据”内保留本地“打开原始 VCD”，并为项目已发布、列入白名单且 SHA-256 与输入清单一致的 VCD 提供可选“用 Surfer 打开”入口，用于查看完整 VCD 信号层次并继续分析。该入口在外部 [Surfer 浏览器版](https://app.surfer-project.org/) 中加载 GitHub Pages 上的公开归档 URL，并携带有效的当前游标与时间窗口。使用 Surfer 需要网络；离线工作台、原始 VCD 和本地波形查看不依赖该服务。

波形解码是诊断视图，不是新的验证 oracle。`RESET_ABORT` 等视图标签也不等于 UVM 的通过判定；结果仍来自原始测试和审计记录。功能 bins、RTL 行和分支覆盖分别保留实测分母，未知计数显示“未记录”。

## 覆盖与源码下钻

覆盖页保留所选报告的功能 bins、RTL 行与分支三个独立指标，下方用“RTL 源码”和“功能缺口”切换同一检查区域。“RTL 源码”按文件列出 LCOV 行、分支各自的命中数与总数；选择文件可查看全部未命中行和分支，点击位置跳到生成时指定的受测提交及源码行。“功能缺口”保留 bin 搜索、命中阈值、记录原因及源码入口。展开分组和证据可查原生数据库、LCOV 和统计定义。

文件明细使用当前套件与 RTL 版本的归档 LCOV，分支列按导出的 `BRDA` 记录计数。同一源码行可对应多条记录。修复版核心的五个未命中诊断 bin 继续计入功能覆盖分母。

源码定位方式参考 [Verilator 的覆盖工具文档](https://verilator.org/guide/latest/exe_verilator_coverage.html)：官方工具支持按源码行标注覆盖点及导出 LCOV；工作台使用本项目归档的 LCOV 生成文件列表与缺口位置。具体实测边界见 [覆盖缺口分析](coverage_analysis.md)。

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

锁文件固定 ECharts 6.1.0 及构建工具；[构建入口](../scripts/dashboard-charts/entry.js) 仅注册矩阵所需的热力图、组件和 SVG 渲染器。[构建脚本](../scripts/dashboard-charts/build.mjs) 输出 classic-script IIFE、许可文件及 SHA-256 清单到 `web/dashboard/vendor/`。重新运行页面生成器即可将它们复制到 `docs/assets/`；浏览已生成报告不需要 Node.js 或 npm。第三方许可范围见 [NOTICE](../NOTICE.md)。

源码包不包含生成数据、日志或波形；证据包不替代可复跑的验证源码。保留完整相对目录结构并核对独立清单，具体下载和校验方法见 [发布说明](../RELEASE.md)。
