# 验证结果 / Verification results

当前结果来自 [完整 GitHub CI 45321619200](https://github.com/jiangzheyi1234-star/apb-uart-uvm/actions/runs/45321619200)，受测提交为 `127f21e0d695cd0e6aa32b46541b158196058679`。执行环境为 GitHub Ubuntu 24.04、Python 3.12、Verilator 5.054、Accellera UVM 2020.3.1，使用真实 RTL 与 UVM。每份报告的源码快照、工具版本和 SHA-256 清单用于确定对应版本；本地被环境终止的构建不计为通过证据。

完整 CI 共执行 **118 次仿真进程**，原始状态合计 **99 PASS、19 FAIL**。19 个 FAIL 分别为上游严格需求 12 次、UART 指定故障 4 次、APB 超时负向 3 次；它们保持原始失败状态，按各自验收规则另行审计。UART 修复版正常回归仍为 **48/48 PASS**，独立 APB 协议的 **15 次**不加入该分母。

## 核心回归

| 项目 | 修复版 | 未修改上游版 |
| --- | --- | --- |
| 同一套测试矩阵 | 15 场景 × seed 1/2/3 | 15 场景 × seed 1/2/3 |
| 原始运行状态 | 45 PASS，0 FAIL | 33 PASS，12 FAIL |
| 汇总 ERROR/FATAL | 全部 0/0 | 12 个严格需求出现真实 UVM_ERROR，FATAL 为 0 |
| 正常退出与超时 | 全部正常退出，无超时 | 全部正常退出，无超时 |
| PASS 运行 TX/RX 自动比对 | 1,039 / 1,216，合计 2,255 帧 | 1,021 / 955，合计 1,976 帧 |

未修改上游版的 12 个 FAIL 分别为 4 项严格需求 × 3 个 seed：

- `uart_parity_requirement_test`：错误校验没有使 LSR.PE 置位。
- `uart_framing_requirement_test`：低停止位没有使 LSR.FE 置位。
- `uart_error_association_test`：错误状态不能与对应的 FIFO 字节关联。
- `uart_irq_requirement_test`：RX 假中断、无中断编码与确认/撤销行为不满足需求。

这些 FAIL 保留原始日志和状态，未改判为 PASS。其余 33 个原版运行包含缺陷特征检查，通过仅表示行为符合记录。修复版对同样的严格需求全部通过。

发布证据：[93 次回归的 HTML 报告](release/index.html)、[机器可读汇总](release/summary.json)、[输入 SHA-256 清单](release/inputs.json)。其范围是核心双版本 90 次运行加独立 RAL 3 次运行，原始状态合计为 81 PASS、12 FAIL。

两套核心矩阵的 100 项验收全部通过，原始 `ci_acceptance.json` 保存在 [该次 CI](https://github.com/jiangzheyi1234-star/apb-uart-uvm/actions/runs/45321619200) 的产物中。复跑命令见下文；CI 原始产物下载与离线查看方式见 [发布说明](../RELEASE.md)。

## RAL 与检查器敏感性

独立的 `uart_ral_test` 在 seed 1、2、3 实际 **3/3 PASS**，每次验证 IER、LCR、DLL、DLM 四个配置寄存器，记录 12 轮随机配置、56 次 RAL 写和 97 次镜像读，三次合计 **168 次写、291 次镜像读**。普通/分页预测、复位和 bank frontdoor 并发访问均有运行日志。并发后另以原始 APB 读回完整 LCR=`0xF3`，检查 DLAB 和存储格式位均被恢复；该读取不计入 97 次 RAL mirror 读。

| 修复版统计范围 | 运行结果 | PASS 运行 TX / RX 比对 | 合计帧数 |
| --- | --- | ---: | ---: |
| 核心 15 场景 × 3 seed | 45/45 PASS | 1,039 / 1,216 | 2,255 |
| RAL × 3 seed | 3/3 PASS | 3 / 3 | 6 |
| 核心与独立 RAL 合计 | 48/48 PASS | 1,042 / 1,219 | 2,261 |

另行执行的检查器敏感性实验为 **4/4 指定故障检出、6/6 注入前后无故障控制通过**。四种边界故障对应的唯一错误 ID 分别为 `TX_MISMATCH`、`RX_MISMATCH`、`STATUS`、`IRQ`。故障运行保留原始 `FAIL`，另用 `DETECTED` 标记检出；它们不是新增发现的四个 DUT 缺陷，也不是对全部可能故障的穷举。48 次统计范围限定为上表的核心与 RAL，敏感性实验单独计量。

[RAL 与敏感性实验 HTML](features/index.html)、[功能证据汇总](features/summary.json)、[功能证据 SHA-256 清单](features/inputs.json) 包含 58 份仿真日志：核心 PASS 基线 45 份、RAL 3 份、检查器对照 10 份，并保留二进制身份、编译源码快照和暂存映射的交叉核验。基线日志与 UART 核心证据重叠，不代表额外执行 45 次；方法与边界见 [检查器敏感性说明](checker_sensitivity.md)。

## 独立 APB Agent 协议验证

UART DUT 的 `PREADY` 恒为 1。等待、错误响应、复位中止与超时恢复由 `--suite apb_protocol` 选择的独立可编程从设备验证，使用 `sim/files_protocol.f` 和独立 ASCII 编译缓存；不编译 UART DUT，也不使用 `RTL_FIXED` 标记。

| 协议阶段 | 测试矩阵 | 原始结果 | 独立审计 |
| --- | --- | --- | --- |
| 正向 | 等待、复位中止、超时边界控制三类 × 3 seed | 9 PASS，ERROR/FATAL 为 0/0 | 9/9 PASS |
| 超时负向 | `apb_timeout_requirement_test` × 3 seed | 3 FAIL；每次恰好一个 `APB_TIMEOUT`，零 FATAL、正常退出 | 3/3 DETECTED |
| 恢复对照 | 正常等待类 × 3 seed | 3 PASS，ERROR/FATAL 为 0/0 | 3/3 PASS |

协议审计检查三阶段使用相同二进制与源码快照；每个负向运行必须有按顺序出现的 ARMED、唯一超时错误、SCENARIO_COMPLETE，以及超时后完成的三笔恢复传输。另行执行的正常恢复对照也必须通过。15 次协议进程合计观察到 **93 笔完成的 APB 传输**；复位/超时中止不会伪装成完成事务。

协议原始状态为 12 PASS、3 FAIL，`protocol_report.json` 的 PASS 指审计成立。它不代表 15 次原始运行全部通过，也不增加 UART 的 2,261 帧或 277 个功能 bin。详见 [协议要求与结果](apb_protocol.md)、[协议 HTML](protocol/index.html) 与 [机器可读证据](protocol/summary.json)。

## 覆盖率

| 修复版指标 | 实测值 |
| --- | ---: |
| 功能 bins 未加权命中率 | 272/277，98.19% |
| 普通帧格式交叉 | 32/32，100% |
| 方向 × 位宽 × 校验 × 停止位 × 波特周期 | 96/96，100% |
| RTL LCOV 行命中率 | 453/474，95.57% |
| RTL LCOV 分支命中率 | 1,670/2,120，78.77% |

功能统计直接读取合并后的原生 `coverage.dat`，按 bin 的 at_least 阈值计算，未加权。原始 covergroup 中两个 default bin 按工具规则不参与覆盖率；未为提高数字而修改覆盖组或新增排除项。它不等同于加权的 SystemVerilog covergroup API 百分比。RTL 行/分支数据来自 Verilator 导出的 LCOV，单独统计 RTL 文件，未把 UVM 库代码混入设计分母。

图中原版覆盖只合并 33 个 PASS 运行，12 个严格需求失败不贡献合并覆盖。独立 RAL 报告的覆盖率按其 3 次运行单独展示，没有与核心 45 次回归合并；上表的 272/277 仍指核心修复版。协议 15 次及检查器对照也不并入功能或 RTL LCOV 分母。两套 RTL 的代码行分母不同，因此不把两条代码覆盖百分比的差值解释为质量提升。

[覆盖缺口分析](coverage_analysis.md) 记录已覆盖项目与剩余 5 个诊断 bin，并解释代码覆盖率的范围边界。

![核心回归与独立 RAL 的实测覆盖率](release/coverage.svg)

## 复位与引脚证据

[发布报告](release/index.html) 提供原版/修复版错误帧、错误关联和修复版帧中复位等代表性 VCD，保留对应文件 SHA-256。UART 证据目录包含 93 份原始仿真日志、3 个合并覆盖数据库与 LCOV、编译时源码快照和暂存字节一致性映射。独立 [协议证据](protocol/index.html) 另含全部 15 份日志及等待、复位中止、超时负向的 seed 1 代表性 VCD 三份；它们属于不同统计范围。

[交互工作台](index.html) 的“波形与总线”页提供真实接口采样、游标、缩放及 APB 事件定位；[修复版帧中复位原始 VCD](release/inputs/024_waves.vcd) 的 SHA-256 见发布输入清单。图形只从归档 VCD 解码，不替代原始测试结果。

## 自动验收与工具检查

`py/validate_acceptance.py` 对两套核心报告执行 **100 项检查，全部通过**，包含：

- 恰好 15 场景 × 3 seed，两套环境使用相同 TB 文件和 UVM 源码。
- PASS 完成标记、完整 UVM 汇总、真实双向比对数、正常退出及文件存在性。
- 12 个原版严格需求确实因功能 UVM_ERROR 失败，而非超时、崩溃或构建错误。
- 3 个压力测试 seed 产生不同的数据/格式摘要；相同 seed 在两套 RTL 重放相同刺激。
- 从原生数据库重新计数 bins，从 LCOV 重新统计 RTL 行，核对所有 45 个 PASS 数据库都参与合并。
- 编译前源码快照与当前 SV 源码一致，8 个上游文件 Git blob 保持原样。

该次 GitHub Linux CI 的 **74 项 Python 工具测试全部通过**，覆盖日志假成功、超时、失败进程、一次编译多运行、命令预演、覆盖解析、安全解包、协议日志/统计和身份篡改、离线链接、VCD pre-edge 读取，以及 mutation 的激活、指定错误 ID 和前后控制。命令为 `python3 -m unittest discover -s tests -v`。进程替身仅用于 Python 工具测试；本页的核心、RAL、检查器及协议结果来自真实 Verilator 仿真。

静态检查使用 pyslang 12.2.0：两套 RTL + UVM 1.2 全环境为 0 errors、2 条上游 UVM 空循环警告；UVM 2020.3.1 全环境为 0 errors、1 条上游转义字符警告。商业 Questa/VCS 入口尚未实际执行。

RAL 三次运行的 `[RegModel]` 初始化警告均为 **0**：frontdoor 通过 `add_reg(...,0,frontdoor)` 在建模时绑定，完整模型 `lock_model()` 后才查询 map 信息，没有屏蔽或降级警告。每次仍保留官方库的两条运行警告 `[NO_DPI_USED]` 与 `[NO_VISIT_CHECK]`，因此没有宣称零警告。Verilator 编译日志中的标准 UVM 字段宏位宽诊断及原始 RTL 设计诊断也保留。

## 已执行的 GitHub CI 与范围

[完整手动运行 45321619200](https://github.com/jiangzheyi1234-star/apb-uart-uvm/actions/runs/45321619200) 已成功，`full_regression=true` 的上游对照与验收步骤实际执行。其 118 次仿真包括修复版核心 45 次、RAL 3 次、上游核心 45 次、检查器对照 10 次、独立 APB 协议 15 次。100 项核心验收与协议独立审计均通过，74 项 Python 测试全部通过。

运行身份应按该次 CI 的 `ci_context.json`、编译前源码快照与原始报告核对。其他提交不自动继承这次执行状态；单独归档的 [CI 记录](ci/README.md) 仍按其自身运行 ID 和提交解释。

## 复跑

从项目目录执行：

```bash
bash scripts/run_full_regression.sh --out results/new_fixed
RTL_VARIANT=upstream bash scripts/run_full_regression.sh --out results/new_upstream
python3 py/validate_acceptance.py --fixed results/new_fixed/report.json \
  --upstream results/new_upstream/report.json --out results/new_acceptance.json
python3 py/run_linux_regression.py --rtl fixed --test uart_ral_test \
  --seeds 1 2 3 --coverage --trace --out results/new_ral
python3 py/run_protocol_checks.py --trace --out results/new_protocol
```

原版回归命令应返回失败退出码，以保留真实缺陷状态；验收工具会独立检查失败集合是否恰好符合要求。工具不会把任意失败当作已知缺陷。

每次使用新的输出目录。敏感性实验需使用仍与编译二进制哈希匹配的实际 PASS 基线，运行方式见 [敏感性说明](checker_sensitivity.md)。

## 下载与离线复核

[最新 Release](https://github.com/jiangzheyi1234-star/apb-uart-uvm/releases/latest) 分别提供源码包和证据包，具体附件及校验方法见 [发布说明](../RELEASE.md)。**源码 ZIP 不包含生成的报告、日志、数据库或波形**，也不包含 `results/` 和工具缓存。下载匹配版本的证据 ZIP 并叠加解压到源码项目根目录，保留 `docs/assets/`、`docs/data/`、`docs/release/`、`docs/features/`、`docs/protocol/` 的相对结构，即可离线打开工作台和原始报告；也可直接查看 [在线证据](https://jiangzheyi1234-star.github.io/apb-uart-uvm/)。

数据库、波形和日志的原文件 SHA-256 保存在各自证据清单中；源码 ZIP 另附逐文件校验清单。离线复核时应保持包内目录结构，并核对报告绑定的源码版本。

