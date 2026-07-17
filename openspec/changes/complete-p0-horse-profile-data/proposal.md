## Why

马匹详情页 MVP 已上线并用 `春秋分`、`北十字星` 验证了前台、关注、新闻 tag 和移动端链路，但现有 P0 马定义仍绑定“正式术语库中 active 且有中文译名的 horse `TermEntry`”。这会漏掉五大地区重点赛事参赛马，尤其是暂时没有合适中文译名、但已经具备资料补全和前台展示价值的海外马。

本专项需要把 P0 马从“已有中文译名的马名术语”扩展为“已有中文译名的正式马名术语 + 五大地区重点赛事参赛马”，并把资料补全升级为多地区、可审核、可回滚、可持续同步的生产流水线。首批验收不再是日本单区样本，而是从新版 P0 范围中完成日本、中国香港、英国、法国、美国各 10 匹马的完整资料补全。

## What Changes

- 扩展 P0 马定义：保留当前 active 且有中文译名的 horse `TermEntry` 范围，并新增五大地区所有 `G1/G2/G3/J-G1/J-G2/J-G3/JpnⅠ/JpnⅡ/JpnⅢ` 重点赛事参赛马；覆盖历史与未来全部已知赛事。
- 支持没有中文译名的 P0 马：术语体系允许 active horse term 暂无 `target_zh`，翻译时识别为马名并保留原文，不因缺中文译名阻塞资料补全、ready 或人工发布。
- 新增结构化 P0 来源记录，区分 `term_active_with_zh` 与 `major_race_participant`，并保存赛事、等级、地区、来源 URL 和审核状态。
- 建立持续同步机制：重点赛事、出赛表或赛果导入后，系统可刷新 P0 范围、创建缺失 `HorseProfile`、记录 P0 来源并触发资料补全队列。
- 建立多地区补全队列和来源 adapter，首批必须从新版 P0 范围中为五大地区各完成 10 匹完整资料样本；数据源不足时不得降级通过，可换同地区样本、修 adapter 或人工补录。
- 定义“完整马信息”硬门槛：身份与来源证据、基础事实字段、二代血统、完整赛事履历、按既有规则计算的主胜鞍、来源 URL、可审核 artifact 和人工批准记录；`intro` 不作为硬门槛。
- 将“赛事产品覆盖”与“马匹完整生涯”拆成两个完整度维度：P0 马必须按马匹来源采集从新马/未胜利/普通条件赛到分级赛的全部实际出赛；没有正式 `RaceEvent` 的普通比赛仍保存未关联 `HorseRaceRecord`，以后确认赛事身份再安全关联。
- 将生涯履历完整度从二代血统/资料完整度中独立出来，记录来源总出赛数、已采集实际出赛数、缺口数、已关联/未关联赛事数、海外出赛数和最后核验时间；退赛、取消出走不得计入实际出赛数。
- 马匹详情页以分页方式浏览全部生涯履历，不再固定截取最近 20 条；未关联普通比赛显示本地快照但不生成无效赛事链接。
- 为每批输出数据库记录和可审阅文件 artifact，包括 JSONL 原始候选、CSV 审核表、summary、失败/冲突清单和 source evidence manifest。
- 支持按模块人工审核基础资料、血统、赛事履历和主胜鞍；所有必需模块 approved 且写入成功后，马匹才能计入完整资料样本。
- 保留人工首次发布：首批每地区至少人工发布 1-2 匹做公开验收；未来自动化拆分为“已发布马自动增量更新”和“未发布马自动首次公开灰度”两个路径。
- 不改变公开页面实时请求策略：普通用户访问 `/horses/`、`/horses/<id>/`、新闻详情和关注流时仍只读本地数据库。

## Capabilities

### New Capabilities

- 无

### Modified Capabilities

- `horse-profile-data-completion`: 从“基于本地缓存的 P0 草稿补全”扩展为新版 P0 范围同步、多地区完整资料补全队列、受控来源候选生成、人工审核应用和首批五地区验收闭环。
- `horse-profile-pages`: 扩展后台审核工作台的数据质量筛选、ready/发布前提示、无中文译名展示和完整资料状态，使 P0 马可以按来源、批次、完整性、候选状态和发布状态分批运营。
- `termbase-and-race-priority`: 支持暂无中文译名的 active horse term，并让翻译、术语保留校验和新闻实体识别正确区分“可中文替换”和“只保留原文”的马名术语。
- `race-event-pages`: 重点赛事参赛马成为 P0 来源，赛事、出赛表和赛果导入必须能为 P0 范围同步提供可追溯证据。

## Impact

- 代码：`server/stable/models.py`、`server/stable/services/horse_profiles.py`、`server/stable/services/horse_profile_completion.py`、术语解析/翻译/校验服务、赛事数据服务、管理命令、后台视图和模板、测试。
- 数据：新增或扩展 P0 来源、补全 batch/run、完整资料状态、无中文译名术语状态；继续复用 `HorseProfile`、`HorseRaceRecord`、`HorseProfileDataCandidate`、`RaceEvent`、`RaceEventResult`、`ExternalHorse` / `ExternalHorseAlias`。
- 数据：`HorseRaceRecord` 增加实际出赛语义、日期精度、普通比赛快照、跨来源规范键和多来源证据；`HorseProfile` 增加独立的生涯完整度计数快照。
- 运维：生产执行必须先 dry-run、备份、审核 artifact，再 commit；真实外部请求必须限速、可暂停、可续跑，并确认外部导入长任务和 import lock 不冲突。
- 文档：更新 `docs/current_state.md`、`docs/project_status.md`，若涉及生产批次、部署或运行口径则更新 `docs/deploy_runbook.md`。
