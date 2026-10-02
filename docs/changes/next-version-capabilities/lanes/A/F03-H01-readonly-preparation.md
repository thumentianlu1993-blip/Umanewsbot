# F03 / H01 只读准备（未派发实施、未完成）

本材料是 A-001/F01 的独立准备输入，不报告 F03/H01 完成，不新增网络采集或生产查询。
代码 base：907f8de699b31a6fcc80acc78e9ba070aadc4f28。

F03 按九地区×赛程/名单/退赛/结果/更正固定 45 格；每格记录 adapter、source key、provider class、
稳定身份、parser/endpoint、maturity/完整度、source-time 语义、route/terms/proof、权限有效期、
主备与共用底层来源、预算/健康、缓存回放、真实 proof 的时间和范围。未知明确写缺口，不写空格；
parser 存在不等于端点权限或当前生产启用。入口为 `race_data_sync_providers.py`、
`race_data_source_adapters.py`、`race_source_identity.py`、现有 registry/policy 与缓存证据。
先从这些既有输入盘点，不由旧账单推断套餐、覆盖或当前额度；账号套餐由协调者/F06 核验。

H01 以冻结 as_of、local_date 窗口与来源证据枚举参赛项，而不是从 HorseProfile 表开始漏掉未建档对象。
输入须覆盖 RaceEventRunner、RaceEventParticipant、RaceEventResult 及经准入来源可枚举的未建档参与者，
对 revision 来源按生效版本/撤销规则选取，不把同一赛前赛后名单算两次；报名/退赛不自动当实际出赛。
已核验 HorseExternalIdentity 与 provider 稳定 ID 可映射成唯一马匹；只有同名或未知身份时保留独立
source target 与冲突组，不删出原始分母。raw 参与项数、唯一已解析马、未解析目标、冲突组分别计数。

近期集合建议含 2023-10-03..2026-10-03 的实际出赛证据；source start_status 不明者保留待核池及数量。
历史名称集合按 2020 起 G1/Jpn1/香港本土 G1 全名单（含名单内非出赛者并标状态），不能只抓冠军。
跨集交集只去重处理队列，不丢各自目标归属；冻结 snapshot + sha，之后增量单独记录，不回写旧分母。
未来30天/当前赛季/近期新闻是优先队列补充，不把预测参赛计入已发生近期参赛数。

复用入口：`p0_horse_profiles.py:_identity_index/_participant_identity_keys`、
`horse_profile_completion.py:plan_profile_completion`、`horse_race_records.py:resolve_existing_race_record`。
这些函数是否足够表达全部目标要在 H01 接单时确认，不能假设旧 P0 选集就是本版完整分母。
缓存、ExternalHorse/staging、正式 HorseProfile、公开 validator 通过四个处理面各自对账；
收集 starts=0 的空履历与未知 starts=null，避免错误“完整生涯”判定。
