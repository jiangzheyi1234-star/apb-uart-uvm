# 工程文档

本项目验证 PULP APB UART 的明确功能子集，并提供未修改上游 RTL 与独立修复版的可复现对照。运行环境和入口见 [项目 README](../README.md)，版本、下载与包内目录说明见 [发布说明](../RELEASE.md)。

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

## 结果与证据

| 文档或报告 | 内容 |
| --- | --- |
| [验证结果](validation.md) | 核心/RAL/负向对照的独立统计、工具检查与复跑入口 |
| [覆盖缺口分析](coverage_analysis.md) | 功能 bins、RTL LCOV 分母与剩余未覆盖项目 |
| [核心与 RAL 报告](release/index.html) | 双 RTL 核心矩阵、RAL、原始日志、数据库和代表性波形 |
| [RAL 与检查器报告](features/index.html) | RAL 访问计数、四类故障检出与六次正常对照 |
| [GitHub CI 记录](ci/README.md) | 已归档远端运行的提交、步骤状态与原始验收报告 |

生成报告可 [在线查看](https://jiangzheyi1234-star.github.io/apb-uart-uvm/)。**源码 ZIP 不包含生成证据**；离线阅读报告前，按 [发布说明](../RELEASE.md) 下载匹配版本的证据 ZIP 并叠加解压到源码项目根目录，保持 `docs/release/`、`docs/features/` 等目录结构。各报告的 SHA-256 清单用于核对原始输入，不能将其他版本的证据视为当前源码的运行结果。

第三方来源、许可及文件校验见 [NOTICE](../NOTICE.md)、[上游来源清单](../third_party/apb_uart_sv/manifest.json) 与 [许可证](../LICENSE)。
