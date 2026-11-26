# 工程文档

本项目验证 PULP APB UART 的明确功能子集，提供未修改上游 RTL 与独立修复版的可复现对照，并使用独立从设备验证 APB Agent 的等待、取消及超时行为。运行环境和入口见 [项目 README](../README.md)，版本、下载与包内目录说明见 [发布说明](../RELEASE.md)。

## 设计与验证

| 文档 | 内容 |
| --- | --- |
| [验证架构](architecture.md) | Agent、独立观测、Scoreboard、FIFO 时序模型、RAL 与复位处理 |
| [接口与寄存器](registers.md) | 字节地址、DLAB、寄存器副作用、分频与上游行为 |
| [验证计划](verification_plan.md) | 功能需求、测试场景、检查器及范围边界 |
| [上游 RTL 发现](rtl_findings.md) | 源码依据、缺陷及对应严格需求 |
| [本地 RTL 修复约定](rtl_fixes.md) | 错误标记、中断行为与保留的实现边界 |
| [RAL 实现](../tb/ral/README.md) | 四寄存器双 map、互斥 frontdoor 与观察式预测 |
| [检查器敏感性](checker_sensitivity.md) | 受控故障、指定错误 ID、正常对照与判定条件 |
| [独立 APB 协议验证](apb_protocol.md) | 可编程从设备、等待/错误响应、复位中止、超时与恢复要求 |
| [APB RAM / MBIST 子系统](subsystem.md) | 自研控制器、March C−、复位和访问仲裁、独立故障验证和证据 |
| [控制器综合、STA 与扫描链](../flow/frontend/README.md) | 标准单元映射、时序约束、门级比较与扫描验证流程 |
| [离线交互工作台](dashboard.md) | 数据生成、真实 VCD 解码、游标/缩放和证据分发 |

## 结果与证据

当前完整验收见 [CI 45321619200](https://github.com/jiangzheyi1234-star/apb-uart-uvm/actions/runs/45321619200)，实测源码为 `127f21e0d695cd0e6aa32b46541b158196058679`。118 次仿真进程按范围分别统计：修复版 UART 核心与 RAL 为 **48/48 PASS、2,261 帧**；原版核心为 **33/45 PASS、12 个严格需求原始 FAIL**；检查器实验为 **4 个指定故障原始 FAIL / DETECTED、6 个正常对照 PASS**；独立 APB 协议为 **9 个正向 PASS、3 个超时原始 FAIL / DETECTED、3 个恢复对照 PASS**。这些预期故障未被改写成 PASS。

同次 Linux CI 的 74 项 Python 测试及 100 项核心矩阵验收均通过。RAL 三个 seed 均未产生 `RegModel` 警告，每次仍有两条 UVM 库警告；四寄存器范围和运行边界见 RAL 文档。

| 文档或报告 | 内容 |
| --- | --- |
| [验证结果](validation.md) | 核心/RAL/负向对照的独立统计、工具检查与复跑入口 |
| [覆盖缺口分析](coverage_analysis.md) | 功能 bins、RTL LCOV 分母与剩余未覆盖项目 |
| [核心与 RAL 报告](release/index.html) | 双 RTL 核心矩阵、RAL、原始日志、数据库和代表性波形 |
| [RAL 与检查器报告](features/index.html) | RAL 访问计数、四类故障检出与六次正常对照 |
| [独立 APB 协议报告](protocol/index.html) | 正向、超时负向及恢复对照的原始状态、审计分类和代表性 VCD |
| [RAM / MBIST 子系统报告](subsystem/report.json) | 12 次独立 UVM 运行及同次日志和 VCD，通过工作台验证计划导航 |
| [前端基线报告](frontend/report.json) · [Hold 修复证据](frontend_hold/README.md) | 同约束下的控制器综合、STA、门级对照及扫描检查，两版结果从工作台「实现与 DFT」导航 |
| [GitHub CI 记录](ci/README.md) | 远端运行的提交身份、步骤状态与原始验收报告 |

生成的 [工作台首页](index.html) 可 [在线查看](https://jiangzheyi1234-star.github.io/apb-uart-uvm/)。**源码 ZIP 不包含生成证据**，其中 `web/dashboard/` 是源模板；离线阅读前，按 [发布说明](../RELEASE.md) 下载匹配版本的证据 ZIP 并叠加解压到源码项目根目录，保留 `docs/assets/`、`docs/data/`、`docs/release/`、`docs/features/`、`docs/protocol/` 的相对目录结构。各报告的 SHA-256 清单用于核对原始输入，不能将其他版本的证据视为当前源码的运行结果。

第三方来源、许可及文件校验见 [NOTICE](../NOTICE.md)、[上游来源清单](../third_party/apb_uart_sv/manifest.json) 与 [许可证](../LICENSE)。
