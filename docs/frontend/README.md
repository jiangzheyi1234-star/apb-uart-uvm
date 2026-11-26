# 控制器综合、STA 与扫描证据

本目录保存 `apb_ram_mbist` 控制器的真实前端测量。外部 64×32 RAM 本体不计入单元面积，也没有使用已表征的 RAM 宏完成时序分析。

| 检查 | 实际结果 |
| --- | --- |
| 标准单元综合 | 559 个单元、58 个触发器，原始映射面积 829.388 µm² |
| 静态时序 | setup +4.88060 ns；hold −0.00636 ns，保留 `TIMING_VIOLATION` |
| 零延时门级功能比较 | RTL、映射网表、扫描网表在 2,711 个检查周期、877 次 APB 事务中一致 |
| 扫描 shift | 一条 58 位真实 `SDFFR_X1` 链，四个模式共检查 232 位 |
| 功能 capture 后移出 | 32 个 `actual_q` 位与独立预期 `0xfffffff7` 比较；其余 26 位不计为 capture 检查 |

两次独立执行的源码快照、测量指标及映射网表、扫描网表、链顺序、约束和单元模型 SHA-256 一致。原始报告继续保留时序违例状态，没有将成功执行工具等同于时序收敛。

可从 [报告](report.json)、[SHA-256 清单](inputs.json)、[综合统计](inputs/synthesis_statistics.txt)、[完整 setup/hold 路径](inputs/sta.log)、[动态日志](inputs/gate_simulation.log)、[扫描链顺序](inputs/scan_chain.json) 和 [原始 VCD](inputs/gate_smoke.vcd) 复核。两次原始过程记录位于 [首次报告](inputs/original_report.json) 与 [独立复跑报告](repeat/original_report.json)。部分原始记录引用未分发的构建中间物；本目录不包含二进制。

VCD 来自同一次真实零延时仿真，两个视图分别展示 APB/门级输出及扫描信号。扫描默认窗口为实际 capture 移出区间，解码器逐一核对 32 次检查时间、对应链位置及真实 `SCAN_OUT` 值。APB 事件按时钟边沿前的采样值解码，877 条完成访问与仿真记录一致。它们不增加 UART 的运行次数或功能覆盖率分母。

时序条件为 Nangate45 典型角、1.1 V、25 °C、10 ns 理想时钟、0.1 ns 不确定度及记录在 [SDC](inputs/controller.sdc) 中的 I/O 预算；没有布局、寄生、SDF 或多角收敛。复位按功能模式排除，因此不包括复位恢复/移除检查。扫描期间由 testbench 禁止外部 RAM 访问；生产测试模式隔离、物理扫描布线、ATPG 和故障覆盖率均未验证。

重新执行综合/STA/扫描流程的方法见 [流程说明](../../flow/frontend/README.md)。从仓库根目录，将两份新的真实执行报告打包到一个新目录：

```bash
python py/frontend_evidence.py --report results/frontend_controller_final/report.json \
  --repeat results/frontend_controller_repeat/report.json --out results/frontend_bundle_new
python py/frontend_evidence.py --check results/frontend_bundle_new
```

打包器核对全部原始产物、当前 RTL/工具脚本的源码快照、两次独立执行和公开文件 SHA-256，并拒绝覆盖非空输出目录。审核后可将新包用于本目录。公开集合只包含所列文本、源码、网表、模型、许可证和 VCD；原始日志保持字节一致。公开日志中的 `/var/tmp/` 为通用 Linux 构建路径，不包含个人目录、凭据或本机 Windows 路径。

Python 接口 `frontend_data(base, root)` 返回 `(checks, waves, inputs)`。`base` 为本目录，`root` 为工作台证据根；所有 URL 和输入路径均相对 `root`。缺少本包时返回三个空列表，存在但校验失败时抛出 `ValueError`。四个检查与原有回归行分开计量，门级和扫描波形使用不同 ID，共用同一份真实 VCD。
