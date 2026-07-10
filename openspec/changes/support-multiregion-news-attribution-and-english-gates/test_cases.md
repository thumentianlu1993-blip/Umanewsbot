# support-multiregion-news-attribution-and-english-gates 测试用例

本文档只依据本 change 的 `proposal.md`、`design.md`、`tasks.md` 和 delta specs 编写，不依据未来实现倒推测试点。目标是把“多地区新闻归属 + 英文门禁 + 发布窗口 + QQ 推送 + 后台运营入口”拆成可执行、可复查的验收用例。

测试类型说明：

- `A`：自动化测试或本地命令可验证。
- `S`：management command smoke test 可验证。
- `M`：前台、后台或人工操作验收。
- `O`：生产 dry-run、只读审计或上线前后运维验收。
- `D`：文档、OpenSpec 或非目标边界验收。

## 0. 推荐测试落点

实现阶段类名可按现有 `server/stable/tests.py` 组织调整，但行为覆盖必须保留。

- `stable.tests.NewsArticleRelatedRegionModelTests`：关联地区模型、约束、索引和兼容性。
- `stable.tests.NewsAttributionServiceTests`：地区归属服务、归属原因、人工锁定和地区集合 helper。
- `stable.tests.MultiregionIngestionAttributionTests`：抓取入库、来源提升、自动化重评和补跑入口接入归属服务。
- `stable.tests.EnglishGateMultiregionTests`：英文门禁、地区集合、可接受译名差异和内容类别。
- `stable.tests.MultiregionPublishWindowTests`：发布窗口候选、配额、去重和 0 篇原因。
- `stable.tests.PublicHomeMultiregionTests`：公开首页地区 tab、综合流去重、详情标签。
- `stable.tests.QQMultiregionPushTests`：QQ 群地区匹配、同群去重、类别资格和窗口审计。
- `stable.tests.MultiregionAttributionAdminTests`：后台展示和人工调整最终地区。
- `stable.tests.ReprocessMultiregionGateCommandTests`：重处理命令 dry-run、commit 和 artifact。

## 1. 标准测试 fixture

地区与来源 fixture：

- `source_uk_sporting_life`：`NewsSource(racing_region=united_kingdom, source_language=en)`。
- `source_france_english`：`NewsSource(racing_region=france, source_language=en)`。
- `source_hkjc`：`NewsSource(racing_region=hong_kong, source_language=en 或 zh-hant)`。
- `source_tdn_global`：可代表英文国际来源，默认地区可为 `united_states` 或具体 source config 地区。

术语与实体 fixture：

- `term_belmont_stakes_us`：active `race / en / Belmont Stakes -> 贝尔蒙特锦标`，`racing_region=united_states`，高优先级。
- `term_princess_of_wales_uk`：active `race / en / Princess Of Wales's Stakes -> 威尔士公主锦标`，`racing_region=united_kingdom`，高优先级，含英文 alias。
- `term_arc_france`：active `race / en / Prix de l'Arc de Triomphe -> 凯旋门大赛`，`racing_region=france`，高优先级。
- `term_hk_horse`：active `horse / en / Romantic Warrior -> 浪漫勇士`，`racing_region=hong_kong`。
- `term_fr_horse`：active `horse / en / Calandagan -> 卡兰达甘`，`racing_region=france`。
- `term_ambiguous_class`：active 或历史存在的英文高歧义词 `class`，用于确认普通词降级。

文章 fixture：

- `article_uk_france_race`：英国来源英文文章，正文明确报道法国境内赛事。
- `article_fr_horse_uk_race`：英国来源英文文章，核心对象是法国马，比赛发生地为英国。
- `article_hk_horse_overseas`：英文或繁中文章，报道香港马海外远征。
- `article_ireland_from_uk_source`：英国来源文章，主要报道爱尔兰赛事或爱尔兰赛马实体。
- `article_generic_uk_tips`：英国来源普通投注倾向 tips，无明确赛事地和核心实体。
- `article_result_brief`：赛果简报，已翻译且无 blocker。
- `article_major_preview`：重大赛事赛前展望，关联 P0/P1 或等价重大赛事。

## 2. 覆盖关系

| Spec Requirement | 主要测试 ID |
| --- | --- |
| 文章支持主地区和相关地区 | TC-MODEL-001 至 TC-MODEL-008 |
| 自动识别新闻地区归属 | TC-ATTR-001 至 TC-ATTR-011 |
| 地区归属可审计 | TC-ATTR-012, TC-REPROCESS-001, TC-ADMIN-001 |
| 后台人工调整最终地区 | TC-ADMIN-002 至 TC-ADMIN-005 |
| 单地区兼容和查询回退 | TC-MODEL-006, TC-QUERY-001 至 TC-QUERY-005 |
| 英文门禁结合内容类别 | TC-GATE-001 至 TC-GATE-010 |
| 地区集合参与门禁和策略 | TC-GATE-011 至 TC-GATE-014 |
| 重处理重算地区与英文门禁 | TC-REPROCESS-001 至 TC-REPROCESS-009 |
| 发布窗口主/相关地区与配额 | TC-PUBLISH-001 至 TC-PUBLISH-010 |
| 公开首页地区 tab | TC-PUBLIC-001 至 TC-PUBLIC-008 |
| QQ 主/相关地区匹配和幂等 | TC-QQ-001 至 TC-QQ-012 |
| 法国英文可审核边界 | TC-FR-001 至 TC-FR-004 |
| 香港宽口径内容 | TC-HK-001 至 TC-HK-005 |

## 3. 数据模型与查询 helper

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-MODEL-001 | 创建一篇日本旧文章，无关联地区 | 保存并读取文章 | `racing_region=japan` 保持主地区；关联地区为空；旧查询不报错 | A |
| TC-MODEL-002 | 创建主地区英国文章 | 添加相关地区法国 | 保存成功；相关地区表有一条 `france`；不复制 `NewsArticle` | A |
| TC-MODEL-003 | 主地区为英国 | 尝试把英国也保存为相关地区 | 拒绝保存或清理掉主地区；相关地区不包含主地区 | A |
| TC-MODEL-004 | 主地区为英国 | 重复添加法国相关地区两次 | 只保留一条；`article + region` 唯一约束生效 | A |
| TC-MODEL-005 | 支持地区清单不包含 `ireland` 公开 tab | 尝试保存非法相关地区值 | 拒绝保存或忽略非法值，并返回表单错误或可排查错误 | A |
| TC-MODEL-006 | 旧文章没有相关地区行 | 调用文章地区集合 helper | 返回只包含主地区的集合 | A |
| TC-MODEL-007 | 文章主地区英国、相关地区法国 | 调用文章地区集合 helper | 返回 `{united_kingdom, france}`，不重复、不含非法值 | A |
| TC-MODEL-008 | 关联地区表已有数据 | 检查 migration / model meta | 存在面向 `region + article` 的查询索引和面向 `article + region` 的唯一约束 | A |
| TC-QUERY-001 | 文章主地区英国、相关地区法国 | 使用地区可见性 helper 查询法国 | 能查到该文章 | A |
| TC-QUERY-002 | 同 TC-QUERY-001 | 使用地区可见性 helper 查询香港 | 查不到该文章 | A |
| TC-QUERY-003 | 同 TC-QUERY-001，配置关闭相关地区参与查询 | 查询法国 | 查不到该文章；查询英国仍能查到 | A |
| TC-QUERY-004 | 配置关闭相关地区参与查询 | 查看关联地区表 | 已保存的相关地区数据不被删除 | A |
| TC-QUERY-005 | 存在多篇同一文章因 join 产生重复的风险 | 查询综合流或地区 helper 并分页 | 同一文章只出现一次，排序稳定 | A |

## 4. 多地区归属服务

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-ATTR-001 | 英国来源文章明确报道法国境内赛事 | 调用自动归属服务 | 主地区为法国；英国来源地区只进入证据或相关地区规则，不得仅按来源定英国 | A |
| TC-ATTR-002 | 文章没有明确赛事地，核心对象是香港马 | 调用自动归属服务 | 主地区为中国香港 | A |
| TC-ATTR-003 | 英国来源文章无赛事地、无核心实体 | 调用自动归属服务 | 回退主地区为英国 | A |
| TC-ATTR-004 | 法国马在英国比赛 | 调用自动归属服务 | 文章地区包含法国和英国；按赛事地或规则选择一个主地区，另一个为相关地区 | A |
| TC-ATTR-005 | 香港马海外远征美国 | 调用自动归属服务 | 文章地区包含中国香港和美国 | A |
| TC-ATTR-006 | 英国来源报道爱尔兰赛事，系统无爱尔兰公开 tab | 调用自动归属服务 | 暂归英国，并在归属证据或标签中保留 `ireland` | A |
| TC-ATTR-007 | 文章同时命中赛事地、马、骑手多个地区 | 调用自动归属服务 | 主地区优先按赛事地；其它命中地区进入相关地区或证据 | A |
| TC-ATTR-008 | 文章已有人工最终地区锁定 | 自动化重评或重处理调用归属服务 | 保留人工最终主地区和相关地区，不被自动结果覆盖 | A |
| TC-ATTR-009 | 运营显式要求重新自动识别 | 调用带 override 的归属服务或管理动作 | 人工锁定可被重新计算结果替换，并输出原因 | A/M |
| TC-ATTR-010 | 来源、正文和术语信号互相冲突 | 调用归属服务 | 输出完整归属解释，包含触发规则、命中实体、来源 fallback 和置信说明 | A |
| TC-ATTR-011 | 无法识别任何实体 | 调用归属服务 | 稳定 fallback 到来源地区，不猜测其它地区 | A |
| TC-ATTR-012 | dry-run 重算近期候选 | 查看输出 artifact | 每篇文章输出调整前后主地区、相关地区、内容类别和归属原因；数据库无变化 | S/O |

## 5. 抓取、自动化和重处理入口

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-INGEST-001 | 新英文文章从英国来源入库 | 执行 ingestion draft 创建或 upsert | 调用归属服务写入主地区、相关地区、内容类别和归属摘要 | A |
| TC-INGEST-002 | 同一文章先普通来源入库，后榜单来源提升 | 执行 source elevation | 保留或重算归属结果；榜单提升不清空人工地区 | A |
| TC-INGEST-003 | 文章翻译完成后进入自动评分 | 执行自动化处理 | 门禁和策略使用当前主地区 + 相关地区集合 | A |
| TC-INGEST-004 | 人工补跑或窗口重跑 | 调用对应入口 | 与新抓取入口使用同一归属服务，不出现入口间结果不一致 | A |
| TC-REPROCESS-001 | 近期候选包含主地区错误和英文 blocker | 执行重处理 dry-run | 输出主地区变化、相关地区变化、内容类别、普通词降级、可信专名 blocker、预计可恢复候选 | S |
| TC-REPROCESS-002 | dry-run 完成 | 检查数据库 | 文章地区、门禁、状态、发布时间均无变化 | A/S |
| TC-REPROCESS-003 | 文章重处理后完整门禁通过 | 执行 commit | 更新归属、门禁结果和候选唤醒时间或等价字段；不直接设置为公开发布 | A/S |
| TC-REPROCESS-004 | 文章仍有可信核心专名缺失 | 执行 commit | 保持人工审核或 blocked 状态；不恢复为发布候选 | A/S |
| TC-REPROCESS-005 | 文章已人工拒绝、撤回或已发布 | 执行重处理 | 不复活这些终态文章，输出 skipped 原因 | A/S |
| TC-REPROCESS-006 | 文章有人工地区最终值 | 执行重处理 commit | 不覆盖人工地区，除非命令显式带重新自动识别参数 | A/S |
| TC-REPROCESS-007 | 命令未提供时间窗口或范围 | 执行命令 | 使用安全默认窗口，或拒绝无界全量写入；不得静默扫描全库并 commit | S |
| TC-REPROCESS-008 | 命令指定输出目录 | 执行 dry-run | 输出 machine-readable JSON、人工 review CSV、summary JSON | S |
| TC-REPROCESS-009 | commit 使用旧 dry-run artifact，但文章当前值已变化 | 执行 commit | 跳过 stale 行并记录原因，不覆盖当前人工或新状态 | A/S |
| TC-REPROCESS-010 | 前若干人工审核文章没有目标门禁，后续文章才有目标门禁 | 使用较小 `--limit` dry-run | `limit` 按有效候选计数；输出扫描数、候选数和是否仍有更多候选 | A/S |

## 6. 英文门禁与内容类别

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-GATE-001 | 英文 `result_brief` 文章无 blocker | 执行 `validate_rewrite()` 与自动发布资格判断 | 允许进入自动发布候选 | A |
| TC-GATE-002 | 英文 `preview` 文章关联 P0/P1 重大赛事且无 blocker | 执行自动发布资格判断 | 允许进入自动发布候选，并可作为 QQ 高价值候选 | A |
| TC-GATE-003 | 普通 `tips` 文章主要含 best bets / NAP / free bet | 执行自动发布和 QQ 资格判断 | 可被降权或转人工；不得仅因评分高进入 QQ 高价值推送 | A |
| TC-GATE-004 | 香港官方通知或 racecard update | 执行内容类别和策略判断 | 可进入站内发布门禁；QQ 资格按通知重要性或配置判断 | A |
| TC-GATE-005 | 英文文章命中 `Princess Of Wales's Stakes`，发布稿保留英文原文 | 执行发布校验 | 不产生 `core_term_missing` blocker | A |
| TC-GATE-006 | 英文文章命中 `Belmont Stakes`，发布稿缺中文、英文和 alias | 执行发布校验 | 产生 `core_term_missing` blocker | A |
| TC-GATE-007 | 英文正文出现普通词 `class` | 执行发布校验 | 按既有高歧义词或语义分类降级为 warning/info，不生成真实核心 blocker | A |
| TC-GATE-008 | 英文文章命中机构缩写或常见全大写词 | 执行发布校验 | 可解释为机构/缩写时不误判核心术语缺失；不可解释真实专名仍按 blocker | A |
| TC-GATE-009 | 内容类别无法确定 | 执行分类 | 保存为 `other` 或转人工，不默认进入 QQ 高价值 | A |
| TC-GATE-010 | 来源或栏目配置提供默认类别 | 执行分类 | 来源/栏目默认类别可覆盖纯文本规则，但最终结果写入文章并可审计 | A |
| TC-GATE-011 | 主地区英国、相关地区法国，命中法国赛事术语 | 执行发布校验 | 法国术语参与可信核心校验，不记录 `term_region_excluded` | A |
| TC-GATE-012 | 英国/法国文章命中香港马名普通词，香港不在地区集合 | 执行发布校验 | 继续按地区不匹配排除或降级为 info | A |
| TC-GATE-013 | 多地区文章自动发布 allowlist 只允许相关地区、不允许主地区 | 执行策略判断 | 按规格确定使用地区集合；结果可审计，不出现静默拒绝 | A |
| TC-GATE-014 | 配置关闭相关地区参与查询 | 执行门禁地区过滤 | 仅主地区参与地区过滤；相关地区数据保留但不影响本次判断 | A |

## 7. 发布窗口与公开页面

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-PUBLISH-001 | 主地区英国、相关地区法国的待发布文章 | 运行英国发布窗口 | 文章可作为英国主地区候选并发布 | A |
| TC-PUBLISH-002 | 同一文章已在英国窗口发布 | 运行法国发布窗口 | 不重复公开发布；法国窗口记录 `already_published_related_region` 或等价原因 | A |
| TC-PUBLISH-003 | 主地区英国、相关地区法国文章在英国窗口发布 | 检查配额账本 | 只消耗英国发布配额，不消耗法国发布配额 | A |
| TC-PUBLISH-004 | 法国窗口无主地区法国新文章，但有英国主地区/法国相关已发布文章 | 运行法国窗口 | 可计入法国已有可见内容，并记录原因 | A |
| TC-PUBLISH-005 | 某地区没有主地区新发布，只有相关地区可见内容 | 查看窗口 payload | 不得只记录 `no_ready_candidates`；必须说明相关地区可见或已发布原因 | A |
| TC-PUBLISH-006 | 多地区候选在同一总体候选集中通过 join 出现多次 | 运行发布候选选择 | 按文章去重，排序稳定 | A |
| TC-PUBLISH-007 | 候选硬门禁 blocker 存在 | 运行发布窗口 | 不因地区相关而绕过硬门禁 | A |
| TC-PUBLISH-008 | 保底发布逻辑遇到多地区文章 | 运行发布窗口 | 保底仍遵守主地区配额和硬门禁，关联地区只计可见 | A |
| TC-PUBLISH-009 | 配置关闭相关地区参与查询 | 运行发布窗口 | 只选择主地区等于窗口地区的文章 | A |
| TC-PUBLISH-010 | 查看地区生产审计 | 请求审计 JSON 或后台页面 | 展示主地区文章数、相关地区文章数、多地区示例、归属原因和 0 篇原因 | A/M |
| TC-PUBLIC-001 | 综合 tab 存在多地区已发布文章 | 打开公开首页综合 tab | 同一文章只展示一次，按 `published_to_web_at` 倒序和 `id` 倒序 | A/M |
| TC-PUBLIC-002 | 主地区英国、相关地区法国文章已发布 | 打开法国 tab | 该文章出现在法国 tab | A/M |
| TC-PUBLIC-003 | 同 TC-PUBLIC-002 | 打开香港 tab | 该文章不出现在香港 tab | A/M |
| TC-PUBLIC-004 | 存在待翻译、待审核、撤回或忽略的多地区文章 | 打开综合和地区 tab | 未公开文章均不展示 | A/M |
| TC-PUBLIC-005 | 多地区文章在首页卡片展示 | 查看标签 | 展示主地区标签，并展示相关地区标签或等价说明 | M |
| TC-PUBLIC-006 | 多地区文章详情页 | 打开 `/news/<id>/` | 展示主地区、相关地区、来源和原文语言；公开 URL 仍使用全局数字 ID | A/M |
| TC-PUBLIC-007 | 地区 tab 翻页 | 点击下一页/上一页 | 分页链接保留 `region` 参数 | A/M |
| TC-PUBLIC-008 | 配置关闭相关地区参与查询 | 打开法国 tab | 不展示仅相关地区命中的文章 | A/M |

## 8. QQ 自动推送

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-QQ-001 | 文章主地区英国、相关地区法国；群只允许法国 | 评估 QQ 资格 | 允许该群接收文章 | A |
| TC-QQ-002 | 同一文章；群只允许香港 | 评估 QQ 资格 | 不推送，并记录地区不匹配原因 | A |
| TC-QQ-003 | 群同时允许英国和法国 | 创建 QQ delivery | 同一文章对同一群只创建一条 `QQPushDelivery` | A |
| TC-QQ-004 | 同一文章对同一群已有 `sent` delivery | 再次运行 QQ 窗口或自动推送 | 不重复发送；记录 `already_sent` 或等价原因 | A |
| TC-QQ-005 | 多地区文章消息生成 | 调用消息渲染 | 消息包含主地区标签，并包含相关地区标签或说明 | A/M |
| TC-QQ-006 | `result_brief` 已公开无 blocker | 评估 QQ 高价值资格 | 满足分数或重点策略时可推送 | A |
| TC-QQ-007 | 重大赛事 `preview` 已公开无 blocker | 评估 QQ 高价值资格 | 可进入 QQ 高价值候选 | A |
| TC-QQ-008 | 普通 `tips` 或投注营销内容 | 评估 QQ 高价值资格 | 默认不推送，并保存 `content_category_not_qq_eligible` 或等价原因 | A |
| TC-QQ-009 | 普通官方通知或普通育马/拍卖内容 | 评估 QQ 高价值资格 | 默认不进 QQ，除非来源或类别配置显式允许 | A |
| TC-QQ-010 | QQ 窗口某地区没有任何可推文章 | 运行 QQ 窗口 | 记录明确 0 篇原因，如 `no_eligible_articles`、地区不匹配、类别不合格或已发送 | A |
| TC-QQ-011 | 配置关闭相关地区参与查询 | 文章主地区英国、相关地区法国，群只允许法国 | 不允许发送；保留相关地区数据但不参与匹配 | A |
| TC-QQ-012 | OneBot 离线 | 运行 QQ 窗口 | 继续遵守既有离线预检，不创建真实发送任务，并在窗口中记录原因 | A/O |
| TC-QQ-013 | 主地区美国、关联地区日本和法国 | 生成 QQ 消息 | 先显示 `地区：美国`，再显示 `关联地区：日本 / 法国`；不得按固定地区顺序颠倒主次 | A/M |

## 9. 后台与运营入口

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-ADMIN-001 | 候选文章有自动归属结果 | 打开候选详情或文章详情 | 展示主地区、相关地区、内容类别和归属解释 | M |
| TC-ADMIN-002 | 运营把主地区改为法国、相关地区改为英国 | 保存表单 | 保存成功，不要求填写调整原因 | A/M |
| TC-ADMIN-003 | 人工保存最终地区后 | 执行自动重评或重处理 | 不覆盖人工地区，除非显式重新自动识别 | A |
| TC-ADMIN-004 | 后台选择非法相关地区 | 提交表单 | 拒绝保存并显示错误；数据库不写非法值 | A/M |
| TC-ADMIN-005 | 后台移除所有相关地区 | 保存表单 | 主地区保留；相关地区清空；文章回到单地区兼容状态 | A/M |
| TC-ADMIN-006 | 文章当前已锁定人工归属 | 后台取消勾选归属锁定并保存 | `attribution_locked=false`；后续自动识别可重新计算，普通编辑不会强制重新锁定 | A/M |

代码审查返修补充回归边界：

- 国家或对象形容词与赛场同时出现时，明确赛场决定主地区，国家/对象地区只进入关联地区。
- 来源 URL 或来源备注包含地区/赛场字样时，不得覆盖正文无地区信号时的主来源 fallback。
- 同一 canonical 文章由补充来源和普通来源重复抓取时，归属必须使用最终保存在文章上的主来源配置。
- `MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false` 时，QQ 窗口和文章发布后的即时 QQ 任务都只按主地区匹配。
- `MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false` 时，公开列表卡片和文章详情只显示主地区；关联地区记录仍保留，重新开启开关后可恢复显示。
- 重处理 dry-run 对人工锁定文章不得模拟应用自动推断结果；输出必须区分推断地区和实际有效地区。
- `other` 默认不具备 QQ 资格，只有显式配置后才可放行。
- 新版编辑页提交关联地区字段哨兵但多选为空时必须清空全部关联地区；旧请求完全没有新字段时才保留原值。
- Django Admin 选择与主地区相同的关联地区时必须显示字段级中文错误，不得返回 500。
- `--limit` 按有效门禁候选计数，不能被无关人工审核文章提前占满。
- 列表、详情页和 QQ 必须先显示主地区，再单独标识关联地区。

## 10. 法国、香港与内容范围边界

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-FR-001 | 候选来源正文语言为法语 | 尝试进入新闻审核、自动发布或 QQ 主链路 | 被拒绝或不纳入主链路 | A/D |
| TC-FR-002 | 英文文章报道 France Galop、Longchamp、Deauville、Chantilly、Arqana 或法国育马/拍卖 | 执行归属服务 | 允许进入法国新闻池，并保留法国实体证据 | A |
| TC-FR-003 | 法国马、法国骑师或法国练马师在海外赛事中出现 | 执行归属服务 | 法国和比赛发生地区均进入文章地区归属 | A |
| TC-FR-004 | 法国英文来源文章无法识别法国实体 | 执行归属服务 | 按来源 fallback 到法国，并输出 fallback 原因 | A |
| TC-HK-001 | HKJC 官方兽医报告或装备更新 | 执行内容分类和归属 | 进入香港池，类别为 `official_notice` 或 `racecard_update` | A |
| TC-HK-002 | 香港马海外远征 | 执行归属服务 | 香港和比赛发生地区均进入文章地区归属 | A |
| TC-HK-003 | 从化训练、香港骑师/练马师动态 | 执行归属服务 | 进入香港池，并保存命中实体或机构证据 | A |
| TC-HK-004 | SCMP / IdolHorse / DRF 赛前预测 | 执行内容分类 | 分类为 `preview` 或 `tips`，并按类别决定 QQ 资格 | A |
| TC-HK-005 | 普通投注营销内容 | 执行内容分类和 QQ 判断 | 可进入新闻池但默认不进入 QQ 高价值推送 | A |

## 11. 运维与上线验收

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-OPS-001 | 本地实现完成 | 执行 `DB_ENGINE=sqlite python manage.py check` | Django check 通过 | A |
| TC-OPS-002 | 本地实现完成 | 执行目标测试类 | 多地区归属、英文门禁、发布窗口、QQ、后台和重处理测试通过 | A |
| TC-OPS-003 | 本地实现完成 | 执行 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable --noinput` | 完整 stable 测试通过 | A |
| TC-OPS-004 | 新迁移已生成 | 执行 `DB_ENGINE=sqlite python manage.py makemigrations --check --dry-run` | 无遗漏迁移 | A |
| TC-OPS-005 | Compose 文件存在 | 执行两个生产 compose config 命令 | `docker compose -f docker-compose.prod.yml config` 和 lowcost 版本均通过 | A/O |
| TC-OPS-006 | OpenSpec artifact 完成 | 执行 `openspec validate support-multiregion-news-attribution-and-english-gates --strict` | 严格校验通过 | D |
| TC-OPS-007 | 本地改动完成 | 执行 `git diff --check` | 无尾随空格、冲突标记等 diff 问题 | A |
| TC-OPS-008 | 准备生产 dry-run | 记录生产 commit、容器状态、`/healthz/`、备份路径和外部导入锁 | 前置状态写入部署记录或 runbook | O |
| TC-OPS-009 | 生产 dry-run 重处理完成 | 抽查香港、英国、法国、美国、日本近期候选 | 输出主地区、相关地区、内容类别、门禁原因和预计恢复数量；数据库无变化 | O |
| TC-OPS-010 | 小批 commit 重处理完成 | 查看地区 tab、发布窗口和 QQ 资格 | 新归属生效；无重复公开；QQ 不重复发送 | O/M |
| TC-OPS-011 | 配置回退开启 | 线上只读验收首页、发布窗口和 QQ 匹配 | 行为回到只看主地区；相关地区数据未被清除 | O |
| TC-OPS-012 | 上线完成 | 更新 `docs/current_state.md`、`docs/project_status.md`、`docs/decisions.md`、`docs/deploy_runbook.md` | 文档记录决策、命令、计数、回退方式和验收结果 | D/O |

## 12. 非目标边界

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-SCOPE-001 | 本 change 实施完成 | 检查适配器和来源清单 | 不新增英国、香港、法国新闻源适配器；来源扩容另起 change | D |
| TC-SCOPE-002 | 存在法语正文来源 | 执行抓取或审核入口 | 不把法语正文接入主审核、自动发布或 QQ 主链路 | A/D |
| TC-SCOPE-003 | 多地区文章出现 | 检查数据库 | 不复制文章正文，不创建重复公开文章 | A |
| TC-SCOPE-004 | 重处理 commit 后文章满足发布条件 | 查看文章状态 | 不在重处理命令内直接公开发布，仍交给发布窗口 | A/S |
| TC-SCOPE-005 | QQ 交付记录存在 | 检查唯一粒度 | 不改变“文章 x 群”的自动推送幂等粒度 | A |

## 13. Code review 回归

| ID | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- |
| TC-GATE-ALIAS-001 | 同一术语记录包含一个普通词 alias 和一个可信专名，只有普通词在忽略清单中 | 让文章仅命中可信专名，并令发布稿缺少其中文、英文及可接受 alias | 可信专名继续产生 `core_term_missing`；普通词 alias 不得连带豁免整条术语记录 | A |

## 14. 当前预期执行命令

实现完成后至少执行：

```bash
DB_ENGINE=sqlite python manage.py check
DB_ENGINE=sqlite python manage.py makemigrations --check --dry-run
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable --noinput
docker compose -f docker-compose.prod.yml config
docker compose -f docker-compose.prod.lowcost.yml config
openspec validate support-multiregion-news-attribution-and-english-gates --strict
openspec validate --all
git diff --check
```

若实现阶段新增更细粒度测试类，应先运行目标测试类，再运行完整 `stable` 测试。生产上线前必须再执行重处理 dry-run 和窗口/QQ 只读抽样，确认五地区主地区、相关地区、门禁原因和 QQ 资格符合预期。
