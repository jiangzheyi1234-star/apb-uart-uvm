# APB UART UVM

[![Verification](https://github.com/jiangzheyi1234-star/apb-uart-uvm/actions/workflows/verification.yml/badge.svg?branch=main)](https://github.com/jiangzheyi1234-star/apb-uart-uvm/actions/workflows/verification.yml)

[English](README.en.md) · [技术文档](docs/README.md) · [验证工作台](https://jiangzheyi1234-star.github.io/apb-uart-uvm/) · [Releases](https://github.com/jiangzheyi1234-star/apb-uart-uvm/releases/latest)

基于 PULP APB UART 的 SystemVerilog/UVM 模块级功能验证环境。包含独立 APB/UART Agent、双向 Scoreboard、周期级 FIFO 模型、DLAB 感知寄存器模型、断言、覆盖率与自动回归。

## 功能

- APB 建立/访问阶段驱动、事务监视及协议断言。
- 独立 RX 激励与 TX/RX 引脚解码；数据检查不读取 DUT 内部 FIFO 或状态机。
- TX 容量预测、RX 第 17 帧保留、空读、地址镜像、错误帧及帧中复位检查。
- IER/LCR/DLL/DLM 四寄存器 RAL：双 map、加锁 frontdoor、LCR 保存/恢复和被动 bank predictor。
- 四项受控故障与注入前后正常对照，验证指定检查器能发现错误。
- 独立 APB Agent 资格验证：可编程从设备提供等待、错误响应、复位中止和超时恢复场景。
- 离线交互工作台：筛选回归、查看覆盖缺口、缩放真实 VCD、定位 APB 事件，并链接原始日志与源码。
- 固定工具版本、seed、源码快照及原生覆盖数据库；GitHub Actions 执行真实 UVM 仿真。

## 运行环境

工具链为 Python 3.12、Verilator 5.054、Accellera UVM 2020.3.1，工具下载固定 SHA-256。[完整 CI 45321619200](https://github.com/jiangzheyi1234-star/apb-uart-uvm/actions/runs/45321619200) 已在 GitHub Ubuntu 24.04 runner 完成 UART、RAL、原版对照及独立 APB 协议验收，实测源码提交为 `127f21e0d695cd0e6aa32b46541b158196058679`。Questa/VCS 入口已提供，尚无商业仿真器动态验收记录。

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

### 独立 APB 协议验证

UART DUT 的 `PREADY` 恒为 1。APB Agent 的等待与取消行为使用独立从设备验证，通过 `--suite apb_protocol` 选择 `sim/files_protocol.f`，与默认 `--suite uart` 使用不同的测试平台和编译缓存。

```bash
# 完整协议审计：9 次正向 + 3 次预期超时 FAIL + 3 次正常恢复对照
python3 py/run_protocol_checks.py --trace --out results/protocol

# 单独运行正向协议类
python3 py/run_linux_regression.py --suite apb_protocol \
  --test apb_wait_state_test --seeds 1 --trace --out results/protocol_wait
```

协议正向运行要求 `APB_AGENT_TEST_PASS`；UART 仍要求 `UART_UVM_TEST_PASS`。协议审计仅在唯一 `APB_TIMEOUT`、激活/恢复完成标记、正常退出、零 FATAL、恢复传输统计及同一二进制/源码身份均满足要求时记录 `DETECTED`，原始超时运行仍为 `FAIL`。协议运行次数和 APB 传输数不并入 UART 帧数或功能覆盖率。方法与范围见 [APB 协议说明](docs/apb_protocol.md)。

原版 RTL 的严格需求存在功能失败，可单独复现：

```bash
RTL_VARIANT=upstream bash scripts/run_full_regression.sh --out results/upstream
# 上条命令应返回 1；继续单独执行验收，不以 && 连接。
python3 py/validate_acceptance.py --fixed results/core/report.json \
  --upstream results/upstream/report.json --out results/acceptance.json
```

## 当前实测结果

以下结果来自上述完整 CI 的实际报告。UART、原版缺陷对照、检查器实验及 APB 协议各自保留统计范围和原始状态，定义见 [验证记录](docs/validation.md)。

| 检查范围 | 结果 |
| --- | --- |
| 修复版核心回归 | 45/45 PASS；1,039 TX + 1,216 RX 帧 |
| RAL 专项 | 3/3 PASS；168 次写、291 次 mirror 读 |
| 核心 + RAL | 48/48 PASS；16 类场景、2,261 帧 |
| 原版核心对照 | 33/45 PASS；12/45 严格需求原始 FAIL |
| 检查器对照 | 4/4 指定故障原始 FAIL、分类 DETECTED；6/6 正常对照 PASS |
| 独立 APB 协议 | 9/9 正向 PASS；3/3 超时原始 FAIL、分类 DETECTED；3/3 恢复对照 PASS |
| Linux Python 工具测试 | 74/74 PASS |
| 双核心矩阵验收 | 100/100 检查通过 |
| 核心功能 bins | 272/277，98.19% |
| 帧格式 × 波特周期交叉 | 96/96 |
| RTL LCOV 行 / 分支 | 453/474，95.57% / 1,670/2,120，78.77% |

该次 CI 共执行 118 次仿真进程：修复版核心 45 次、RAL 3 次、原版核心 45 次、检查器实验 10 次、APB 协议 15 次。**48/48** 仅指修复版 UART 核心与 RAL；预期故障运行仍为原始 FAIL，不能把 118 次统称为全部 PASS。功能覆盖率只来自修复版核心 45 次，不与 RAL 或协议套件混算；5 个无效中断编码诊断 bin 保持未命中。

本次 RAL 的三个 seed 均为零 `RegModel` 警告；每次运行仍保留两条 UVM 库警告。完整日志及对应源码身份随证据包保存。

## 交互工作台

按验证范围选择验证项，可核对映射的 UVM 用例、归档运行和原始状态。点击 FAIL 可查看日志摘录与原始日志，并打开已归档的同次波形。[计划与回归](https://jiangzheyi1234-star.github.io/apb-uart-uvm/#plan)

正式报告首页使用 [验证工作台](https://jiangzheyi1234-star.github.io/apb-uart-uvm/)，集中展示 UART 核心、RAL、检查器对照和独立 APB 协议结果，分别保留各自分母及原始状态。波形来自归档 VCD，支持游标、缩放、平移和 APB 事件定位；读数据按时钟上升沿前的信号值解码，避免把沿后更新误作已采样响应。波形诊断不代替 UVM 检查器结果。

原始静态报告继续保留在 [UART 回归](docs/release/index.html)、[RAL 与检查器](docs/features/index.html)、[APB 协议](docs/protocol/index.html)。工作台的生成、数据校验和离线使用见 [工作台文档](docs/dashboard.md)。

## 源码与文档

```text
rtl/          固定版本的未修改上游 RTL
rtl_fixed/    本地修复版，每次编译选择一套 RTL
tb/           APB/UART Agent、Scoreboard、RAL、SVA、coverage 和测试
sim/          编译文件列表及商业仿真器入口
py/           回归、覆盖分析、验收与发行打包
scripts/      固定版本工具准备与核心回归入口
tests/        Python 工具与发行包检查
web/dashboard/ 无网络依赖的工作台源模板
docs/         工程文档及生成的工作台、数据和验证证据
third_party/  上游许可证及导入清单
```

[架构](docs/architecture.md) · [寄存器](docs/registers.md) · [验证计划](docs/verification_plan.md) · [RTL 发现](docs/rtl_findings.md) · [修复约定](docs/rtl_fixes.md) · [RAL](tb/ral/README.md) · [覆盖缺口](docs/coverage_analysis.md) · [APB 协议](docs/apb_protocol.md) · [工作台](docs/dashboard.md)

## 版本分发

Release 分别提供源码、验证证据及 CI 原始产物，附 `SHA256SUMS`。源码包包含 `web/dashboard/` 源模板，不携带工具缓存或生成数据；证据包提供 `docs/index.html`、`docs/assets/`、`docs/data/` 及 `release/features/protocol` 原始报告。将同版本证据包叠加解压到源码根目录后，可直接双击 `docs/index.html` 离线查看，无需服务器或 CDN。每个归档有独立的逐文件校验清单。

[发行说明与复核方法](RELEASE.md) · [变更记录](CHANGELOG.md) · [贡献说明](CONTRIBUTING.md)

## 范围与许可

RTL 来源为 [pulp-platform/apb_uart_sv](https://github.com/pulp-platform/apb_uart_sv)，固定提交 `dfad6e04d19cc9481d3cd2750b45b970dc61271b`。`rtl/` 保持原始字节；`rtl_fixed/` 的本地修改未声称已被上游接收。接口使用字节偏移 0–7，位周期为 divisor + 1 个时钟。

范围不包含完整 16550 兼容性、任意波特率失配、活跃传输时清 TX FIFO、持续 RX 超载、传输中配置热切换及四态签核。

RTL 及其派生修改保留 Solderpad Hardware License 0.51。新增验证代码、工具和文档使用 MIT，见 [LICENSE](LICENSE)、[NOTICE](NOTICE.md) 和 [第三方来源](third_party/apb_uart_sv/manifest.json)。
