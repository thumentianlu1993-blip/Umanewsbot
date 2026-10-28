# P01 真实模型评估：未完成、未通过

2026-10-28。用户确认现有DeepSeek接口，并明确“按这个评估包执行”。本轮绑定[package.json](package.json) SHA `4a0ded7b2aae0f9af532de6831e995c25db2bde7fd9f2cd4f523825563d7d61d`，预算21美元、20篇固定样本、源码`d4ec87f731e73de9851182cf60a07c7953d0734f`。

## 结果

**18篇完成评估，均被实体校验拦截；第19篇在第56次调用传输失败、远端处理/计费不明；第20篇未开始。** 已按包内unknown规则停止，没有自动重试或继续付费调用。不能宣称20篇完成或通过。

共56次请求：19次事件分类、37次实体识别；55次有HTTP 200及usage回执，1次unknown。没有进入全文翻译或事实审校，Flash实际未调用，无法评估译文质量、两模型优劣、成功稿成本或正式日/月预算。失败调用均价不能用作生产成本。

## 发现

- 事件分类19份返回中18份触发editorial_priority_or_region、1份触发editorial_schema；19份可解析结果的primary_region均为数组，验证器要求单字符串。输入RESPONSE_SCHEMA用列表展示地区选项，存在可复现的形状歧义。
- 完成的36次实体响应中，25次首个阻断为跨度错误、7次为结构/覆盖不合格、4次为数量超限。此分类是验证器首个错误，不是人工逐项标注。重试未使前18篇通过。
- 香港稿22700将Sha Tin标为[43,51)，原文实际匹配[52,59)；识别出名称不等于可以安全占位。日本及短法国输入也复现跨度失败。
- 55次返回的结束原因：{'stop': 49, 'length': 6}。输出上限和不可解析结果不当作完整实体结果。
- 单调用时延P50 21.79秒、P95 72.13秒（nearest rank），8次超过60秒；包含SSH/HTTP往返，不是新闻端到端时效。

## 费用与停止点

已返回55笔按usage、缓存命中及[官方费率](https://api-docs.deepseek.com/quick_start/pricing/)计算 **0.703693936美元**，不是发票或最终扣款对账。峰时无缓存优惠的上界为 **0.75726552美元**。第56笔保留 **0.03872088美元**预约，不当作零费用；已知保守上界加预约 **0.79598640美元**，未超过21美元。

第56笔为22730的entity_check，已保存输入SHA和请求体，未得到供应商response/request ID或usage。初版隔离执行器在SSH/proxy子进程非零退出时没有持久化stderr和具体退出码，无法判断请求是否到达供应商；此证据缺口保留。随后仅只读确认web容器running且启动时间未变化；连通性恢复不能消除账单未知。

继续付费前须取得供应商可核对的请求状态或账单证据，处理unknown，不能通过重跑、清零或释放预约猜测未计费。修改源码、输入或范围时需形成新的精确包，按根AGENTS处理。

## 边界

本轮单模型组合，显式非思考模式；不代表Pro所有模式能力。实际返回model为deepseek-v4-pro，未提供精确版本后缀，官方版本介绍不当作实际回执版本证明。生产gateway不显式关闭思考，故本轮不是生产参数完全一致的整链验收。隔离HTTP超时180秒，应用候选60秒，评估成功返回不全等于生产可成功返回。

未加载生产术语表、canonical别名或既有事件候选，不评价译名库覆盖与跨源去重；保留原名，验证器/提示词取固定源码。为独立诊断实体，即使事件校验不通过也继续实体测试，不宣称可发布。没有手工修正输出、放宽断言或截短全文。

20篇输入清洗通过，17篇复用缓存，3篇指定netkeiba详情有界取证。按稿件实际地区选择，包含旧稿、公告、预告、赛果及播客导读，不是随机代表性样本或人工gold，未完成100篇质量集。

## 后续

1. 先对账第56笔unknown，并完善传输错误收据和断点恢复，防止重复计费。
2. 明确地区字段单选字符串合同；研究让模型返回精确原文及上下文、由程序唯一定位实体，多解继续待审，不放宽完整性/跨度规则。
3. 明确输出容量、思考模式和超时，测试后冻结；以可对账、参数一致的包复测同批输入，真正完成翻译和审校后再定模型/生产预算。

## 逐篇状态

| ID | 地区 | 状态 |
|---|---|---|
| 22726 | japan | entity_blocked |
| 22725 | japan | entity_blocked |
| 22720 | japan | entity_blocked |
| 22706 | japan | entity_blocked |
| 22700 | hong_kong | entity_blocked |
| 22608 | hong_kong | entity_blocked |
| 22715 | hong_kong | entity_blocked |
| 22624 | hong_kong | entity_blocked |
| 20780 | united_kingdom | entity_blocked |
| 20777 | united_kingdom | entity_blocked |
| 17850 | united_kingdom | entity_blocked |
| 22338 | united_kingdom | entity_blocked |
| 22154 | france | entity_blocked |
| 22044 | france | entity_blocked |
| 7611 | france | entity_blocked |
| 5700 | france | entity_blocked |
| 22684 | united_states | entity_blocked |
| 22731 | united_states | entity_blocked |
| 22730 | united_states | stopped_unknown_request |
| 18345 | united_states | not_started |

证据见[evidence.json](evidence.json)。原始请求/响应和脚本位于本机`/Users/mentianlu/.codex/runtime/p01-model-evaluation-20261028/`，哈希已绑定。API凭据未导出或写入仓库。自有validator容器已删除并确认不存在，未新建镜像。没有生产DB写入、发布、配置/调度变更、合并或部署。
