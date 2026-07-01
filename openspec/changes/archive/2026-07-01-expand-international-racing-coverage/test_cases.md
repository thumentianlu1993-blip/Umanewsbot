# expand-international-racing-coverage 测试用例

本文档只依据本 change 的 `proposal.md`、`design.md` 和 delta specs 编写，不依据本次实现代码倒推测试点。目标是把规格承诺拆成可执行、可复查的验收用例，覆盖主要功能和边界条件。

测试类型说明：

- `A`：自动化测试或本地命令可验证。
- `L`：真实外部网页 dry-run 或小样本探测可验证。
- `M`：需要前台、后台或人工操作验收。
- `D`：文档、OpenSpec 或非目标边界验收。

## 1. 地区、语言和来源基础语义

| ID | 来源 | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- | --- |
| TC-REG-001 | `international-racing-coverage` | 系统完成多地区迁移 | 检查既有 `netkeiba` 与 `JRA` 来源和文章 | 既有日本数据具备 `japan / ja` 语义 | A |
| TC-REG-002 | `international-racing-coverage` | 新增国际新闻源或数据库源 | 创建或同步任一新来源 | 来源必须声明地区、原文语言、来源类型 | A |
| TC-REG-003 | `international-racing-coverage` | 新来源产出文章或外部数据 | 执行入库流程 | 入库对象继承来源的地区、语言和类型语义 | A |
| TC-REG-004 | `international-racing-coverage` | 存在 `other` 或预留地区来源 | 打开公开首页地区 tab | 第一版前台不展示预留地区入口 | M |
| TC-REG-005 | `international-racing-coverage` | 文章地区为空或非法 | 触发自动 QQ 推送评估 | 文章不得自动推送，并记录 `region_missing` 或等价跳过原因 | A |
| TC-REG-006 | `international-racing-coverage` | 新闻正文原文语言不是 `ja / en / zh-hant` | 尝试进入新闻审核、翻译、自动发布或 QQ 推送链路 | 系统拒绝或不纳入主链路 | A |
| TC-REG-007 | `international-racing-coverage` | 工作人员在后台手动启用或停用内置来源 | 再次执行内置来源同步、打开工作台或触发抓取任务 | 来源地区、语言、URL 等定义可更新，但人工 `enabled` 状态不得被默认值覆盖 | A |

## 2. 一期国际新闻源

| ID | 来源 | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- | --- |
| TC-SRC-001 | `international-racing-coverage` | 日本扩展启用 | 抓取 `Sponichi` 小样本新闻 | 文章标记为 `japan / ja`，包含标题、正文、发布时间、原文 URL | A/L |
| TC-SRC-002 | `international-racing-coverage` | 香港扩展启用 | 抓取 `HKJC Racing News` 小样本新闻 | 文章标记为 `hong_kong`，语言按来源内容为 `en` 或 `zh-hant` | A/L |
| TC-SRC-003 | `international-racing-coverage` | 香港扩展启用 | 抓取 `SCMP Racing` 小样本新闻 | 文章标记为 `hong_kong`，语言按来源内容为 `en` 或 `zh-hant` | A/L |
| TC-SRC-004 | `international-racing-coverage` | 英国扩展启用 | 抓取 `Sporting Life Racing` 小样本新闻 | 文章标记为 `united_kingdom / en` | A/L |
| TC-SRC-005 | `international-racing-coverage` | 英国扩展启用 | 抓取 `Sky Sports Racing` 小样本新闻和 Top Stories 排序入口 | 文章标记为 `united_kingdom / en`，Top Stories 样本携带原站页面顺序 rank | A/L |
| TC-SRC-006 | `international-racing-coverage` | 英国官方补充源启用 | 抓取 `BHA` 小样本新闻 | 文章标记为 `united_kingdom / en` | A/L |
| TC-SRC-007 | `international-racing-coverage` | 法国新闻源配置完成 | 尝试把 `Jour de Galop` 或其他法语正文纳入新闻链路 | 不得进入新闻审核、翻译、自动发布或 QQ 推送主链路 | A/D |
| TC-SRC-008 | `international-racing-coverage` | 法国扩展启用 | 抓取 `France Galop English News` 小样本新闻 | 文章标记为 `france / en`，来源类型为官方或官方新闻补充 | A/L |
| TC-SRC-009 | `international-racing-coverage` | 法国英文媒体补充源启用 | 抓取 `TDN France keyword` 小样本新闻 | 文章标记为 `france / en`，不抓法语正文 | A/L |
| TC-SRC-010 | `international-racing-coverage` | 美国扩展启用 | 抓取 `TDN` 小样本新闻 | 文章标记为 `united_states / en` | A/L |
| TC-SRC-011 | `international-racing-coverage` | 美国扩展启用 | 抓取 `Horse Racing Nation` 小样本新闻和 Trending 排序入口 | 文章标记为 `united_states / en`，Trending 样本携带原站页面顺序 rank | A/L |
| TC-SRC-012 | `international-racing-coverage` | 任一国际新闻 URL 可解析 | 从完整 URL 生成 `source_article_id` | 来源去重键稳定、低碰撞，不只使用 URL 最后一段 slug | A |
| TC-SRC-013 | `international-racing-coverage` | 两个 URL 最后一段 slug 相同但完整 URL 不同 | 分别生成来源去重键 | 两个键不同，避免同源碰撞 | A |
| TC-SRC-014 | `international-racing-coverage` | 国际新闻详情页包含完整 HTML | 执行详情解析和入库 | 原始 HTML 只保存到 `original_content_html`，`translation_metadata` 与 `NewsSnapshot.snapshot_metadata` 不保存整页 HTML | A |
| TC-SRC-015 | `international-racing-coverage` | 列表页含导航、栏目、作者或广告链接 | 执行列表解析 | 不把非新闻链接作为候选文章 | A/L |
| TC-SRC-016 | `tasks.md 10.5` | 每个新增网站可访问或返回明确错误 | 每站 dry-run 尝试抓两篇真实新闻 | 成功源返回两篇样本；失败源记录 403、反爬或空样本风险 | L |
| TC-SRC-017 | `international-racing-coverage` | 新增新闻源存在公开稳定排序入口 | 以榜单模式抓取排序入口 | 系统创建独立榜单来源，文章携带原站排名 | A/L |
| TC-SRC-018 | `international-racing-coverage` | Sponichi `ニュースランキング` 混有ボート等非赛马新闻 | 以 `source_mode=access` 解析榜单 | 只保留赛马新闻，保留原站排名，不按过滤后列表重新编号 | A/L |
| TC-SRC-019 | `international-racing-coverage` | 某站排序入口返回 403、反机器人页、空骨架屏或无公开 API | 调研或 dry-run 排序入口 | 不启用为生产自动榜单源，并在文档/测试记录中记录风险 | D/L |
| TC-SRC-020 | `international-racing-coverage` | TDN 列表 API 提供发布时间但详情页缺少日期节点 | 执行 TDN 列表、详情解析和标准化 | 入库 draft 使用列表 API 的真实发布时间，不使用当前抓取时间覆盖 | A |
| TC-SRC-021 | `international-racing-coverage` | 同一国际新闻先被普通 list 抓到，随后被公开排序入口抓到 | 执行两次入库 | 主来源提升为排序/榜单来源，保留原站 rank，并返回可用于后续推送编排的提升信号 | A |
| TC-SRC-022 | `international-racing-coverage` | 同一国际新闻已由排序/榜单入口入库 | 后续普通 list 再次抓到同一来源键 | 普通 list 不得覆盖已有排序/榜单主来源，但仍记录普通 list 的 `NewsSnapshot` | A |

## 3. 公开首页和文章详情

| ID | 来源 | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- | --- |
| TC-PUB-001 | `public-home-info-feed` | 存在多地区已发布文章 | 打开公开首页 | 显示综合、日本、中国香港、英国、法国、美国 tab | M/A |
| TC-PUB-002 | `public-home-info-feed` | 多地区文章均已发布 | 打开综合 tab | 展示全部地区已发布文章，按 `published_to_web_at` 倒序、再按 `id` 倒序 | A |
| TC-PUB-003 | `public-home-info-feed` | 存在日本已发布文章和其他地区文章 | 打开日本 tab | 首页头条、普通流、辅助列表只使用日本文章 | A/M |
| TC-PUB-004 | `public-home-info-feed` | 存在香港已发布文章和其他地区文章 | 打开中国香港 tab | 只展示中国香港文章 | A/M |
| TC-PUB-005 | `public-home-info-feed` | 存在英国、法国、美国已发布文章 | 分别打开英、法、美 tab | 每个 tab 只展示对应地区文章 | A/M |
| TC-PUB-006 | `public-home-info-feed` | 某地区存在待翻译、待编辑、待审核、撤回、忽略、驳回文章 | 打开综合和对应地区 tab | 未公开文章均不展示 | A |
| TC-PUB-007 | `public-home-info-feed` | 任一国际新闻公开 | 查看首页卡片和详情页 | 页面展示可读地区标签、来源、原文语言 | M |
| TC-PUB-008 | `public-home-info-feed` | 任一地区文章公开 | 从首页打开文章详情 | 公开 URL 使用 `/news/<NewsArticle.id>/` 数字 ID，不暴露上游 ID 或标题 slug | A/M |
| TC-PUB-009 | `public-home-info-feed` | 多地区文章同时存在 | 打开综合 tab | 不做地区打散、个性化推荐或专题排序 | A |
| TC-PUB-010 | `public-home-info-feed` | 桌面和移动端视口 | 检查地区 tab 和新闻流 | tab 可扫描、可点击，不遮挡新闻内容 | M |

## 4. 正式术语概念和多语言别名

| ID | 来源 | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- | --- |
| TC-TERM-001 | `termbase-and-race-priority` | 既有术语存在 `source_ja / aliases_ja` | 执行多语言术语迁移 | 既有术语视为 `ja`，并生成或保留日文原文别名 | A |
| TC-TERM-002 | `termbase-and-race-priority` | 工作人员创建英文术语 | 创建 `source_language=en` 的马名、赛事、骑师或练马师术语 | 保存正式术语概念和英文原文别名，可被英文文章匹配 | A/M |
| TC-TERM-003 | `termbase-and-race-priority` | 工作人员创建繁中术语 | 创建 `source_language=zh-hant` 的香港马名或赛事术语 | 保存正式术语概念和繁中原文别名，发布稿输出简体中文 | A/M |
| TC-TERM-004 | `design.md` | 存在 `イクイノックス -> 春秋分` | 将英文候选 `Equinox` 合并到该正式术语 | 保留一个 `春秋分` 概念，新增 `en` 别名 `Equinox` | A/M |
| TC-TERM-005 | `design.md` | 同一术语概念拥有日文、英文、繁中别名 | 分别用不同语言文章匹配 | 各语言文章命中对应语言别名，并回到同一正式术语概念 | A |
| TC-TERM-006 | `termbase-and-race-priority` | 系统存在同文本不同语言术语 | 创建 `en` 的 `Title` 和 `ja` 的 `タイトル` | 按语言分别校验，不误判冲突 | A |
| TC-TERM-007 | `termbase-and-race-priority` | 导入文件包含 `Ascot -> 阿斯科特` 且语言为 `en` | 提交正式术语导入 | 创建英文正式术语，不覆盖同文本日文或繁中术语 | A |
| TC-TERM-008 | `termbase-and-race-priority` | 导入文件包含历史 `キタサンブラック -> 北部玄驹` | 预览并提交导入 | 提交后启用马名正式术语，可被翻译和自动评分命中 | A |
| TC-TERM-009 | `termbase-and-race-priority` | 新增模式导入遇到同一 `term_type + source_language + 原文术语` | 执行导入 | 标记错误或跳过，不覆盖既有正式术语 | A |
| TC-TERM-010 | `termbase-and-race-priority` | 更新或插入模式导入遇到同语言重复术语 | 执行导入 | 更新中文译词、原文别名、中文别名、启用状态、优先级、比赛等级和备注 | A |
| TC-TERM-011 | `termbase-and-race-priority` | 打开术语列表、编辑、导入、快速创建、候选池 | 检查页面文案 | 使用“原文”“原文别名”“原文语言”，不再显示日文限定标签 | M |
| TC-TERM-012 | `termbase-and-race-priority` | 从英文文章 `#5266` 快速创建术语 | 打开快速创建表单 | 默认原文语言为 `en`，记录来源文章上下文 | A/M |
| TC-TERM-013 | `termbase-and-race-priority` | 从繁中文章选中香港马名 | 快速创建术语 | 默认原文语言为 `zh-hant`，允许保存简体中文译词 | A/M |
| TC-TERM-014 | `termbase-and-race-priority` | 从日文文章快速创建术语 | 打开快速创建表单 | 默认原文语言为 `ja`，保留马名默认类型和旧行为兼容 | A/M |
| TC-TERM-015 | `termbase-and-race-priority` | 快速创建未填写简体中文译词 | 提交表单 | 拒绝创建，并显示中文译词不能为空 | A/M |
| TC-TERM-016 | `termbase-and-race-priority` | 已存在同语言同类型同原文术语 | 再次快速创建相同组合 | 拒绝创建重复术语 | A/M |
| TC-TERM-017 | `termbase-and-race-priority` | 快速创建空选区或过长选区 | 提交表单 | 拒绝创建，并提示需要选择短原文词条 | A/M |
| TC-TERM-018 | `termbase-and-race-priority` | 快速创建只提交最小字段 | 提交表单 | 创建 `is_active=true`、`priority=0`、`race_grade` 为空、别名为空的正式术语 | A |

## 5. 术语匹配、翻译、校验和自动评分

| ID | 来源 | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- | --- |
| TC-LANG-001 | `termbase-and-race-priority` | 日文文章包含启用日文马名术语 | 执行翻译 | `translation_metadata.terms` 包含命中，中文稿使用标准译名 | A |
| TC-LANG-002 | `termbase-and-race-priority` | 英文文章标题包含启用英文术语 | 执行翻译 | `terms` 包含英文术语命中，中文稿使用对应简体中文译词或可接受别名 | A |
| TC-LANG-003 | `termbase-and-race-priority` | 文章包含与文章语言匹配的启用马名术语 | 执行翻译 | `unknown_horse_names` 不包含该术语原文或别名 | A |
| TC-LANG-004 | `termbase-and-race-priority` | 日文文章包含外部马名索引但无正式中文术语 | 执行翻译 | 使用占位符保护并还原原文，不自动替换中文译名 | A |
| TC-LANG-005 | `termbase-and-race-priority` | 英文文章包含大写或专有名词 | 执行未知马名识别 | 不因日文片假名规则加入未知马名保护列表 | A |
| TC-LANG-006 | `termbase-and-race-priority` | 繁中文章包含普通词或马名候选 | 执行未知马名识别 | 不使用日文普通词过滤表决定繁中识别结果 | A |
| TC-LANG-007 | `termbase-and-race-priority` | 发布校验发现核心术语缺失 | 打开后台 blocker 详情 | 展示原文、原文语言、目标简体中文译词和命中位置 | A/M |
| TC-LANG-008 | `termbase-and-race-priority` | 文章计算重点马匹、赛事优先级或评分信号 | 对 `ja / en / zh-hant` 文章分别计算 | 只使用文章语言对应的启用术语别名，不跨语言误命中 | A |
| TC-LANG-009 | `termbase-and-race-priority` | 英文文章包含某正式术语英文别名，且该术语也有日文别名 | 生成自动标签 | 使用英文别名匹配并生成同一概念中文标签，不执行日文别名匹配 | A |
| TC-LANG-010 | `termbase-and-race-priority` | 候选术语跨语言合并到正式术语 | 接受或合并候选 | 保留候选自己的 `source_language`，不得把英文名混入日文别名数组 | A/M |

## 6. QQ 群级地区和范围推送

| ID | 来源 | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- | --- |
| TC-QQ-001 | `qqbot-auto-push` | `QQ_PUSH_ENABLED=false` | 触发自动推送任务 | 不为任何目标群执行自动发送 | A |
| TC-QQ-002 | `qqbot-auto-push` | 群允许中国香港且 `push_scope=all_public` | 公开一篇无 blocker 的香港文章 | 允许进入该群自动推送交付 | A |
| TC-QQ-003 | `qqbot-auto-push` | 群设置 `high_value_only` 和 `importance_strategy=ranked` | 评估公开文章 | 使用该群重点策略决定是否推送 | A |
| TC-QQ-004 | `qqbot-auto-push` | 全局 `QQ_PUSH_SCOPE=all_public`，群级为 `high_value_only` | 评估该群推送资格 | 按群级 `high_value_only` 判定 | A |
| TC-QQ-005 | `qqbot-auto-push` | 文章地区为空或非法 | 触发自动推送 | 不向任何群发送，并记录 `region_missing` 或等价原因 | A |
| TC-QQ-006 | `qqbot-auto-push` | 群缺少显式配置 | 查看后台和推送判定 | 使用迁移默认或全局回退值，后台展示最终生效配置 | A/M |
| TC-QQ-007 | `qqbot-auto-push` | 多个启用群均满足同一文章条件 | 触发自动推送 | 为每个符合条件的启用群分别创建交付记录并发送 | A |
| TC-QQ-008 | `qqbot-auto-push` | 某群 `is_active=false` | 触发自动推送 | 不为停用群创建新交付或发送消息 | A |
| TC-QQ-009 | `qqbot-auto-push` | 群 A 允许日本和香港，群 B 只允许英国和美国 | 发布一篇香港文章 | 只为群 A 创建或处理交付，不为群 B 创建 | A |
| TC-QQ-010 | `qqbot-auto-push` | 旧全局 QQ 推送配置存在 | 执行迁移 | 既有 `PushTarget` 获得等价旧行为默认值 | A |
| TC-QQ-011 | `qqbot-auto-push` | 某文章对某群已有 `sent` 交付 | 调整该群地区或范围配置后重新评估 | 不重复发送同一文章到同一群 | A |
| TC-QQ-012 | `qqbot-auto-push` | 同一群短时间内有多篇待发送文章 | 处理交付 | 继续按该群最近发送尝试时间限速，延后时不增加尝试次数 | A |
| TC-QQ-013 | `qqbot-auto-push` | 打开 Django Admin 群配置页 | 编辑群名称、群号、默认标记、启用状态、允许地区、范围和重点策略 | 后台可维护并保存配置 | M |
| TC-QQ-014 | `qqbot-auto-push` | 自动推送目标筛选 | 准备 `is_default=false` 但 `is_active=true` 的群 | 自动推送不使用 `is_default` 过滤，仍按群级配置判断 | A |
| TC-QQ-015 | `qqbot-auto-push` | 群级 `push_scope=high_value_only`、`importance_strategy=ranked` | 评估 Sponichi、Sky Sports Racing 或 Horse Racing Nation 的公开排序/榜单稿 | 国际榜单稿与 netkeiba 榜单稿一样被视为 ranked 重点新闻 | A |
| TC-QQ-016 | `qqbot-auto-push` | 一篇已公开国际普通 list 文章随后被同站排序/榜单入口抓到并提升主来源 | 执行对应国际排序/榜单来源抓取 | 系统在来源提升后触发 QQ 自动推送编排，并继续依靠“文章 x 群”交付记录去重 | A |

## 7. HKJC 外部数据导入

| ID | 来源 | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- | --- |
| TC-HKJC-001 | `international-racing-coverage` | 运维指定 HKJC 赛日 | 以 dry-run 导入赛日 | 抓取或解析可发现的比赛、出马、赛果摘要，不写库 | A/L |
| TC-HKJC-002 | `international-racing-coverage` | HKJC 返回比赛信息 | commit 导入样本 payload | 保存比赛日期、马场、场次、比赛名称、班次或等级、距离、场地、跑道、奖金、Going、天气或场地状态、开跑时间和原始 payload | A |
| TC-HKJC-003 | `international-racing-coverage` | HKJC 返回出马表 | commit 导入样本 payload | 保存马名、外部马匹标识、档位、骑师、练马师、负磅、装备、评分、马主或可用连接信息和原始 payload | A |
| TC-HKJC-004 | `international-racing-coverage` | HKJC 返回赛果 | commit 导入样本 payload | 保存名次、完成时间、距离差、赔率、沿途位置、分段时间、骑师、练马师、档位和原始 payload | A |
| TC-HKJC-005 | `international-racing-coverage` | HKJC 返回马匹资料 | commit 导入样本 payload | 保存英文名、中文名、外部马匹标识、父系、母系、出生日期或年龄、产地、性别、毛色、马主、练马师、累计赛绩和原始 payload | A |
| TC-HKJC-006 | `international-racing-coverage` | 出马表、赛果或马匹资料包含可信马名 | 导入 payload | 创建或更新本地外部马名索引，保留英文名、中文名和外部马匹标识关系 | A |
| TC-HKJC-007 | `international-racing-coverage` | commit payload 比赛数超过 `max_races` | 执行导入 | 拒绝本次导入，返回明确错误，不静默截断、不部分写入、不创建成功 run | A |
| TC-HKJC-008 | `international-racing-coverage` | commit payload 马匹数超过 `max_horses` | 执行导入 | 拒绝本次导入，返回明确错误，不静默截断、不部分写入、不创建成功 run | A |
| TC-HKJC-009 | `international-racing-coverage` | 同一 payload 重复提交 | 执行两次 commit | 幂等 upsert，不重复创建比赛、出马、赛果、马匹或别名 | A |
| TC-HKJC-010 | `international-racing-coverage` | 同一来源已有运行中的导入锁 | 再次启动 HKJC 导入 | 拒绝并发导入，保留单来源互斥 | A |
| TC-HKJC-011 | `international-racing-coverage` | 存在中断或部分失败导入 | 重新执行导入 | 支持断点续跑或失败隔离，不影响已成功数据 | A |
| TC-HKJC-012 | `international-racing-coverage` | 已导入 HKJC 样本 | 执行统计查询和样本马名查询命令 | 命令返回可读统计和指定马名结果 | A |
| TC-HKJC-013 | `international-racing-coverage` | HKJC 数据已导入 | 打开公开站点 | 不出现公开比赛页、赛果页、马匹页或完整赛程产品 | M/D |

## 8. 欧美数据库 spike 和非目标边界

| ID | 来源 | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- | --- |
| TC-SPIKE-001 | `international-racing-coverage` | 执行 Equibase 小样本 spike | 查看 spike 产物 | 说明 entries、results、charts、horse profile 字段、访问限制、反爬风险和后续建议 | D/L |
| TC-SPIKE-002 | `international-racing-coverage` | 执行英国 Sporting Life + BHA 小样本 spike | 查看 spike 产物 | 说明 racecards、results、horse profile、official horse search、监管信息字段覆盖和缺口 | D/L |
| TC-SPIKE-003 | `international-racing-coverage` | 执行 France Galop 小样本 spike | 查看 spike 产物 | 只评估结构化赛程、报名、出马、赛果和马匹资料入口，不纳入法语新闻正文 | D/L |
| TC-SPIKE-004 | `international-racing-coverage` | 任一欧美数据库 spike 完成 | 检查数据库和调度 | 不创建正式外部比赛、出马、赛果、马匹或马名索引记录，不加入 Celery Beat、正式导入队列或生产网络导入流程 | A/D |
| TC-SPIKE-005 | `international-racing-coverage` | spike 保存样本解析结果 | 检查保存位置 | 只保存到隔离 fixture、临时文件或仓库文档报告 | D |
| TC-SPIKE-006 | `international-racing-coverage` | spike 完成 | 查看仓库文档 | 记录样本 URL、请求次数、限速设置、失败情况、字段覆盖和后续正式导入建议 | D |
| TC-SCOPE-001 | `international-racing-coverage` | HKJC 或 spike 赛果数据存在 | 检查前台产品面 | 本变更不实现比赛页、赛果页、马匹页、今日赛程模块 | D/M |
| TC-SCOPE-002 | `international-racing-coverage` | 新闻文章提及已导入比赛或马匹 | 执行识别或候选发现 | 可用外部缓存辅助识别和候选发现，但公开文章详情仍以新闻内容为主 | A/M |

## 9. 迁移、文档和整体校验

| ID | 来源 | 前置条件 | 步骤 | 期望结果 | 类型 |
| --- | --- | --- | --- | --- | --- |
| TC-OPS-001 | `design.md` | 新迁移文件已生成 | 执行 Django migration dry-run 或 `makemigrations --check --dry-run` | 无遗漏迁移 | A |
| TC-OPS-002 | `tasks.md 8.1` | 本地 sqlite 配置可用 | 执行 `DB_ENGINE=sqlite python manage.py check` | Django 系统检查通过 | A |
| TC-OPS-003 | `tasks.md 8.2` | 本地测试依赖可用 | 执行相关测试和完整 `stable` 测试 | 自动化测试通过 | A |
| TC-OPS-004 | `tasks.md 8.3` | OpenSpec 变更存在 | 执行 `openspec validate expand-international-racing-coverage --strict` | 本 change 严格校验通过 | A/D |
| TC-OPS-005 | `tasks.md 8.4` | 全量 OpenSpec 文件存在 | 执行 `openspec validate --all` | 全量 OpenSpec 校验通过 | A/D |
| TC-OPS-006 | `tasks.md 8.4` | 本地改动完成 | 执行 `git diff --check` | 无尾随空格、冲突标记等 diff 问题 | A |
| TC-OPS-007 | `tasks.md 8.5` | 变更完成 | 检查 `docs/current_state.md`、`docs/project_status.md` 和必要运维文档 | 文档说明国际化规格、实现状态和后续拆分 | D |
| TC-OPS-008 | `design.md` | 本变更完成 | 检查部署记录和命令记录 | 本变更不要求也不执行生产部署 | D |

## 本轮执行记录

执行时间：2026-06-25。

已执行自动化与规格校验：

- `openspec validate expand-international-racing-coverage --strict`：通过。
- `openspec validate --all`：通过，9 项。
- `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py check`：通过。
- `DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py makemigrations --check --dry-run`：通过，无额外迁移。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py test stable --noinput`：通过，209 项。
- 2026-06-26 上线前 review 补丁：新增国际榜单来源提升后触发 QQ 自动推送编排回归用例；相关测试 `stable.tests.CrawlAutoTranslateTests stable.tests.IngestionSourceElevationTests stable.tests.QQAutoPushTests` 通过，38 项；完整 `stable` 测试通过，215 项。
- 2026-06-26 全球范围适配 review 返修：新增英文外部马名真实写法保护、非日文外部别名候选查询、旧 QQ 群空地区日本兼容、地区 tab 翻页保留过滤和英文赛马关键词评分回归用例；相关测试 `stable.tests.TermResolverTests stable.tests.QQAutoPushTests stable.tests.PublicHomeInfoFeedTests stable.tests.AutomationFlowTests` 通过，80 项；完整 `stable` 测试通过，224 项。
- 2026-06-26 review 返修：新增翻译保护使用英文外部马名真实写法、发布校验不误报已保留真实写法、英文正式术语大小写不敏感匹配与替换回归用例；相关测试 `stable.tests.TermResolverTests stable.tests.AutomationFlowTests stable.tests.TranslationWorkflowTests` 通过，51 项；完整 `stable` 测试通过，227 项。
- `git diff --check`：通过。

真实国际新闻源 dry-run：

- 命令：`DB_ENGINE=sqlite /Users/mentianlu/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 server/manage.py probe_international_news_sources --limit 2 --json`。
- 默认探测矩阵成功解析两篇真实新闻：`Sponichi latest/access`、`HKJC Racing News`、`SCMP Racing`、`Sporting Life Racing`、`Sky Sports Racing access/latest`、`BHA official`、`France Galop English News official`、`TDN France keyword`、`TDN`、`Horse Racing Nation access/latest`。
- 排序入口结论：`Sponichi 新闻ランキング`、`Sky Sports Racing Top Stories`、`Horse Racing Nation Trending` 已作为独立排序/榜单探测入口，保留原站 rank；`HKJC Racing News`、`SCMP Racing`、`BHA`、`France Galop English News`、`TDN` 未按热门榜处理。
- 旧候选源处理：`At The Races` 当前返回 403；`Paulick Report` 当前返回 403；`BloodHorse` 受反机器人/空样本风险影响；三者仍可单独指定探测，但已从第一版默认探测和生产清单移出。

执行备注：

- 直接使用系统 `python3` 时因未安装 Django 失败；随后切换到 Codex 工作区 Python 运行时重新执行并通过。该失败属于本机解释器依赖问题，不代表项目检查失败。
- 本文档的测试用例先按 OpenSpec 规格和设计拆分，再执行现有自动化与 dry-run 命令；未依据实现代码倒推用例。
