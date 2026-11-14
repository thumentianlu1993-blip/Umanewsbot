# 首次发布与恢复记录

PR #310 已合并为 `6d0f37c5c9cb97a7c781a292af86be3dc500708e`，提交树与 420 项范围 CI 完全一致。生产候选 `24de56e2` 的 264 项测试零跳过，代码、修复清单与执行编排经独立审核。用户明确批准原精确发布包后执行；人工门禁仅引用根 `AGENTS.md`。

## 2026-11-14 实际结果

以下时间为北京时间：

- 10:58、11:02 两次启动预检分别遇到 Compose 参数顺序及混合日志 JSON 解析问题，均在停止应用和写数据前退出；原服务保持运行。修正实际执行脚本并经原审核者复审后，同候选、同清单重试。
- 11:07 完成调度暂停、worker 排空和受影响数据备份：1,199 场、17,708 条原赛果、17,794 条原出马记录、8 个年度目标及控制记录。压缩备份 3,132,885 字节，SHA256 `0d36d445e6ed8baf98590dcef81ca758c6ef4ee193590428f6866fea9de1747f`。
- 11:08 三包 dry-run、apply 和重复核验均通过。Web 切换为候选并完成 Nginx 检查与 reload。全量后值、未批准字段保持、712 条非五地区后台记录保留及 schema0084 核验通过。
- 11:09 公网页面抽查在法国 event756 Quincey 上失败：脚本预期后台的 6 条赛果全部展示，实际为 0 条。协调器按获准包自动执行逆序条件恢复。
- 11:10 三包恢复成功、四应用恢复 `282ae4f9`、Nginx reload 和 root/www 首页、healthz、赛事日历通过，发布锁释放。随后逐字段复核 1,199 场全部原业务值、17,708 条赛果和 17,794 条出马记录已恢复；只有操作更新时间变化，schema 未变。应用与恢复审计日志保留。

**当前已合并，但发布已回滚；五地区隐藏规则和本次历史修复均未保留在线上。**

## 验收失败根因

event756 不在本次 1,199 场修复范围内，是盘点中明确保留给既有 writer 的 5 场之一。它的 `write_owner=data_sync`，当前版本为 15；公开读取因 `data_sync_enrollment_policy_drift` 拒绝展示赛果。原版本和候选版本的公网均为 0 条，产品行为没有因本次变更改变。

错误发生在执行验收脚本：直接把后台行数当作页面应展示行数，忽略了既有公开读取规则。修订脚本根据同一公开规则计算预期，并保留此场负向检查；普通历史赛果与已获准公开的 live 赛果仍要求完整行数。

## 证据

本机 `/Users/mentianlu/.codex/runtime/five-region-race-governance-20261113/`：

- `merge-proof.json`、`delivery.json`、`execution-review-approved.json`：合并、CI 和执行审核绑定。
- `backup-proof.json`、`apply.json`、`database-verification.json`：真实备份、提交与全量后值核验。
- `restore.json`、`rollback.json`、`rollback-public.json`、`restored-verification.json`：恢复、服务及全部原业务值复核。
- `event756-public-contract-proof.json`：原/候选网页均为 0 条的实际证据和公开读取拒绝原因。
- `attempt-1/`、`attempt-2/`：两次无生产业务变动的预检记录；远端也保留原执行文件和日志。

重新执行的清单身份和条件见 [修订发布包](release_retry.md)。94 场未补齐项、20,942 个未物化目录的原边界不变。
