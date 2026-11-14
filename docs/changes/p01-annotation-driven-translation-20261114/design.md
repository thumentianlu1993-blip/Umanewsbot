# 实现设计

## 版本与在线链路

新增news_entity_taxonomy纯常量/规范模块，legacy/context-v2保持5类+common_word，context-v3为9类+common_word；unknown version fail closed。NEWS_QUALITY_POLICY.contract_version显式选择，新版本不成为默认配置。

news_entity_units将版本作为initial_payload/repair_payload/replay/occurrences的证据；v3状态携带版本，v2形状不变。模型仍给原文text/context，程序定位，避免强迫模型数Unicode字符。片段仍逐块定位保护，不跨块伪造跨度；离线数据用entity_group_id/name_segments关联同一完整名称，片段计数与语义组数分开。

news_content验证新类型；现有term resolver只对已识别occurrence寻找确认译名，不启用新马名识别。v3翻译输入增加有界实体glossary；发布重放验证输入与snapshot，不能只验证模型称通过。相同term_id的译名矛盾拒绝，未知名称原样保留，不按表面同名强行合并身份。新类别暂无术语表类型时保留原名，不直接给TermEntry增加类别/迁移。

模型gateway所有context路径兼容v3，实际contract_version/prompt_sha进入spec/cache与付费回执验证。旧run因policy_sha变化不继续；不自动重放付费调用。v3发布重放必须要求对应entity-units-v3，旧v2不能混用。

## 离线评估与数据

新增news_annotation_evaluation纯函数模块与离线management command，CLI只读本地输入写指定输出，禁止请求模型/数据库。规范化样本含schema、sample_id、title/blocks哈希、原split、exposure、annotation_status、mentions、人工裁决和groups。严格验证重复ID、整数半开跨度、重叠、类型、片段对应关系、源哈希；所有已知事件关联合组，曝光不会因重分组消除。

实体预测为每sample一条状态记录（complete/uncertain/timeout/truncated/protocol_error/not_run等）及mentions；冻结全集决定分母，缺失记录计not_run，重复/未知ID拒绝。协议无效本篇可用集合为空，原始问题仍计诊断。最大基数一对一匹配canonical及预声明variants，canonical分数另列，绝不运行后放宽参考。common_word不是正例，仍检查其跨度与重叠。不凭模型complete认定实际无遗漏。

翻译评估不将参考译文字符串包含匹配当最终语义真值。事实参考每项带source block/span/quote、类别、中文命题、可接受译法和不可混淆点。对候选译文的审阅记录绑定source/reference/target SHA，逐事实supported/contradicted/missing/uncertain、目标证据，加全文额外断言与自然度评价。缺失/过期/自称但无证据的评价不通过。报告机器结构/实体保护与外部语义评价分别统计，失败仍保留全文分母。

20篇事实包仅从开发D组选择日英/文章类型覆盖；不得读取旧T组gold做提示例子。仓库保存规范、合成回归、来源manifest和统计；新闻全文及派生事实参考保存在专用runtime目录，不提交文章全文。

## 安全、兼容与回滚

本轮无数据库迁移、生产数据写入、网络抓取、计费模型调用。离线评估不启动Celery。在线改动仅显式v3策略启用后生效；新旧配置互不重用缓存。回滚到旧策略会令新run的policy_sha不匹配并停止，回滚时先停调度并清点在途/unknown；旧策略恢复须设置新的rollout_revision（参与现有policy_sha），按新身份调用start_revision，使旧pending/stale均不复活。所有旧回执/unknown预约保留，迟到结果仅核账，不投射到新run。禁止直接恢复完全相同旧策略哈希；本轮不执行回滚或改生产配置。独立review及固定源码隔离PG回归后准备Draft PR；本分支依赖尚未合并的P01栈，必须明示基线，不能直接当main可部署变更。

## 方案审核修订

预测必须绑定sample_id、source_sha、contract_version（legacy/context-v2/context-v3）和reference_sha（单篇完整规范化参考，含variants）。评估报告绑定有序全集manifest_sha及scoring_version；比较要求相同manifest/scoring版本，候选协议变化显式列出但不改变评分口径。错源文/错reference作为本篇protocol_error保留分母，未知/重复样本ID拒绝整个预测文件。

v3实体容量256，v2/legacy仍128；初轮、修复累计、occurrences及发布重放统一。单个模糊位置候选数仍128、单元512、JSON大小限额保持原有有界限制。超限报capacity，不能截断通过；D015 158/T001 130已处于v3容量内。付费输出token预算不自动扩大，真实调用预算仍另行冻结。
