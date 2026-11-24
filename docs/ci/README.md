# GitHub CI 验证记录

[完整运行 45321619200](https://github.com/jiangzheyi1234-star/apb-uart-uvm/actions/runs/45321619200) 在公开 GitHub Ubuntu 24.04 runner 上实际执行并成功完成，实测提交为 `127f21e0d695cd0e6aa32b46541b158196058679`。本目录保留该次运行的原始记录；其状态不自动代表其他提交。当前 workflow 状态见 [GitHub Actions](https://github.com/jiangzheyi1234-star/apb-uart-uvm/actions/workflows/verification.yml)。

| 远端实跑范围 | 原始结果 |
| --- | --- |
| 修复版核心：15 测试 × 3 seed | 45 PASS |
| 修复版 RAL：1 测试 × 3 seed | 3 PASS |
| 四项边界故障与前后干净对照 | 4 个预期原始 FAIL、6 个 PASS；4/4 指定 checker 检出 |
| 原版核心：相同 15 测试 × 3 seed | 33 PASS、12 个严格需求原始 FAIL |
| 独立 APB 代理资格验证 | 9 正向 PASS、3 超时原始 FAIL/DETECTED、3 恢复 PASS |
| 两套核心矩阵的自动验收 | 100 项检查全部通过 |
| Python 工具与上游文件校验 | Linux 74 项测试通过、无跳过；8 个固定版上游文件字节一致 |

完整运行共 118 次仿真进程：原始 99 PASS、19 FAIL。正常 UART 回归的 **48/48** 只包含前两行，共比对 2261 帧；协议 15 次另行计量，不把受控故障、干净对照或原版对照加入 UART 分母。RAL 三次运行均为 0 条 RegModel 警告，每次保留 2 条官方库配置警告。

文件来源：

- [full_run.json](full_run.json) 是由 GitHub REST API 取得的运行元数据，包含 head SHA、时间、job 和每个步骤结论。完整原版验收、独立协议资格验证及工作台生成步骤均为 `success`。
- [acceptance.json](acceptance.json) 是从该次 GitHub 上传的 artifact 直接复制的原始验收报告，100 项明细保持原样。
- 每个 [Release](https://github.com/jiangzheyi1234-star/apb-uart-uvm/releases/latest) 的 CI 证据附件均按其自身的 `ci_context.json` 确认运行 ID 与提交 SHA，并附逐文件 SHA-256 清单。本目录保存上表所述运行的实测记录，不自动代表最新附件的身份。具体附件名和校验方式见 [发布说明](../../RELEASE.md)；原版或注入故障的原始 FAIL 不改写。

Actions 临时 artifact 的保留期为 14 天；Release 附件用于保留可下载的远端证据。源码仍可按 [项目 README](../../README.md) 的 Linux/WSL 命令复跑。正常回归、负向对照及原版缺陷对照的状态分别判断，没有把任意失败当作预期缺陷。

源码 ZIP 不包含生成证据。离线查看报告时，应按 [发布说明](../../RELEASE.md) 将匹配版本的证据 ZIP 叠加解压到源码项目根目录；也可查看 [在线报告](https://jiangzheyi1234-star.github.io/apb-uart-uvm/)。`full_run.json` 和 `acceptance.json` 中的运行 ID、提交及原始结论保持不变。
