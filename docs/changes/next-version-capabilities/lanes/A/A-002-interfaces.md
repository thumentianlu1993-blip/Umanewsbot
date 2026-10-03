# A-002 / F01 共享类型接口与测试映射

方案输入：7c78f67d04cc156520d21916f3eb0a3ef066305e，原R已APPROVED/F01-M-01 CLOSED。
代码文件 `server/stable/services/content_contracts.py`，不import模型、Django、Celery、网络库，不使用隐式时间。

| API | 合同 |
|---|---|
| `parse_input(dict或JSON字符串) -> LoaderInput` | 严格schema/字段/enum/UTC时刻/source三元键/摘要/规范无序集合；坏wire不修复 |
| `build_input(snapshot, *, evaluated_at, policy_ref, generations, scope=INPUT_SCOPE)` | 生产者规范化无序集合，派生Protection和content摘要；业务名单顺序原样保留；f01.v1只支持五个顶层snapshot依赖闭集，不能缩scope |
| `parse_decision(value, *, input_document) -> DecisionOutput` | 校验形状以及input/fingerprint/entity/policy/now/action版本与证据引用；不计算业务决定，不获得执行许可 |
| `parse_public_summary(value) -> PublicSummary` | 公开字段白名单；拒绝source_refs/candidate_ids/evidence_refs以及原始证据/锁/动作字段；仅形状检查，调用者须先过原publication validator |
| DTO `.to_dict()/.to_json()` | frozen JSON值对象，to_dict独立副本；构造函数也做形状校验；DecisionOutput直接构造只有结构验证，输入绑定须调用parse_decision，不允许消费者把直接构造当完整绑定 |
| `ContractError` | 稳定错误码，不回显源payload或凭据；1MiB/64层/100000节点限制、严格内置JSON类型、重复键/循环/NaN拒绝 |

f01.v1按受审四组资料定义窄data白名单，未定义字段拒绝；后续B/C/A资料业务提出字段合同后受审增补，不能靠任意JSON直写writer。
`career.known_zero_control`是受审四组fixture内的已知0对照，保留其严格子形状以支持原正例；不提供任何writer/统计接入。
来源class和maturity分别校验而不推断；DTO合格不代表身份事实、来源权利、校验结果或已公开是可信事实。
公开entity_ref只保留用户可用的稳定实体与状态，内部source/candidate/evidence引用要求空数组。

测试映射单独审核：

- 新领域content_contracts仅拥有stable.test_content_contracts整类；目前没有现有应用消费者，没有虚构业务依赖。
- 新模块、该领域测试及既有离线文档校验器显式映射；core由现行工具添加。
- rules/catalog变更按现行流程触发full，保留原base和候选两套覆盖并集，不改选择算法、runner或skip政策。
- 当前本地stdlib结果是开发证据，Linux固定树full及候选外收据由现行工具/协调者产生；不得用宿主GREEN冒称交付。
