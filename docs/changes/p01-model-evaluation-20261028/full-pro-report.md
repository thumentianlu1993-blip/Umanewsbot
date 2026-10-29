# Pro思考完整20篇评估结果

2026-10-29。执行完成标记：True；本轮调用107次，完整收据107份，新未明或待处理0笔。全部20篇完成尝试。

## 结果边界

固定原20篇缓存、新版提示词与现有校验器；Pro思考high处理事件/实体/审校，Flash非思考翻译，客户端均不设置max_tokens。供应商默认限制仍为Pro思考64K、Flash非思考8K；不是无限输出。HTTP1200秒，串行。模型输出经现有契约校验，未自动修跨度、放宽数字规则或补缺失占位符。非随机样本、没有完整人工gold，下面是程序及模型审校结果，不是公开发布资格或质量验收。

- 实体首轮通过：14/20；包含最多一次重试后：19/20。
- 有通过结构校验的译文：17/20；翻译与事实审校最终通过：5/20。
- 事件输出结构通过：18/20。reject/uncertain结构通过不代表可发布或判断准确。
- 状态计数：`{"translation_or_audit_blocked": 14, "translation_checks_passed": 5, "entity_blocked": 1}`。
- 停止信息：`null`。

| 样本 | 地区 | 实体首次/最终 | 翻译审校最终状态 | 事件优先级 |
|---|---|---|---|---|
| 22726 | japan | 通过/通过 | translation_or_audit_blocked | uncertain |
| 22725 | japan | 通过/通过 | translation_or_audit_blocked | uncertain |
| 22720 | japan | 通过/通过 | translation_or_audit_blocked | uncertain |
| 22706 | japan | 通过/通过 | translation_checks_passed | uncertain |
| 22700 | hong_kong | 通过/通过 | translation_or_audit_blocked | uncertain |
| 22608 | hong_kong | 通过/通过 | translation_or_audit_blocked | uncertain |
| 22715 | hong_kong | 未通过/未执行/通过 | translation_or_audit_blocked | uncertain |
| 22624 | hong_kong | 通过/通过 | translation_or_audit_blocked | uncertain |
| 20780 | united_kingdom | 未通过/未执行/通过 | translation_or_audit_blocked | uncertain |
| 20777 | united_kingdom | 未通过/未执行/通过 | translation_checks_passed | uncertain |
| 17850 | united_kingdom | 通过/通过 | translation_or_audit_blocked | reject |
| 22338 | united_kingdom | 未通过/未执行/通过 | translation_or_audit_blocked | uncertain |
| 22154 | france | 通过/通过 | translation_or_audit_blocked | uncertain |
| 22044 | france | 通过/通过 | translation_checks_passed | 结构未通过/未执行 |
| 7611 | france | 通过/通过 | translation_or_audit_blocked | reject |
| 5700 | france | 通过/通过 | translation_checks_passed | 结构未通过/未执行 |
| 22684 | united_states | 未通过/未执行/未通过/未执行 | entity_blocked | uncertain |
| 22731 | united_states | 未通过/未执行/通过 | translation_or_audit_blocked | uncertain |
| 22730 | united_states | 通过/通过 | translation_checks_passed | uncertain |
| 18345 | united_states | 通过/通过 | translation_or_audit_blocked | reject |

## 阻断分类与下一步

最终结果互斥分类为：5篇翻译审校通过；6篇模型自审pass但数字表面比较阻断；5篇最终有效译文被模型审校判为fail（可同时存在数字差异）；2篇两轮翻译均缺占位符；1篇修复后的翻译schema失败；1篇两轮实体coverage均uncertain。共20篇，不把同一稿件重复计入总数。

6篇数字表面阻断的所列差异经有限人工复核，涉及月份/中文数词、级别、时间和金额单位转换；这说明现有表面比较未完整覆盖语义等价表达。仍不能直接把6篇算作全文质量通过，已看到部分术语或中文表达缺陷。5篇翻译审校通过中，22044与5700的事件身份依据仍未通过，所以5篇不代表完整发布链路通过。

建议按以下顺序继续（本轮尚未实施）：

1. 明确数字、日期、时间、金额单位转换的允许规则，以真实失败样本设计正反例；只消除确定的误拦截，同时保留真正数值变化的阻断。
2. 加强翻译与修复提示的完整性、中文语言质量及占位符保护；针对2篇占位符失败、1篇修复schema失败、未译句/词与术语错误作小样本回归，再评估是否需要Pro翻译对照。
3. 对19篇实体成功中的重试成本及1篇uncertain保持独立指标。完成上述修复后，使用固定样本复测并补充人工质量gold，才能讨论生产模型组合与上线。

本轮没有自动更改以上规则、提示词、模型分工或生产参数。

| 地区 | 样本 | 实体首轮通过 | 实体最终通过 | 翻译审校通过 |
|---|---:|---:|---:|---:|
| france | 4 | 4 | 4 | 2 |
| hong_kong | 4 | 3 | 4 | 0 |
| japan | 4 | 4 | 4 | 1 |
| united_kingdom | 4 | 1 | 4 | 1 |
| united_states | 4 | 2 | 3 | 1 |

各地区仅4篇，非随机样本，不做统计外推。

## 有限人工复核与诊断

- 22726：数字表面比较拦截至少包含阿拉伯数字转中文数词：原文6、7割译成六、七成，10割译成十成；语义相符，不能直接称漏译或事实错误。当前规则未改，仍记录为程序拦截。（人工有限复核，仅上述数字表达，不等于全文gold验收）
- 22720：第二轮修复后数字表面匹配，但目标正文保留一整句日文，Pro审校以completeness=false拦截；有限人工检查确认该句未完整翻成中文。（仅审校标注片段，不等于全文gold验收）
- 22725：两轮翻译均缺少b0中的__P01_ENTITY_000__，占位符计数可复现；未判定缺失原因或全文质量。（程序诊断）
- 22700：数字拦截包括Class 2译为第二班、6.45pm译为下午6时45分，属于表达变换，不能直接等同事实错误。另有限人工观察triple winner译为三届冠军，可能把获胜次数误成届次，需赛马术语复核；模型自审两轮均pass。（有限片段复核，非全文gold）
- 22624：第二轮目标正文出现“人们所 perception 的”中英混写；Pro以completeness=false拦截，有限人工复核确认普通词未完整翻成中文。（仅审校标注片段，非全文gold）
- 17850：数字差异为Group 1译为一级赛、August译为8月，数值语义相符；但同段术语和亲缘表述仍需人工复核，数字误拦截不代表全文合格。（仅所列差异块）
- 22608：数字差异包括G1译为一级赛、April译为4月，未在所列差异中观察到数值改变。（仅所列差异块）
- 22715：数字差异为May译为五月、gate six译为第6档，数值语义相符；four-time winner译为四届冠军仍有术语问题。（仅所列差异块）
- 7611：数字差异为百万欧元改写为亿/万欧元：725million=7.25亿、802million=8.02亿、26.2million=2620万、16.5million=1650万；所列换算相符。（仅所列金额换算）
- 18345：审校标注地名问题；目标将Louisville, Ky.拆成Louisville与句末悬空Ky.，有限复核确认地点表达破碎。（仅审校标注段落）
- 22154：across the Channel译成Channel各地，有限复核认为改变了海峡对岸的地理关系；模型以unsupported_claims拦截。（仅审校标注段落）
- 20780：原文含he/a等拼写错误，目标出现一场Newmarket的病句；模型以unsupported_claims拦截，需人工结合原文语境判断。（仅审校标注段落）

程序阻断中既有内容问题，也有表达转换造成的表面差异；不能把全部阻断直接解释为错译。反过来，模型自审pass也不等于人工确认准确。失败样本的原文、译文、修复请求和完整返回均保存于runtime，用于后续逐项复核。

## 成本与时延

本轮按usage与时段/缓存费率计算 **1.983036342美元**；峰时无缓存上界 **3.73024854美元**；累计保守上界含历史及所有预约 **4.89675234美元/20美元**。旧未明0.03872088美元保留，不重试且不宣称已对账。usage估算不是平台最终扣款对账。

单次调用P50 28.80秒、P95 269.68秒、最大572.70秒；不是文章端到端SLA。

| 阶段 | 次数 | P50秒 | P95秒 | 用量计价美元 |
|---|---:|---:|---:|---:|
| event_classify | 20 | 23.48 | 90.74 | 0.129667780 |
| entity_check | 26 | 206.17 | 345.68 | 1.344400904 |
| translate_full | 33 | 4.89 | 9.25 | 0.032507982 |
| fact_audit | 28 | 50.32 | 133.89 | 0.476459676 |

本批只是包含失败与修复成本的样本，不据此直接确定日/月生产预算或最终模型选型。长文实体思考时延、实际合格率、供给量和后续修复后的成本均需纳入。未将模型返回内容作为网页/QQ发布。

## 处理量情景（不是生产预算承诺）

本批包含失败及修复的平均处理费用约0.0992美元/篇，峰时无缓存上界均值约0.1865美元/篇。以下仅假设每天样本长度、阶段、重试和缓存/时段混合与本批相同，按30天换算；不含抓取、人工复核、存储及运行设施，也没有计入未来修复后新增的调用。

| 每日处理篇数 | 日费用按本批usage均值 | 30天费用 | 日费用按本批峰时无缓存均值 |
|---|---:|---:|---:|
| 20 | $1.98 | $59.49 | $3.73 |
| 50 | $4.96 | $148.73 | $9.33 |
| 100 | $9.92 | $297.46 | $18.65 |

整批串行执行约141.33分钟，107次响应全部stop，无输出截断；单次最大572.70秒。当前1200秒测试超时与生产时效要求需要单独评估。本轮5/20翻译审校通过率不能作为成功稿件产能预测，不能据上述均值直接批准自动化预算。

## 核验与交付

7项离线代理保护测试通过。固定输入、提示及runner哈希复核通过；所有settled请求均核对请求SHA/operation/本地收据与远端持久化收据。临时validator容器已确认删除。没有生产DB写入、配置/调度/队列变更、对外发送、合并或部署。

[执行包](full-pro-plan.md)；[机器包](full-pro-package.json)；[逐篇及费用证据](full-pro-evidence.json)。本地完整结果：`/Users/mentianlu/.codex/runtime/p01-full-pro-20261029/`。远端收据在web容器`/tmp/umanews-p01-eval-20261029/`，重建可能删除，本地已核对留存。费率：[DeepSeek官方价目](https://api-docs.deepseek.com/quick_start/pricing/)。
