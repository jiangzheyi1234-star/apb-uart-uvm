# 已执行验证计划

验收范围是 PULP APB UART 的明确功能子集。已归档核心回归使用相同 TB 对原版与修复版各执行 15 场景 × 3 seed，详见 [验证结果](validation.md)。独立 RAL 专项和检查器敏感性实验单独统计。

| 检查项 | 对应测试/检查器 | 修复版动态结果 |
| --- | --- | --- |
| APB Setup/Access、控制信号稳定 | 顶层 SVA，所有场景 | PASS |
| DLAB、寄存器读回、只读写忽略 | smoke、address_mirror | PASS |
| APB THR 到独立 TX 引脚解码比对 | 全部场景 | PASS |
| 独立 RX 引脚解码到 RBR 比对 | 全部场景 | PASS |
| 5～8位、偶校验开关、1/2停止位 | smoke、baud_sweep | PASS |
| 00/FF/55/AA 与随机数据 | smoke、random_stress | PASS |
| TX FIFO16加发送器的17帧短突发 | fifo_boundary | PASS |
| TX 21写接受17、丢弃4及恢复 | tx_overflow | PASS |
| RX16填满/排空、指针回绕 | fifo_boundary | PASS |
| RX第17帧在接收器等待、按顺序排出 | rx_retention | PASS |
| RX非空清空、TX空闲清空 | fifo_boundary | PASS |
| 空RBR读取、不下溢、后续恢复 | empty_read | PASS |
| 高位地址镜像、两bank组合 | address_mirror | PASS |
| 校验/停止位故障独立注入与识别 | error | PASS |
| PE、FE严格需求 | parity_requirement、framing_requirement | PASS；原版 FAIL |
| 正常/错误/正常字节的标记关联 | error_association | PASS；原版 FAIL |
| 四档RX门限，门限下/等于/高于检查 | irq、irq_requirement | PASS |
| 中断优先级、使能、确认、禁用与重触发 | irq、irq_requirement | PASS；原版严格需求 FAIL |
| 传输中复位、残帧清理、恢复新帧 | reset | PASS |
| 多批随机双向流、不同seed、相同seed重放 | random_stress | PASS |
| 3个波特周期×16种格式×2方向 | baud_sweep | 96/96 bins |
| 日志判定、超时、编译失败、旧日志拒绝 | Python 工具测试 | 执行 `python3 -m unittest discover -s tests -v`；结果见对应 [CI 记录](ci/README.md) |
| 原始证据、源码一致性、结果矩阵和原生覆盖再计算 | validate_acceptance | 100项 PASS |

功能 covergroups 的277个有效统计 bin中，272个命中，剩余5个是无效中断编码的诊断项。只有实际观察到的事件计入；没有创建覆盖率截图来代替数据库。

范围边界：活跃 TX 清FIFO、RX持续超载、热切换配置、波特率误差扫描、短毛刺路径、四态验证、完整16550功能。它们未计入已完成需求。

## 计划与归档运行映射

工作台使用 [`web/dashboard/verification-plan.json`](../web/dashboard/verification-plan.json) 维护机器可读映射，以 `suite_id`、`tests`、`variants` 和 `phases` 关联实际运行。当前 6 组、15 个验证项关联核心两版 90 次、RAL 3 次、独立 APB 15 次及检查器对照 10 次，共 118 个独立 UVM 运行身份，每个身份在计划中关联一次。映射保留各套件和阶段，验证项的运行统计与功能覆盖率分别展示。

其中 19 条原始 FAIL 包含 12 条上游严格需求、4 条指定边界故障和 3 条 APB 超时负向记录；后两类由独立审计判定 `DETECTED`，原始状态保留。13 条失败运行已有经校验的同次 VCD，含按原 CI SHA-256/字节数补回的 11 份 UART 文件；其余 6 条明确显示未生成或未保留波形的原因。原封存输入、报告和结果不变。

组织方式参考 [OpenTitan Testplanner](https://opentitan.org/book/util/dvsim/doc/testplanner.html) 的验证项与实际测试映射。侧栏“计划与回归”支持从验证项或原始 FAIL 数量进入精确运行，再打开日志摘录、完整日志、报告及已有同次波形；操作路径见 [工作台说明](dashboard.md#计划与回归)。

## RX FIFO 错误状态关联

需求是错误状态随当前 FIFO 队首字节更新。测试依次注入正常 `0x10`、错误偶校验 `0x96`、正常 `0x20`，每次读 RBR 前检查 LSR：`PE` 应为 `0 → 1 → 0`，`FE` 应保持 0。检查采用掩码 `0x0C`，期望依次为 `0x00 / 0x04 / 0x00`。

| 环节 | 源码与检查职责 |
| --- | --- |
| 激励与状态判定 | [定向测试](https://github.com/jiangzheyi1234-star/apb-uart-uvm/blob/127f21e0d695cd0e6aa32b46541b158196058679/tb/test/uart_extended_tests.sv#L116-L130) 调用 [STATUS 检查](https://github.com/jiangzheyi1234-star/apb-uart-uvm/blob/127f21e0d695cd0e6aa32b46541b158196058679/tb/test/base_test.sv#L33-L37)，比较 `(actual & mask)` 与期望值 |
| 独立数据检查 | [Scoreboard 的 RBR 比对](https://github.com/jiangzheyi1234-star/apb-uart-uvm/blob/127f21e0d695cd0e6aa32b46541b158196058679/tb/scoreboard/apb_uart_scoreboard.sv#L149-L162) 核对 RX 引脚监视器预测的数据顺序；[串行错误计数](https://github.com/jiangzheyi1234-star/apb-uart-uvm/blob/127f21e0d695cd0e6aa32b46541b158196058679/tb/scoreboard/apb_uart_scoreboard.sv#L183-L189) 确认注入被实际解码；LSR 位值由测试判定 |
| RTL 修复 | [FIFO 入队](https://github.com/jiangzheyi1234-star/apb-uart-uvm/blob/127f21e0d695cd0e6aa32b46541b158196058679/rtl_fixed/apb_uart.sv#L120-L139) 保存 `{FE, PE, data}`；[LSR 映射](https://github.com/jiangzheyi1234-star/apb-uart-uvm/blob/127f21e0d695cd0e6aa32b46541b158196058679/rtl_fixed/apb_uart.sv#L209-L213) 取当前队首标记 |

seed 1 的归档记录在 **t = 16,875 ns** 读取 `LSR@0x005`：原版原始值 `0x61`、修复版 `0x65`，掩码后分别为 `0x00`、`0x04`，该次期望为 `0x04`。可在 [工作台案例](https://jiangzheyi1234-star.github.io/apb-uart-uvm/#overview) 对照波形及同次日志。实测范围仅为这个定向场景的 seeds 1/2/3：**原版 3 次原始 FAIL，修复版 3 次 PASS**；这是该需求的定向回归，不代表错误状态关联的全部组合或额外覆盖率。追溯入口说明见 [工作台文档](dashboard.md)。
