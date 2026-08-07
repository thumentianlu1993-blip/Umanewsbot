## 0. 预声明验证假设

- [ ] 0.1 (operations) 一期范围 PASS：候选只来自 1998–2026 年符合规范等级的 G1/G2/G3、J-G1/J-G2/J-G3、JpnⅠ/JpnⅡ/JpnⅢ及证据完整的海外 G1/G2/G3；日本训练身份明确，一匹一候选且保存全部 qualification。任一越界、重复或训练范围推测为 BLOCKER。
- [ ] 0.2 (operations) 批次选择 PASS：每批 1–100 匹，按最高等级、官方锚点、完整官方赛事上下文、唯一 Netkeiba ID、公开状态、重赏次数和最近日期稳定排序；旧 39 blocker 零交集，无 N+1。任一计数、排序或查询预算不符为 BLOCKER。
- [ ] 0.3 (operations) 20 匹 PoC PASS：从第二层冻结20条完整赛事上下文，20/20 先形成唯一官方锚点或稳定上下文 blocker，最终为 pass/partial/稳定 blocker，未知异常为 0，至少 1 匹完成“赛事上下文 → 唯一锚点 → 完整双源 pass”；满足 10 现役、5 退役、2 外国出生线索、2 中央/地方赛事上下文或经审核转籍线索、1 障碍，并覆盖 G1/G2/G3 和 JRA/NAR。抽样线索不充当训练证据；请求账本闭合、单匹总计不超过 6 URL/18 次传输且官方链不超过 3 URL/6 次传输，结束后网络为 false。
- [ ] 0.4 (operations) 100 匹 prepare PASS：100/100 均有 qualification 与身份结论，未知异常和静默遗漏为 0；按最高等级/provider 分层报告，不预设通过率。
- [ ] 0.5 (operations) commit PASS：只写精确批准的 `candidate_pass` 三个空身份字段、来源引用和审计记录；整批无漂移，公开/完整度/履历/P0 来源不变，相同 SHA replay 新增写入为 0。

## 1. 本地覆盖率盘点与测试基线

- [x] 1.1 (integration) 用只读查询盘点现有 `RaceEvent`、参赛/赛果与 `HorseP0Source`：按等级统计唯一日本训练候选、已有 JRA/NAR horse ID/URL、只有赛事上下文、只有 Netkeiba、训练范围未确认和海外赛事缺证数量；不触网、不写业务数据。
- [x] 1.2 (application) 为一期资格范围、多赛事去重、最高等级、第二层优先排序、旧 blocker 排除、1–100 上限、批量预取且无 N+1、冻结赛事上下文字段完整性、`provisional_japan/confirmed_japan/foreign_visitor/unresolved` 训练范围证据门禁和快照漂移编写测试并取得有效 RED。
- [x] 1.3 (integration) 为 JRA/NAR 直接锚点、索引到详情最多一跳、马号+精确马名唯一参赛行、唯一同 provider 马匹链接、逐跳 SHA、禁止站内搜索、同 host 重定向与 3 URL/6 次传输子预算，以及赛事上下文唯一/零/多结果、Netkeiba 四字段一致、三源一致/冲突、日期精度、国别后缀、文字体系 alias、字段不全和结构变化编写合成 fixture 测试并取得有效 RED。
- [x] 1.4 (integration) 为网络双重门禁、分 host 限速、单匹总计 6 URL/18 次传输预算、缓存、checkpoint/resume、429/拒绝即停、parser/config fingerprint 和禁止保存公开页面副本编写测试并取得有效 RED。
- [x] 1.5 (application) 为 artifact、真实 prepare 冻结字段、内嵌候选与 JSONL sidecar 绑定、精确 SHA 批准、partial/blocker 拒绝、字段/人工锁/资格漂移、整批回滚、数据库唯一 receipt、并发同 SHA、无 receipt 相同值阻断、公开状态不变和重复提交零写编写测试并取得有效 RED。

## 2. 重赏候选池与官方身份 provider

- [x] 2.1 (integration) 实现从 `RaceEvent`、`RaceEventRunner`、`RaceEventResult` 与 P0 来源反向生成资格池，保存全部 qualification、最高等级、重赏次数、最近日期、结构化训练范围证据和官方锚点；一匹一候选。只有 JRA/NAR 所属字段或经审核等价证据可确认日本训练，海外赛事不得用当前所属回推历史。
- [x] 2.2 (integration) 实现稳定优先级与有界批次选择，批量预取来源并冻结 profile、Netkeiba key、qualification、官方锚点和配置指纹；禁止逐匹查询。
- [x] 2.3 (integration) 复用 Netkeiba 解析，只提取登记马名、父名、母名和完整出生日期，保留既有双重网络门禁、持久预算、缓存和 checkpoint。
- [x] 2.4 (integration) 实现独立 `JraHorseIdentityProvider`：优先消费赛事中的 JRA horse URL/code，保存完整 URL、`CNAME` 原始值、赛事上下文和最小身份字段；结构未知或访问受限立即阻断。
- [x] 2.5 (integration) 实现独立 `NarHorseIdentityProvider`：优先消费赛事中的 `k_lineageLoginCode` 与完整 URL，保存赛事上下文和最小身份字段；不得复用或耦合 JRA 页面规则。
- [x] 2.6 (integration) 实现没有直接官方锚点时的确定性赛事上下文解析：allowlist URL，赛事索引最多跟随一个唯一详情链接，参赛表须以马号+精确马名唯一命中且只含一个同 provider 马匹链接；保存逐跳 SHA，零/多结果不得退化为站内马名搜索。
- [x] 2.7 (integration) 实现 provider-neutral 匹配、保守规范化、日期精度、证据等级 A/A+/C、稳定 blocker 和三源冲突 fail-closed；JAIRS 代码路径完全移除。
- [x] 2.8 (integration) 定义 JRA-VAN Windows 离线输入/输出 schema 与 manifest 校验器，覆盖 UM record、血统登记编号、数据规格版本、snapshot、逐记录和清单 SHA；本期不实现常态采集服务。
- [x] 2.9 (integration) 生成 qualification/candidate/blocker JSONL、source evidence manifest、summary、请求账本、state/checkpoint 和确定性 artifact SHA。
- [x] 2.10 (application) 实现管理命令 select/prepare 阶段、1–100 上限、`--allow-network` 双重门禁和逐 provider 请求预算。
- [x] 2.11 (application) 生成逐马审核 xlsx，展示最高等级、全部资格赛事、官方锚点、双/三来源原始值与规范值、证据等级、blocker 和审核列。

## 3. 审核与身份底稿提交

- [x] 3.1 (application) 完成 commit receipt 模型及迁移，以唯一 `approved_sha256` 保存获批集合、before/after、资格/证据摘要和 OperationLog 身份；验证正向/反向迁移。
- [x] 3.2 (integration) 实现审核 manifest builder，绑定输入、qualification、候选、blocker、工作簿、source evidence 和配置指纹 SHA，不包含写入批准语义。
- [x] 3.3 (application) 实现人工 approve，只允许 `candidate_pass`，要求 reviewer，拒绝 partial/blocker 并记录不可变审核事件。
- [x] 3.4 (integration) 实现原子 commit：稳定锁定获批 profile，复验 Netkeiba key、资格、官方锚点、身份字段和人工锁，只填空 `sire_text`、`dam_text`、`birth_date` 并合并来源引用；任一漂移整批回滚。
- [x] 3.5 (integration) 在首次成功事务内创建唯一 receipt 与 OperationLog；报告从 receipt 确定性导出，不改变公开状态、完整度、履历或 P0 来源。
- [x] 3.6 (application) 实现 commit/verify 命令，要求精确批准 SHA、独立批准人和显式确认；相同 SHA 只在 receipt 全量复验后返回零写 replay。

## 4. 验证与方案审查

- [x] 4.1 (integration) 运行新增测试并完成 GREEN/REFACTOR，覆盖 G1/G2/G3 资格、JRA/NAR 成功与 blocker、恢复、漂移、并发和幂等路径。
- [x] 4.2 (application) 运行 P0 批次、Netkeiba、既有补源、身份回填、赛事等级和发布门禁相关回归；确认旧 JBIS/JAIRS 路径不再被新命令引用。
- [x] 4.3 (operations) 运行 `manage.py check`、迁移漂移检查、durable artifact 结构检查、Compose config 和 `git diff --check`。
- [ ] 4.4 (operations) 完成独立只读代码审查，修复所有 P0/P1/P2 finding 后重新验证。
- [x] 4.5 (operations) 更新 `docs/current_state.md`、`docs/decisions.md`、`docs/deploy_runbook.md`、`docs/project_overview.md` 和 `docs/project_status.md`。

## 5. 生产 PoC 与滚动批次

- [ ] 5.2 (operations) 从最新生产只读快照的第二层候选生成 20 匹 PoC 清单，冻结唯一 Netkeiba ID、不完整底稿、资格赛事、官方赛事 URL/日期/场地/马号/精确马名，验证样本构成和旧 blocker 零交集；不足时报告缺口并停止。
- [ ] 5.3 (operations) 获得当次触网授权后，在一次性容器中低频执行 PoC；结束立即关网，审核 JRA/NAR/Netkeiba 解析、访问边界、缓存、请求账本和 artifact。
- [ ] 5.4 (operations) PoC 通过并另获授权后，按稳定优先级执行首个最多 100 匹 prepare；立即关网，按最高等级/provider 交付 xlsx、候选 SHA 和 blocker 分布。
- [ ] 5.5 (operations) 获得精确审核 SHA 的正式写入授权后，创建恢复点、暂停竞争任务、提交身份底稿并执行幂等/公开状态复验。
- [ ] 5.6 (operations) 重新生成现有 P0 完整资料批次，确认 expected 四字段齐全，再按原 select → approve → prepare → review → commit 门禁继续入库。
