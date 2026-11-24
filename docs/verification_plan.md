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

