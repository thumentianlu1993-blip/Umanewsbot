# 赛卡测试合同校正

## 最小修改

仅修改两份测试文件，应用和默认开关不变：

- `test_race_live_racecard_sync.py` 的普通赛卡完整字段断言不再要求虚构的 `status=declared`。
  既有 normalizer 只在明确 NR 信号时提供退赛状态，避免无信号刷新把已退赛马匹重置。
- 同文件的资格例外 E2E 用例保持 2026 自然年与当地日期一致，继续用原 LISTED 等级测试
  精确例外进入 prepare、manifest 和 initializer；不绕过模型年份校验。
- `test_race_live_target_eligibility.py` 将原成功例外输入扩展为“2024 年 G1”和“2026 年 LISTED”，
  分别保留年份例外和等级例外覆盖。原错误 commit、事件范围、到期时间和摘要拒绝断言原样保留。

所有测试方法名称保留；没有删除测试、降低权限检查、增加 skip 或修改生产行为。

## 验证与限制

2026-09-10，从固定 main `f62a6edadbe6173c6a5b3ec58ad957916588a15f` 隔离开发。
原两项在既有 Linux/PG CI 和本机均失败：完整字段断言失败，以及不一致自然年的模型错误。
本机实际 RED 为 2 项、1 failure/1 error。

修正后，12 项针对性回归为 10 pass、1 failure、1 error，零跳过：

- 3 项赛卡解析、6 项资格判断及原多地区 NR/缺失状态检查通过；最终资格例外输入再单独复跑
  6 项，全部通过（0.004 秒），错误授权的原拒绝检查保留。
- E2E 用例已越过旧年份错误，随后因 Windows 的目录权限模式不满足 POSIX 检查而失败。
- 既有 provider 退赛保留/显式 NR 回归返回 `snapshot_fetch_failed`。只观察、继续抛出的异常链
  确认原因为 Windows 缺少 `os.statvfs`，没有替换权限检查或伪造该回归通过。

上述测试禁用真实网络和 `.env`，使用隔离 SQLite；不覆盖 Linux 文件权限或 PostgreSQL 语义。
须等待本候选正式 Linux/PG CI 核验完整赛卡路径和 provider 退赛回归，不能宣称本机或全量全绿。
原始日志和方法 AST 对照保存在本机专用 runtime 目录。

`git diff --check` 通过。工作流检查仍有基线五处旧引用，四项合同测试为 3 pass/1 error；
对应治理修复在独立文档候选。本机正式指纹受 POSIX API 限制，字节快照只作补充。
交付引用根 `AGENTS.md`；此候选不含生产操作。
