# B035 N01最小切片测试设计

范围：既有正文cleaner/国际adapter纯解析。保存已有metadata供后续持久化消费者，不新增models/views/settings/迁移/网络/模型调用。Sporting Life只用现有两个可信正文容器，缺失显式selector_not_found。按ROOT指令先最小切片提交后原R独立复审，当前为本线方案/测试自检，不冒称独立review已通过。

| 用例 | 预期 | 捕捉mutation |
|---|---|---|
| 正常现有HRN/SL fixture | 首尾/段落/引语/列表/表格/图片说明/赔率和专名保持，输出与base固定预期一致 | 误删关键正文/术语/全部正文 |
| structured与语义污染 | 每项删除有原因/原文/空结果，部分CTA修改有原文与保留结果 | 只有总计无区块证据，变更无原因 |
| 稳定ID/重复段落 | 同一source/输入重解析ID相同，重复文本不同ID，HTML/body before/after可对照 | 随机ID、文本重复合并、不能回到原文 |
| SL宽article/main有导航推荐但没有可信容器 | 明确selector_not_found且正文空，不把污染当非空成功 | 恢复宽容器fallback |
| 可信正文仅噪声/空 | empty_after_cleaning，记录缺口，不恢复原噪声当正文 | 删除全篇仍ok/恢复脏正文 |
| TDN leading/tail、SPONICHI图/促销及SL inline | 原规则/count/输出不变，每块结果可追踪 | trace改写原规则或数目 |
| 小标题/blockquote/表格/图片caption/多行边界 | 原DOM顺序不变，不删同词合法句 | 宽关键词整段删除 |
| None/选择器漂移/模型/下游 | 原selector状态保持；纯解析不访问DB/网络/queue；不改下游自动发布 | 意外调用外部、伪造下游完成 |

RED使用SimpleTestCase（不需要DB），socket连接强制拒绝。最小body blocks缺失断言与SL污染fallback断言先失败；GREEN后同例及现有代表模板逐字正文回归，停止。输出大小随原正文区块线性增长；只保存必要文本/路径/hash，不复制图片或整个网页入trace。并发/lease/事务/部署不涉及，本轮不以SQLite/mock冒称其正确。

剩余：五地区真实启用模板覆盖、独立gold误删/污染率、模型审查、UI展示和生产验收未完成。F02真实样本缺口不能被这次fixture填充。
