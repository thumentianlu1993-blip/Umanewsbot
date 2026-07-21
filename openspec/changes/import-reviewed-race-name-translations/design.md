# 已审核赛事中文名统一导入与生产写入设计（管理层）

## 权威契约

本文件只做管理性补充。以下文档为本任务的权威契约，不得被本文件覆盖或改写：

- `docs/changes/import-reviewed-race-name-translations/spec.md`：输入锁定、23 条规则与验收标准。
- `docs/changes/import-reviewed-race-name-translations/design.md`：数据流、字段分工、分类、安全/幂等/回滚、bundle 与审计契约。
- `docs/changes/import-reviewed-race-name-translations/rollout.md`：安全检查点、失败与恢复、备份脚本、未来 apply 门禁。
- `docs/changes/import-reviewed-race-name-translations/test_cases.md`：验收用例。
- `docs/race_name_translation_handoff_20260720.md`：交接状态、固定执行顺序（步骤 1–9）与关键安全边界。

若本文件与上述文档冲突，以上述文档为准并修正本文件。

## 当前状态基线（2026-07-21 复核）

- 工具链已实现；最近一轮 review 三项 finding（非动作父 Series 完整行 CAS、非 allowlist 独立中文名覆盖边界、supplemental seriesKey 门禁）已修复并补负向测试。
- 无可发布候选：`T020815Z` 及更早候选全部失效；两次重生成因生产 SSH 超时 fail closed，未产出 artifact。
- 2026-07-21 生产只读探测已恢复：SSH 可执行，`/opt/umanewsbot` HEAD `7ad6ade`，`umanewsbot-web-1` image `sha256:af880cd2…` started `2026-07-20T07:28:13Z`，八容器运行，`/healthz/` 200。该 metadata 只证明可达性，候选生成时仍须按规则 22 在 snapshot 前后各读一次并精确比较。
- 本地基线 2026-07-21 复核绿色：Node 16/16、XLSX 布局 2/2、SQLite Django 20 通过 + 4 项 PostgreSQL 专项 skip、OpenSpec 30/30。
- 全部六份输入 SHA 已复核匹配；`~/Downloads` 四份（日本基线、香港、英国、法国）因 macOS 隐私权限不可读，用户已于 2026-07-21 同字节复制到 `outputs/translate-race-names-20260719/`，生成器锁定路径已切换到该目录（SHA 全部不变），spec/handoff 输入表同步更新。

## 关键决策

### 最终复审由 Claude Code 替代原 codex reviewer 会话

- 背景：交接文档要求复用 codex reviewer 外层会话 `019f7bfb-2543-7523-aebd-3d496bc96422` / 内层 `019f7e38-ab9f-74e1-8932-f42f9c364a48` 做最终只读复审，以维持连续审核链。
- 现实：该会话属于 codex CLI，当前执行者为 Claude Code，无法恢复。
- 决定（用户 2026-07-21）：改由 Claude Code 对最终精确候选做等价完整只读复审，聚焦交接文档点名的四类回归（全部 scope RaceSeries 完整行 CAS、非 allowlist 独立中文名不覆盖、supplemental seriesKey 门禁、SSH non-multiplexing 回归）外加全量常规审查；必须取得 APPROVED 且 actionable finding 清零。
- 约束：不得以测试通过或人工判断替代该复审；审核链替换事实同步记录到 `docs/decisions.md` 与交接文档。

### 其他既有决策

用户已锁定的业务决定（让赛不展示、京成杯秋季赛精确值、香港身份修正、Event 96 例外、219 场补充同步、supplemental 三重匹配、不覆盖独立中文名、不扩到马名）见交接文档第 3 节，本设计不再重复。

## 风险与缓解

- 生产再次不可达：候选生成任何一步失败必须 fail closed，产出 blocked/空目录，禁止复用旧快照。
- `~/Downloads` 输入不可读：在生成候选前解决（用户复制或授权），生成器按同 bytes 哈希+解析，不存在绕过路径。
- 复审口径差异：替代复审必须覆盖交接步骤 7 的聚焦项，并在 evidence 中明示审核链替换。

## 发布顺序

严格按 `rollout.md` 与交接步骤 1–9；本任务不部署应用镜像、不重启服务。若生产代码无法运行受审工具，停止并重新设计发布路径，不得临时复制未提交脚本绕过提交身份。
