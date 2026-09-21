# 分解与实施顺序

用户已批准实现，当前证据以 implementation.md / validation.json 为准。下列复合任务只有全部要求已满足才勾选；未勾选可包含已完成实现，不表示代码完全未动。真实来源 proof、Linux全量对照和生产自然验收不可用合成fixture代替。

## 0. 预声明假设

以 test_cases.md H1～H6 为 PASS/BLOCKER 阈值，不因运行成功而修改指标；来源不可达保留 coverage_gap。固定基线与fixture SHA，先保存真实 RED，再GREEN。

## 1. 通用登记与身份

- [ ] (integration) 建立 T03–T10/T17/T21 失败测试，覆盖跨语种、并发、旧摘要稳定。
- [x] (application) 加 `RaceEventIdentityKey`、`RaceDataSyncSourceBinding` 和 Enrollment v2字段；仅 additive migration，约束和默认兼容验证。
- [ ] (integration) 实现统一观测/adapter协议、A0旧日历/已核验候选seed receipt（缺ID/key且series未审的正反fixture）、证据化venue/name解析及原子identity绑定；复用已有别名/series/reference强匹配，不导入旧未合并分支。
- [x] (integration) 实现v2 policy、route-local digest、冻结legacy resolver；无关新增route不得改变旧准入。
- [x] (application) 实现登记/attach/CAS、分能力粘滞选源、连续故障/circuit后的有期限备用授权及receipt；共享admission覆盖状态、资料写入和公开读。
- [x] (integration) 修改selector/task/provider分派为binding驱动，一个event单claim、单claim单source；所有末端writer禁用隐式TRA/source FK假设。

## 2. 来源适配（每项测试在实现之前）

- [x] (integration) JRA：T01/T11–T16真实fixture RED；提取既有parser，赛前官方ID→登记→真实结果链接→完整结果、显式finality GREEN。
- [ ] (integration) NAR/HKJC：先身份/跨语种/非完赛fixture，再官方发现、卡与结果adapter；NAR/JRA路由冲突必须拒绝。
- [ ] (integration) UK/Ireland：先两个独立地区proof/fixtures，再Sporting Life独立发现与能力路由；ATR作为Ireland来源备选，RP403/406保留缺口。
- [ ] (integration) France：先ZEturf gallop和trot排除fixture，再独立发现/登记/卡/结果，France Galop保持独立proof状态。
- [ ] (integration) US：先HRN结果only及SL名单跨源fixture，再独立身份/结果登记与roster bootstrap；Equibase/NYRA不绕过访问限制。
- [ ] (integration) 按sources.md记录每桶非TRA可用能力/未通过项、第二来源去重顺序；不能只交付日本后标全部完成。

## 3. 补入、状态、告警和公开

- [ ] (application) T13/T14/T23/T26–T28先RED；分离发现时间窗与赛前轮询窗，加入过去7天未登记目标和无分钟赛时结果轮询，实时/late admission按H4分层计时。
- [ ] (integration) T15/T16/T20/T28先RED；完整result-only bootstrap、跨语种runner slot与更正/确认链。
- [ ] (application) T24/T25先RED；JRA/参考候选赛后只读保留，正式接管、缓存和赔率新鲜度处理。
- [ ] (application) 覆盖盘点从公开event生成，持久incident去重、解除条件、后台缺口可见；不发外部消息作为测试副作用。
- [ ] (integration) T29/T30先RED；公平分桶、能力窗口、预算和精确终态统计。

## 4. 兼容、发布工具与验证

- [ ] (operations) T21/T22/T31先RED；编写固定event manifest的legacy转换命令、dry-run及独立verify；空迁移/0078前向发布合同检查。
- [x] (application) 在 `.env.example` / `settings.py` 加三开关及v2 policy schema接入，全部默认关闭；维护README/运行文档相关入口。
- [x] (integration) 聚焦SQLite/PG测试GREEN，现有fixture provenance与数据契约review，候选/基线Linux CI无新增失败（ec5f7791；逐地区实网proof另列）。
- [ ] (operations) 冻结来源/地区/event范围、预算、schema迁移和恢复包，提交独立实现review；给用户具体G2选择后才合并/发布。
- [ ] (operations) 经批准后关闭态部署、只读预演、分地区灰度、103/104精确修复、105自然周期（若已过期则改新鲜样本并记录）；T32按真实来源开放观察，不用手动任务冒充自然验收。

## 文件责任与复用边界

业务：`models.py`、`migrations/`、`tasks.py`、`settings.py`、`race_data_sync_*`、`race_pre_race*`、现有结果/页面上下文服务和模板；集成：新两个service及来源纯parser/fixture；运维：固定scope命令、发布/verify和docs。源码修改时再列精确diff，禁止顺手重构新闻/马匹流程；任何新增模块需证明既有host模块不能直接承载。

## 当前未完成项的明确范围

- 日历只有裸URL且没有旧候选/导入证据的A0自动收据不实现猜测；需要补足受审输入。
- 七桶通用去重和离线parser测试已有；各桶完整实网proof、Ireland真实fixture、HKJC赛前卡以及US完整结果合同仍未齐备。
- 固定未发布v1转换工具已通过独立review和PG测试；已发布v1历史不自动转换。
- 0079迁移本地通过，ec5f7791的Linux固定SHA全量无新增失败；0079受保护发布包及T32自然周期仍未完成。
