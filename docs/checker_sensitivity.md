# 检查器敏感性：先证明错误能被发现

一次普通回归通过，只能证明该次激励下没有观察到检查失败。本项目另外执行了四个明确的负向控制：在验证平台与 DUT 的连接边界施加指定故障，确认对应检查器报出预期错误，再用无故障控制证明测试能够恢复通过。

实际结果为 **4/4 指定故障检出，6/6 注入前后无故障控制通过**。四个故障运行的原始仿真状态都是 `FAIL`；报告另用 `DETECTED` 表示预期检查器发现了该控制故障。原始状态未改写成 `PASS`。

[逐项日志与可审计结果](features/index.html) · [运行工具](../py/run_mutation.py) · [注入连接](../tb/tb_top.sv)

| 指定故障 | 注入位置 | 使用的测试 | 必须出现且唯一的 UVM_ERROR ID |
| --- | --- | --- | --- |
| `tx_data_xor` | DLAB=0、THR 写路径的 DUT 输入数据位 0 翻转，APB monitor 保留原始写值 | `uart_smoke_test` | `TX_MISMATCH` |
| `rx_data_xor` | DLAB=0、RBR 读路径返回数据位 0 翻转 | `uart_smoke_test` | `RX_MISMATCH` |
| `parity_mask` | LSR 读值的 PE 位清零 | `uart_parity_requirement_test` | `STATUS` |
| `irq_stuck_low` | 对外 IRQ 观测连接保持低电平 | `uart_irq_requirement_test` | `IRQ` |

这些是四个选择好的**边界故障控制**，不是新增发现的四个 DUT 设计缺陷，也不是枚举、替换 RTL 运算符得到的完整 mutation campaign。`4/4` 的分母始终是表中四项，不能写成“所有故障检出率 100%”或“验证完整性 100%”。上游 RTL 的实际缺陷与本地修复仍单独见 [RTL 发现](rtl_findings.md) 和 [修复约定](rtl_fixes.md)。

检测条件较严格：日志中必须有与模式匹配的 `MUTATION_ACTIVE`，进程正常退出，UVM_ERROR 数大于零，FATAL 为零，不出现 `UART_UVM_TEST_PASS`，且 UVM_ERROR ID 集合必须恰好等于指定 ID。超时、崩溃、无激活标记以及混入无关错误都不能算检出。

实验先分别执行 smoke、parity requirement、IRQ requirement 三个无故障控制；随后执行四个故障模式；最后再执行相同三个无故障控制。十次进程使用同一记录二进制和 seed 1。工具核对基线报告哈希、二进制 SHA-256、编译前源码快照、基线 PASS 日志，并在实验结束后再次确认二进制未改变。没有修改 `rtl/` 或在每项控制之间换编译版本。

```bash
# 先用当前源码编译并取得包含三个控制测试的实际 fixed PASS 报告。
python3 py/run_mutation.py \
  --baseline-report results/optimization_features_01/report.json \
  --out results/checker_mutations_new
```

基线中的二进制如果已被后续编译覆盖，工具会拒绝执行；应先重跑基线。路径搬迁可用 `--binary` 指定新位置，但文件内容必须匹配基线 SHA-256。

同一版本还单独执行了 `uart_ral_test` 的 seeds 1、2、3，均实际通过。RAL 模型包含 IER、LCR、DLL、DLM 四个配置寄存器；每次日志记录 12 轮随机配置、56 次 RAL 写、97 次镜像读，以及普通/分页预测和复位活动。三次累计为 168 次 RAL 写和 291 次镜像读。这些数字描述已执行访问，不代表穷举全部寄存器值组合；FIFO 弹出等副作用寄存器没有被计入四寄存器镜像模型。

可用下面的命令重新打包两项功能的真实证据。工具会再次读取日志独立核验计数和结果，复制原始报告、17 份仿真日志以及构建/暂存来源文件，并输出逐文件 SHA-256。目标目录必须为空或尚不存在。

```bash
python py/build_feature_evidence.py \
  --ral-report results/optimization_ral_01/report.json \
  --mutation-report results/checker_mutations_01/mutation_report.json \
  --out docs/features
```
