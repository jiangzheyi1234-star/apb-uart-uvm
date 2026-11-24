# APB UART UVM

[![Verification](https://github.com/jiangzheyi1234-star/apb-uart-uvm/actions/workflows/verification.yml/badge.svg?branch=main)](https://github.com/jiangzheyi1234-star/apb-uart-uvm/actions/workflows/verification.yml)

[English](README.en.md) · [技术文档](docs/README.md) · [验证报告](https://jiangzheyi1234-star.github.io/apb-uart-uvm/) · [Releases](https://github.com/jiangzheyi1234-star/apb-uart-uvm/releases/latest)

基于 PULP APB UART 的 SystemVerilog/UVM 模块级功能验证环境。包含独立 APB/UART Agent、双向 Scoreboard、周期级 FIFO 模型、DLAB 感知寄存器模型、断言、覆盖率与自动回归。

## 功能

- APB 建立/访问阶段驱动、事务监视及协议断言。
- 独立 RX 激励与 TX/RX 引脚解码；数据检查不读取 DUT 内部 FIFO 或状态机。
- TX 容量预测、RX 第 17 帧保留、空读、地址镜像、错误帧及帧中复位检查。
- IER/LCR/DLL/DLM 四寄存器 RAL：双 map、加锁 frontdoor、LCR 保存/恢复和被动 bank predictor。
- 四项受控故障与注入前后正常对照，验证指定检查器能发现错误。
- 固定工具版本、seed、源码快照及原生覆盖数据库；GitHub Actions 执行真实 UVM 仿真。

## 运行环境

已实测：Ubuntu 24.04 Linux/WSL、Python 3.12、Verilator 5.054、Accellera UVM 2020.3.1。工具下载固定 SHA-256。Questa/VCS 入口已提供，尚无商业仿真器动态验收记录。

```bash
git clone https://github.com/jiangzheyi1234-star/apb-uart-uvm.git
cd apb-uart-uvm
sudo apt-get update
sudo apt-get install -y --no-install-recommends build-essential autoconf \
  flex bison libfl-dev zlib1g-dev help2man ca-certificates z3
bash scripts/bootstrap_verilator.sh
```

## 执行验证

```bash
python3 py/verify_rtl.py
python3 -m unittest discover -s tests -v

# 核心回归：15 个测试 × 3 个 seed
bash scripts/run_full_regression.sh --out results/core

# RAL 专项
python3 py/run_linux_regression.py --rtl fixed --test uart_ral_test \
  --seeds 1 2 3 --coverage --trace --out results/ral

# 使用核心回归记录的同一编译产物执行检查器对照
python3 py/run_mutation.py --baseline-report results/core/report.json \
  --out results/checker_controls
```

每次使用新的输出目录；工具拒绝复用非空目录。暂存工具按字节校验源码并使用 ASCII Linux 编译路径，支持原始 Windows 工作目录包含中文字符。

原版 RTL 的严格需求存在功能失败，可单独复现：

```bash
RTL_VARIANT=upstream bash scripts/run_full_regression.sh --out results/upstream
# 上条命令应返回 1；继续单独执行验收，不以 && 连接。
python3 py/validate_acceptance.py --fixed results/core/report.json \
  --upstream results/upstream/report.json --out results/acceptance.json
```

## 已记录的验证结果

指标来自已归档的实际 Verilator/UVM 运行，统计定义见 [验证记录](docs/validation.md)。

| 检查范围 | 结果 |
| --- | --- |
| 修复版核心回归 | 45/45 PASS；1,039 TX + 1,216 RX 帧 |
| RAL 专项 | 3/3 PASS；168 次写、291 次 mirror 读 |
| 核心 + RAL | 48/48 PASS；16 类场景、2,261 帧 |
| 检查器对照 | 4/4 指定故障检出；6/6 正常对照 PASS |
| 核心功能 bins | 272/277，98.19% |
| 帧格式 × 波特周期交叉 | 96/96 |
| RTL LCOV 行 / 分支 | 453/474，95.57% / 1,670/2,120，78.77% |

48 次分母仅包含核心 45 次和 RAL 3 次；10 次检查器实验单独统计。原版另有 33 PASS、12 个严格需求 FAIL，失败状态保留。功能覆盖率只来自核心 45 次，不与 RAL 或故障对照混算。5 个无效中断编码诊断 bin 保持未命中。

## 源码与文档

```text
rtl/          固定版本的未修改上游 RTL
rtl_fixed/    本地修复版，每次编译选择一套 RTL
tb/           APB/UART Agent、Scoreboard、RAL、SVA、coverage 和测试
sim/          编译文件列表及商业仿真器入口
py/           回归、覆盖分析、验收与发行打包
scripts/      固定版本工具准备与核心回归入口
tests/        Python 工具与发行包检查
docs/         架构、寄存器、验证计划、缺陷和验证证据
third_party/  上游许可证及导入清单
```

[架构](docs/architecture.md) · [寄存器](docs/registers.md) · [验证计划](docs/verification_plan.md) · [RTL 发现](docs/rtl_findings.md) · [修复约定](docs/rtl_fixes.md) · [RAL](tb/ral/README.md) · [覆盖缺口](docs/coverage_analysis.md)

## 版本分发

Release 分别提供源码、验证证据及 CI 原始产物，附 `SHA256SUMS`。源码包不携带工具缓存或仿真生成物；离线查看报告时，将证据包叠加解压到源码根目录。每个归档有独立的逐文件校验清单。

[发行说明与复核方法](RELEASE.md) · [变更记录](CHANGELOG.md) · [贡献说明](CONTRIBUTING.md)

## 范围与许可

RTL 来源为 [pulp-platform/apb_uart_sv](https://github.com/pulp-platform/apb_uart_sv)，固定提交 `dfad6e04d19cc9481d3cd2750b45b970dc61271b`。`rtl/` 保持原始字节；`rtl_fixed/` 的本地修改未声称已被上游接收。接口使用字节偏移 0–7，位周期为 divisor + 1 个时钟。

范围不包含完整 16550 兼容性、任意波特率失配、活跃传输时清 TX FIFO、持续 RX 超载、传输中配置热切换及四态签核。

RTL 及其派生修改保留 Solderpad Hardware License 0.51。新增验证代码、工具和文档使用 MIT，见 [LICENSE](LICENSE)、[NOTICE](NOTICE.md) 和 [第三方来源](third_party/apb_uart_sv/manifest.json)。
