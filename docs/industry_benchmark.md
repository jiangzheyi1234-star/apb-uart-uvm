# UART 验证项目对标与增强方向

核对日期：2026-11-23。对标重点是可复现的检查能力、寄存器建模和缺陷证据。双 Agent 与较高覆盖率已经很常见，本项目更适合突出**真实 SV/UVM、独立引脚解码、周期级 FIFO 模型、原版缺陷复现与修复对照、源码到证据的校验链**。下一项有面试价值的增强是 DLAB 感知的 RAL，以及能实际运行的 CI。

本次阅读了下列仓库的公开文档及列出的源码，没有在本机执行别人的回归。对方 README 的覆盖率是作者报告，不能与本项目的统计直接排名；不同 DUT 的寄存器、错误处理和覆盖分母都不同。

本轮借鉴的是 testplan/CSR 组织、独立观测、生成物一致性检查和可复现回归等方法；新增 SV RAL、检查器和 CI 由本项目独立编写，没有移植这些对标仓库的源码。PULP RTL 本身属于已明确标注来源与许可证的第三方代码。

## 五个真实仓库提供不同参照

| 项目 | 已核对内容 | 可借鉴的具体做法 | 本项目应如何取舍 |
| --- | --- | --- | --- |
| [lowRISC/opentitan UART DV](https://github.com/lowRISC/opentitan/tree/master/hw/ip/uart/dv) | 工业 SV/UVM；TileLink agent、UART agent、生成式 RAL、虚拟序列、覆盖模型与 `dvsim`；scoreboard 管理 TX/RX 队列、错误和中断预测 | 从 testplan 展开检查点；CSR 与串行行为联合预测；结束时检查未消费队列；覆盖 FIFO、门限和错误组合 | 学习验证组织方式。其 TileLink、错误帧丢弃与丰富中断规格不同，不能直接套进 PULP APB DUT。来源：[DV 文档](https://opentitan.org/book/hw/ip/uart/dv/index.html)、[scoreboard 源码](https://github.com/lowRISC/opentitan/blob/master/hw/ip/uart/dv/env/uart_scoreboard.sv)。 |
| [pulp-platform/apb_uart_sv](https://github.com/pulp-platform/apb_uart_sv) | 本项目 RTL 来源；仓库已归档；本地固定提交 `dfad6e04d19cc9481d3cd2750b45b970dc61271b` | 保留原始版本、许可证和来源摘要，按真实译码建立寄存器说明 | 它提供 DUT，不提供本项目新增 UVM 环境。简历应分别说明使用的 RTL 与自行新增的验证工作。来源：[固定版 APB 顶层](https://github.com/pulp-platform/apb_uart_sv/blob/dfad6e04d19cc9481d3cd2750b45b970dc61271b/apb_uart.sv)。 |
| [Hithaishisr/verification-of-apb-based-uart-master-core](https://github.com/Hithaishisr/verification-of-apb-based-uart-master-core) | 教学 SV/UVM；两个 UART DUT、两套 APB agent；`uart_sb.sv` 使用两路 analysis FIFO、寄存器覆盖和结束阶段检查；有独立 SVA 文件 | 将用例、寄存器检查、断言分别展示，便于讲解 | 在双端互连之外保留独立 RX 激励与 TX 引脚解码，避免双方共享实现掩盖错误。维持逐字节在线比对、最少检查次数与残留队列门禁。源码：[scoreboard](https://github.com/Hithaishisr/verification-of-apb-based-uart-master-core/blob/main/tb/uart_sb.sv)、[断言](https://github.com/Hithaishisr/verification-of-apb-based-uart-master-core/blob/main/tb/uart_assertions.sv)。 |
| [anlit75/c4o-pyuvm](https://github.com/anlit75/c4o-pyuvm) | 使用同一 PULP 提交；pyuvm、SystemRDL 生成寄存器模型、RTL/门级复用；CI 实际重新生成 RAL/转换 RTL 并做差异检查 | 自动检查生成物漂移；同一测试入口、seed 重放和公开运行产物 | 可学习 RAL 和 CI 的一致性检查；无需为数字验证求职把当前项目扩成 RTL-to-GDS。其 RDL 明确将 FIFO 口、FCR 别名和 DLAB 动态 bank 留给直接 APB 访问，这正是本项目可以深入处理的语义。来源：[RDL](https://github.com/anlit75/c4o-pyuvm/blob/main/regs/apb_uart.rdl)、[CI](https://github.com/anlit75/c4o-pyuvm/blob/main/.github/workflows/verify.yml)。 |
| [smitarekar/apb-uart-verification](https://github.com/smitarekar/apb-uart-verification) | pyuvm/cocotb；独立 TX pin monitor；TX scoreboard 用两路 FIFO 配对；RX/负向测试通过独立 BFM 与 APB 读检查 | 把预期与实际观测分开；明确区分 Python coverage 与 SV covergroup；记录 seed 与采样漂移的调试过程 | 本项目保留原生 SV/UVM 的 factory、virtual interface、SVA、covergroup 经验，并把 RX 也纳入事务级 scoreboard。来源：[scoreboard](https://github.com/smitarekar/apb-uart-verification/blob/main/tb/uart_scoreboard.py)。 |

源码核查也发现一个需要避免照抄的描述：`c4o-pyuvm` 的 RDL/README 将停止位配置写成“RX 支持、TX 未连接”，而本项目固定源代码的 TX 连接 `LCR[2]`、RX 连接被注释。项目文档与寄存器模型应以实际提交为准，核对见 [本地寄存器说明](registers.md)。

## 优先增强能解释的验证语义

| 优先级 | 增强项 | 完成后应有的检查证据 |
| --- | --- | --- |
| P0 | **DLAB 感知 RAL**：IER/LCR/DLL/DLM 建立存储寄存器模型；普通与分频 bank 分开；frontdoor 在切 bank 的多个 APB 操作间保持互斥 | 用观察到的 APB 完成事务显式预测；普通/分频访问交错、地址镜像、随机读写、复位恢复与并发 RAL 序列通过。FIFO 口、IIR/FCR 等有副作用的对象不能机械套普通 RW mirror。新增代码见 [RAL 说明](../tb/ral/README.md)，运行状态以最新验收报告为准。 |
| P0 | **检查器负向对照**：分别让 TX/RX 数据、PE 读回和 IRQ 路径出现受控错误 | 正常运行通过；每种受控错误都被对应 checker 判失败，保留原始 FAIL 与报错标识。顶层已经提供可选 mutation 连接，不能仅凭“存在开关”宣称检测成功。 |
| P0 | **真实 CI**：固定 Verilator/UVM 下载摘要，执行 Python 测试、源码来源校验和一个真实 UVM smoke | 清洁 checkout 可运行，失败返回非零，上传日志与报告；全量回归可按手动或定时入口运行。公开徽章连接实际 workflow，首次远端运行通过后再写 CI PASS。 |
| P1 | **移植检查**：在有授权环境运行 Questa/VCS；记录版本、命令与结果 | UVM 1.2 静态编译兼容记录继续保留。当前实际动态工具是 Verilator/UVM 2020.3.1，不把脚本入口算作商业仿真器运行经验。 |
| P1 | **补充协议检查器测试**：为可复用 APB driver/monitor 单独提供带等待的测试从设备 | 检查等待期间地址/控制稳定、超时与 reset-abort；当前 DUT 的 PREADY 恒 1，现有真实 UART 回归无法证明等待状态覆盖。 |
| P2 | **明确范围的扩展**：波特率失配、短毛刺、活跃 TX 清 FIFO、持续 RX 超载 | 先确定规格与模型，再新增检查和覆盖；不把 DUT 未实现的 break、字符超时或完整 16550 行为加入“已完成”清单。 |

## 当前最有说服力的展示顺序

先用 README 的一条命令运行真实 smoke，展示两路 scoreboard 检查计数。再打开一个原版严格失败与对应修复版通过的日志，沿“触发输入 → 独立观测 → 不匹配 → RTL 根因 → 修复”讲一遍。然后展示周期级 FIFO 满写丢弃和 RX 第 17 帧保留，最后解释覆盖率的分母、剩余诊断 bin 和代码分支缺口。

现有可分享证据见 [实测报告](evidence/index.html)、[验收记录](validation.md) 与 [覆盖分析](coverage_analysis.md)。后续 RAL、mutation、CI 的结果必须来自新增运行记录，不能覆盖旧报告后继续沿用旧源码摘要。这样比继续增加测试类数量或追求没有统计口径的“100%”更有面试价值。
