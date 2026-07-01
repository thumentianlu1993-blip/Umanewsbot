## 1. 多地区与多语言基础模型

- [x] 1.1 (application) 为 `NewsSource`、`NewsArticle` 和必要外部数据模型新增地区与原文语言字段，并为现有数据回填 `japan / ja`
- [x] 1.2 (application) 为地区和语言字段增加模型校验、显示标签、后台筛选和测试
- [x] 1.3 (integration) 调整来源同步与入库服务，使每个适配器写入稳定的地区、原文语言和来源类型
- [x] 1.4 (application) 更新管理命令、API payload 和后台列表，展示地区与原文语言

## 2. 前台地区 tab

- [x] 2.1 (application) 为公开首页新增地区 tab 测试，覆盖综合、日本、中国香港、英国、法国、美国
- [x] 2.2 (application) 实现 `/?region=<region>` 或等价稳定入口，地区 tab 只展示对应地区已发布文章，综合展示全部已发布文章倒序
- [x] 2.3 (application) 调整公开首页模板与 `public.css`，在桌面和移动端展示地区 tab，并确保 tab 不遮挡新闻内容
- [x] 2.4 (application) 在文章详情页展示地区、来源和原文语言标签

## 3. 术语库多原文语言适配

- [x] 3.1 (application) 为 `TermEntry`、`TermCandidate` 或等价术语对象增加 `source_language`，现有术语回填 `ja`
- [x] 3.2 (application) 将后台术语表单、快速创建、导入预览和候选池中的“日文原词/日文别名”展示为“原文/原文别名”
- [x] 3.3 (integration) 调整术语解析、翻译提示和发布校验，按 `source_language` 分流日文、英文和繁体中文规则
- [x] 3.4 (application) 增加英文术语、繁体中文术语和日文术语共存的回归测试

## 4. QQ 群级地区推送配置

- [x] 4.1 (application) 为 `PushTarget` 增加群级允许地区、推送范围和重点策略配置，并迁移现有群为等价旧行为
- [x] 4.2 (integration) 调整 QQ 自动推送资格判断，使每个目标群按自身地区配置、范围配置和重点策略判断是否创建/处理交付
- [x] 4.3 (application) 在 Django Admin 展示并允许维护群级地区与范围配置
- [x] 4.4 (application) 增加多群差异化推送测试，覆盖同一文章对不同群允许/跳过的结果
- [x] 4.5 (application) 增加地区缺失保护测试，确认缺少地区的公开文章不会自动推送，并记录 `region_missing` 或等价跳过原因
- [x] 4.6 (operations) 更新 QQ 推送运维文档，说明总开关、群级配置、默认值和回滚方式

## 5. 一期国际新闻源

- [x] 5.1 (integration) 为 `Sponichi` 新闻源实现列表与详情适配器，并标记 `japan / ja`
- [x] 5.2 (integration) 为 `HKJC Racing News` 与 `SCMP Racing` 实现新闻源适配器，并标记 `hong_kong / en` 或 `hong_kong / zh-hant`
- [x] 5.3 (integration) 为 `Sporting Life Racing` 与 `BHA` 实现新闻源适配器，并标记 `united_kingdom / en`
- [x] 5.4 (integration) 为 `At The Races` 法国赛马相关英文内容实现受控新闻源适配器，并标记 `france / en`
- [x] 5.5 (integration) 为 `BloodHorse` 与 `Paulick Report` 实现新闻源适配器，并标记 `united_states / en`
- [x] 5.6 (application) 增加各来源最小解析测试，覆盖标题、正文、发布时间、原文 URL、地区和语言

## 6. HKJC 外部数据导入

- [x] 6.1 (integration) 设计并实现 HKJC 外部数据适配器，支持按日期/赛日、单场比赛和单匹马受控导入
- [x] 6.2 (application) 保存 HKJC 比赛、出马、赛果、马匹、血统/父母、马主、练马师、骑师、档位、场地状态和原始 payload
- [x] 6.3 (integration) 从 HKJC 出马、赛果和马匹资料派生 `ExternalHorseAlias` 或等价本地马名索引
- [x] 6.4 (operations) 提供 HKJC dry-run、统计查询和样本马名查询命令，并记录限速配置
- [x] 6.5 (application) 增加 HKJC 导入幂等、断点续跑、限速互斥和字段解析测试

## 7. 全球数据源 spike

- [x] 7.1 (integration) 对 `Equibase` 做小样本 spike，输出 entries/results/charts/horse profile 字段覆盖、访问限制和后续实现建议
- [x] 7.2 (integration) 对英国 `Sporting Life + BHA` 做小样本 spike，输出 racecards/results/horse profile 字段覆盖、公开接口和后续实现建议
- [x] 7.3 (integration) 对法国 `France Galop` 做小样本 spike，输出 calendar/declarations/results/horse profile 字段覆盖、语言风险和后续实现建议
- [x] 7.4 (integration) 确认 spike 不加入 Celery Beat、生产管理命令调度或正式导入队列，不写入正式外部数据表；如需保存样本，只能写入隔离 fixture、临时文件或文档报告
- [x] 7.5 (operations) 将 spike 结论写入仓库文档，记录样本 URL、请求次数、限速设置、失败情况，并明确哪些源可以进入后续正式导入 change，哪些源只保留人工参考

## 8. 验证与收尾

- [x] 8.1 (application) 执行 `DB_ENGINE=sqlite python manage.py check`
- [x] 8.2 (application) 执行相关 Django 测试和完整 `stable` 测试
- [x] 8.3 (application) 执行 `openspec validate expand-international-racing-coverage --strict`
- [x] 8.4 (application) 执行 `openspec validate --all` 和 `git diff --check`
- [x] 8.5 (operations) 更新 `docs/current_state.md`、`docs/project_status.md` 和必要运维文档，说明本轮国际化规格、实现状态和后续拆分

## 9. Review 返修

- [x] 9.1 (operations) 更新 proposal、design 和 delta specs，明确 HKJC 超上限失败、公开数字 ID 与来源去重键分离、自动评分语言隔离、HTML metadata 瘦身
- [x] 9.2 (integration) 修复 HKJC commit 导入，使 payload 超过 `max_races / max_horses` 时直接失败且不写入数据
- [x] 9.3 (application) 修复自动化评分术语命中，使重点马匹和赛事优先级只使用文章原文语言对应术语
- [x] 9.4 (integration) 修复国际新闻来源键生成，使用完整 URL 派生低碰撞稳定键，同时保持公开详情使用 `NewsArticle.id`
- [x] 9.5 (application) 修复入库 metadata，确保整页 HTML 只写入 `original_content_html`，不进入 `translation_metadata`
- [x] 9.6 (application) 补充回归测试并重新执行相关测试、完整 `stable` 测试、OpenSpec 校验和 `git diff --check`
- [x] 9.7 (operations) 回写 `docs/current_state.md`、`docs/project_status.md` 和必要决策/运维文档，记录 review 返修结果

## 10. 术语概念模型返修

- [x] 10.1 (operations) 回填 proposal、design 和 delta specs，明确 `TermEntry` 是正式术语概念，`TermAlias` 承载多语言原文名和别名
- [x] 10.2 (application) 新增 `TermAlias` 或等价模型与迁移，将现有 `source_ja / aliases_ja` 回填为 `ja` 原文别名
- [x] 10.3 (integration) 调整术语导入、快速创建、候选接受与候选合并，使同一术语概念可以拥有不同语言原文别名
- [x] 10.4 (integration) 调整翻译、自动化评分、发布校验和自动标签，使匹配按文章原文语言选择别名，命中后回到同一正式术语概念
- [x] 10.5 (integration) 收窄国际新闻列表选择器，并为每个新增网站提供抓取两篇真实新闻的 dry-run 探测入口或验收记录
- [x] 10.6 (application) 补充同一马匹日英繁别名、跨语言候选合并、自动标签语言隔离和国际列表过滤测试
- [x] 10.7 (application) 重新执行 Django 检查、相关测试、完整 `stable` 测试、OpenSpec 校验和 `git diff --check`
- [x] 10.8 (operations) 回写 `docs/current_state.md`、`docs/project_status.md` 和必要决策文档，记录术语概念模型返修结果

## 11. 新闻源可爬性和榜单入口补强

- [x] 11.1 (integration) 重新 dry-run 探测全部新增国际新闻源，记录可正常抓取来源和访问受限来源
- [x] 11.2 (integration) 调研各新增新闻源是否存在类似 netkeiba 访问量榜/注目榜的公开排序入口
- [x] 11.3 (application) 接入已确认可稳定公开抓取的 `Sponichi` 新闻ランキング，作为 `source_mode=access` 榜单源并保留原站排名
- [x] 11.4 (application) 补充 Sponichi 混合榜单过滤、原站排名保留和内置来源定义测试
- [x] 11.5 (operations) 回写 OpenSpec、测试用例和项目文档，记录其它来源无公开榜单或存在 403/反爬风险

## 12. 上线前最终源清单返修

- [x] 12.1 (operations) 回写 proposal、design 和 delta spec，将第一版生产源改为实测可用清单
- [x] 12.2 (integration) 新增 `Sky Sports Racing`、`France Galop English News`、`TDN`、`TDN France keyword` 和 `Horse Racing Nation` 新闻适配器
- [x] 12.3 (application) 调整内置来源定义，使不可用候选源保持关闭或移出第一版默认清单，最终源默认关闭等待灰度启用
- [x] 12.4 (application) 补充最终源解析、排序 rank、WordPress API、法国英文过滤和不可用候选源默认关闭测试
- [x] 12.5 (integration) 扩展 dry-run 探测命令，覆盖最终第一版所有源并输出统一可用性字段
- [x] 12.6 (application) 重新执行 Django 检查、相关测试、完整 `stable` 测试、OpenSpec 校验和 `git diff --check`
- [x] 12.7 (operations) 回写 `docs/current_state.md`、`docs/project_status.md`、`docs/decisions.md` 和测试用例，记录上线前仍需整体 review 与灰度步骤
