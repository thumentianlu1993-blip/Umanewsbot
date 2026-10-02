# A-002 / F01 可执行合同测试

输入：受审方案 7c78f67d04cc156520d21916f3eb0a3ef066305e；原R已APPROVED、F01-M-01 CLOSED。
范围：无ORM/网络的content_contracts DTO/serializer；不写writer/调度/迁移/许可策略。

| 场景 | 断言与必须捕获的mutation |
|---|---|
| 四组业务输入与output | 使用批准fixture；普通词不产生额外实体、同名异马保持ambiguous、confirmed不变official、date-only不变精确T；删serializer校验不能通过 |
| schema与形状 | 缺键、多键、未知schema/enum、null误用、bool冒充int、duplicate JSON键、NaN、超限深度/大小拒绝；捕获宽松透传 |
| 强身份作用域 | source/namespace/external_id三元组必需，ambiguous不得canonical，引用闭包/重复保护；捕获只按external_id合并 |
| 生产者规范化 | 无序scope/ref/evidence/material集合重排版本稳定；名单顺序改变版本变化；捕获对所有list排序或完全不排序 |
| wire严格性 | 非规范scope、篡改content/protection/fingerprint、output/input/action版本不符拒绝；捕获消费端偷偷修hash |
| 不可变/无副作用 | caller输入与to_dict副本不改变原DTO，无隐式now/ORM/网络imports；捕获共享可变dict |
| 未知与0 | null来源starts保留未知、已知0保持int0，非法负数/bool拒绝；捕获or 0或bool接受 |
| 成熟度/权限边界 | source_class与maturity独立，校验不赋予公开权限；public_summary字段严格白名单，无私有证据/锁/任务字段；捕获内部DTO直接透传公开 |
| failure/兼容 | 所有坏输入稳定ContractError（无敏感payload回显），旧/未知schema拒绝、不转换旧writer字段；捕获宽松回退 |

RED：先提供无行为API骨架（NotImplementedError）供正常导入，测试直接调用批准fixture的解析/serialize目标，失败来自未实现行为而非import或环境。
GREEN：同一行为测试通过后再扩展负例/规范化测试；保存命令、退出状态、结果。
测试为stdlib unittest，无DB/Redis/队列/第三方；Linux固定树证据仍走现行test-impact，不以宿主结果替代。
新路径映射需独立受审；Docker尚不可用已报告协调者。全量/映射演进由既有规则决定，不做空选集。

原R补充mutation：action两个预期版本副本以True/1.0替代整数1分别拒绝；公开identity_state在verified/unresolved/revoked三状态间六种错配拒绝，匹配不变；不只比较Python宽松dict相等或kind/id。
