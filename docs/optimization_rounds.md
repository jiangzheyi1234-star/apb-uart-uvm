# 五轮工程优化与面试演示

这五轮分别交付可检查的实现或证据。核心回归是 15 场景 × 3 seed；追加 RAL 是 1 场景 × 3 seed，正常回归合计 48 次。4 个受控故障的 FAIL 和 6 次干净对照单独统计。

| 轮次 | 发现与改进 | 可审阅结果 |
| --- | --- | --- |
| 1：对标与岗位匹配 | 对照 OpenTitan、同 DUT 的 PyUVM/RAL 项目和 APB/UART 项目；核实实际 PULP 仓库、字节地址、divisor+1、17 帧容量，避免套用错误接口假设。按广州岗位要求组织验证计划、定位与回归讲解。 | [对标及来源](industry_benchmark.md)、[广州岗位与面试](guangzhou_interview.md)；提交 `736935d`。 |
| 2：补齐寄存器验证 | DLAB 复用地址会使普通线性 RAL 混淆 DLL/THR、DLM/IER。新增四寄存器双 map、APB adapter、锁住 sequencer 的 frontdoor、真实 LCR 保存/恢复和被动 bank predictor。 | [实现及范围](../tb/ral/README.md)；3/3 seed，168 次写、291 次 mirror 读；提交 `2e196a8`。 |
| 3：验证检查器本身 | 正常流通过不足以证明 checker 会报错。对 TX 数据、RX 读回、PE、IRQ 做四类边界受控故障；同一编译产物前后各跑三次干净控制，必须命中指定错误 ID。 | [负向对照原理](checker_sensitivity.md)、[17 份实测日志与报告](features/index.html)；4/4 检出、6/6 干净通过；提交 `cccf401`。 |
| 4：建立远端复现 | 本地工具缓存可能隐藏环境依赖。GitHub Ubuntu runner 从固定官方源码准备工具，跑核心 45 次、RAL 3 次和故障/控制 10 次；保存源码身份与原始覆盖数据库。Action 固定到提交。 | [首个实际成功的 CI](https://github.com/jiangzheyi1234-star/apb-uart-uvm/actions/runs/45206296552)、[workflow](../.github/workflows/verification.yml)；实现提交 `f4cc49b`。 |
| 5：独立复核与展示 | 在包含新 RAL/受控故障开关的当前 TB 上重新运行原版与修复版核心 90 次，100 项验收全部通过；补充中英文说明、可离线审计的证据页、五分钟演示和带真实链接的简历表述。 | [当前 93 次正常/原版运行证据](release/index.html)、[100 项验收 JSON](release/acceptance.json)、[本页演示流程](#五分钟介绍顺序)。 |

## 五分钟介绍顺序

1. **0:00–0:40，问题与范围。** “我使用固定版本的开源 APB UART，自己实现双 Agent UVM、独立参考模型与自动回归。原始 RTL 和本地修复版分别保留；核心目标是把协议、边界与缺陷闭环做成可复现证据。” 打开 [寄存器表](registers.md)，说明 byte offset 和 DLAB 复用。
2. **0:40–1:40，检查独立性。** 打开 [scoreboard](../tb/scoreboard/apb_uart_scoreboard.sv)，沿 APB THR → 期望队列 → TX pin monitor 讲解；反向沿 RX pin monitor → RBR 比对讲解。说明外部周期模型如何区分 FIFO 16 槽和 serializer，为什么 TX 满时要算到同周期出队。
3. **1:40–2:40，一个缺陷闭环。** 打开 [原版发现](rtl_findings.md) 和 [修复约定](rtl_fixes.md)，选 PE 与 FIFO 数据关联的问题。展示 [报告](release/index.html) 中原版 `uart_error_association_test` 的真实 FAIL，再展示修复版同 seed 的 PASS。不要把原版缺陷特征检查通过称为设计正确。
4. **2:40–3:40，一个 UVM 难点。** 打开 [RAL frontdoor](../tb/ral/uart_dlab_frontdoor.sv)：读取实际 LCR，锁 sequencer，切换 bank，访问目标，恢复原 LCR。打开 [predictor](../tb/ral/uart_bank_predictor.sv) 说明 mirror 来自实际完成的 APB，而非仅凭 sequence 预期。
5. **3:40–4:30，证明 checker 有效。** 打开 [四类负向对照](features/index.html)，展示 `tx_data_xor` 触发 `TX_MISMATCH`。指出 4 个原始运行仍为 FAIL；工具只把准确命中预定错误的实验记作 DETECTED，崩溃、超时或其他错误不算成功。
6. **4:30–5:00，覆盖与局限。** 展示 272/277、RTL 行 453/474 和剩余诊断 bin；打开实际 CI。说明 Verilator 的实测结果、Questa/VCS 的未运行入口，以及四态签核、任意波特偏差等未覆盖范围。

## 可现场重跑

在已准备工具的 Linux/WSL 项目目录，单项演示：

```bash
python3 py/run_linux_regression.py --rtl fixed --test uart_ral_test \
  --seeds 7 --coverage --trace --out results/interview_ral_seed7
```

完整演示使用 [README](../README.md) 的核心、RAL、故障控制入口。全新环境需要安装/编译工具，面试前先准备好，现场可用已归档证据说明结果。每次换新输出目录，不复用历史 PASS。

## 可以写入简历的事实

> 基于 PULP 开源 RTL 构建 APB/UART 双 Agent UVM 环境，实现独立引脚比对、周期级 FIFO 模型及 DLAB 感知 RAL；完成 16 类场景、48 次正常回归，自动比对 2,261 帧，核心功能 bin 命中 272/277；以 4 类受控故障检验检查器，保留原版缺陷、修复结果与 GitHub CI 证据。

面试时需要自己解释模型、时序与失败日志；仓库提供讲解材料与可复跑入口，不代表商业芯片签核经历，也不保证岗位录用。
