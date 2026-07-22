## 0. Pre-declared hypotheses

- [ ] 0.1 (operations) 实现前确认客户端选择策略：有 netkeiba key 的日本候选走 netkeiba 客户端，无 key 保持 JBIS 检索路径（用户 2026-07-22 已确认方向 1）。
- [ ] 0.2 (operations) 实现前确认本 change 不批量修复 ExternalHorse 存量空四字段（仅随批次自然覆盖，批量修复另立专项）。
- [ ] 0.3 (operations) 在更新 proposal 后执行 plan-eng-review，并将 review 结果写入 `.openspec.yaml`。

## 1. netkeiba 客户端

- [ ] 1.1 (integration) 新增 `_NetkeibaClient`：allowed_hosts 仅 `db.netkeiba.com`；按候选 `netkeiba:{id}` 直取马匹页 + 战绩页；无 key 候选 fail closed 回退。
- [ ] 1.2 (integration) 马匹页解析：性别、毛色、出生日期（精度保留）、马主、练马师、生产牧场、父母；页面马名规范化比对候选名，不一致进冲突。
- [ ] 1.3 (integration) 战绩页解析：逐场日期/场地/比赛名/跑道/距离原文与规范化/名次与异常状态/骑师/马号/负磅/时间/奖金；海外行标记；生涯总数与逐场数对账，不一致进缺口。
- [ ] 1.4 (integration) 结构容错：预期表缺失或结构不识别一律 fail closed 记录不可解析，不猜字段。

## 2. adapter 接入

- [ ] 2.1 (integration) 日本 adapter 按候选是否有 netkeiba key 选择客户端；provider-bound 身份成立时四字段锁按既有规则放宽（字段来自页面本身）。
- [ ] 2.2 (integration) 同候选 netkeiba 与既有来源字段冲突时记冲突不覆盖。

## 3. 测试

- [ ] 3.1 (integration) fixture 测试：正常页全字段、同名马 ID 直取无歧义、马名不符 fail closed、缺表/改版不可解析、总数与逐场不符进缺口、海外行、日期精度只有年份。
- [ ] 3.2 (integration) 本地 sqlite 端到端：select → prepare（缓存）→ bundle → commit → 自动首发钩子触发且只发门禁通过马。

## 4. 验证与文档

- [ ] 4.1 (operations) 本地验证矩阵（check、目标测试、完整 stable 回归基线对照、makemigrations --check、openspec validate --strict、git diff --check）。
- [ ] 4.2 (operations) 独立 code review 修复全部 actionable finding；更新 `docs/current_state.md`、`docs/project_status.md`、`docs/deploy_runbook.md`、`docs/decisions.md`；合并 main。

## 5. 生产执行（分步用户授权）

- [ ] 5.1 (operations) 部署 → 首个日本滚动批次全链路（含 xlsx 人工复审）→ 核验批次自动首发（`publish-p0-horses-basic-tier` tasks 7.2 闭环）。
- [ ] 5.2 (operations) 复核 netkeiba 访问条款与限速合规记录；状态文档更新与归档评估。
