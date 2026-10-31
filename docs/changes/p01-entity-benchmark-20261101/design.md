# 数据格式与实现设计

## 1. 现有实现与兼容性

- `server/stable/services/news_entity_units.py`当前提供initial_payload、repair_payload、evaluate、occurrences与replay；gold绑定完整clean，适配器负责将各实验协议转成统一canonical occurrences。
- `news_content.validate_entities`负责合法跨度、类型、重叠并过滤common_word；它不证明实体语义或全文覆盖。
- `news_evaluation.validate_gold`目前硬编码100篇、75/25划分，并要求body_blocks/entities/facts/editorial四类标注。它不是本设计200篇实体专项评估器，不能给200篇传进去后删除报错，也不能只换计数冒称全链路gold。
- 后续新增独立版本的entity benchmark校验/评分入口，保留旧评估器和历史包语义。可复用来源文件哈希、digest、预算、收据和业务投影函数，不引入Django生产数据库依赖或新Celery架构。

本轮仅新增设计文件，未修改上述代码。拟议模块位置可为`news_entity_benchmark.py`与对应离线管理命令；实际实现前结合仓库入口定名，不冒称已经存在。

## 2. 三类工件分离

1. **input包**：sample_id、clean原文和输入所需语言；不包含gold、难例标签、expected_action或裁决说明。
2. **gold包**：mentions、hard_negatives、ambiguous_spans、标注版本与人工复核信息；模型执行器不挂载。
3. **manifest与结果包**：固定样本顺序/分组/划分/哈希、配置SHA、运行回执、评分与聚合；标签字段只供本地评分器读取，不拼到模型prompt。

数据文件位于任务专用runtime或管理员受控目录；源码仓库保存规范与合成示例，真实全文按既有来源许可处理。无生产业务数据库迁移。

## 3. 单篇记录契约

| 对象 | 必需字段/约束 |
| --- | --- |
| 样本元数据 | sample_id、origin(cached_real/synthetic)、source_url、provenance、region、language、publication_time或unknown、cached_at、source_sha、clean_sha、cleaner_version |
| 分组与划分 | event_group、leakage_group_id、derived_from、split、exposure_status、exposure_reason；只允许development/holdout/challenge |
| clean | title、有序blocks(id/text)；使用正式输入快照和业务digest，原始文件另存字节SHA256 |
| gold正例 | mention_id、block_id、start、end、text、type、context_start/context_end/context、acceptable_variants[]、boundary_reason |
| 变体 | 相同block/type，自己的start/end/text与reason；完整跨度必须可从原文恢复 |
| 负例/不确定 | span/context、reason；不确定另有allowed_action=review，不填虚构类型 |
| gold状态 | annotation_version、annotation_origin、annotators、reviewer、adjudication记录、coverage_checked、status(draft/adjudicated_human) |
| 评估活动 | code/model/prompt/adapter/retrieval配置、dataset/gold/split/input哈希、seed、调用上限、预算、价格/时间、活动状态 |

source_sha、clean_sha、gold_sha各自绑定不同对象，不能混用。clean_sha由冻结的业务序列化定义生成；文件sha256是原始字节，两者分别记录。数据集manifest使用固定JSON规范序列化生成digest，不能因为顺序漂移产生两个同名版本。

`examples.json`展示合成标注格式及预期判断，不是完整生产manifest或真实gold；明确synthetic/agent_draft。实施时须补齐schema必需元数据并禁止它进入真实100篇计数。

## 4. 执行流程

库存→输入完整性审查→查重/事件分组→开发与锁定划分→盲标与裁决→冻结gold→离线评分器自测→开发实验→冻结baseline/候选→隔离锁定执行→本地评分→揭盲报告。

每个模型操作绑定activity/sample/config/repetition/stage/attempt以及request SHA。先持久化预约与操作标识，再发送；记录原始响应和校验结果，评分可完全离线重算。断点恢复只执行已证明未发送的操作，不重发unknown；unknown保留费用预约并停止活动核对。模型返回缺usage、截断、配置漂移或收据矛盾单列，不算识别成功。

自动测试只用本地合成/许可fixture和mock，不访问真实API/生产DB/Redis。真实评估是显式有界活动，使用既有安全凭据通道，不输出凭据或把凭据写入包。

## 5. 范围与标注歧义

gold允许的边界变体是同一mention的备选，不是“可有可无的实体”。主匹配以一对一为准；hard_negative中含等级G1，不得仅因某个已被允许的完整赛事变体跨过G1就判误抽。只有未匹配的专名预测才进FP与hard_negative错误归因。负例与独立正例的矛盾由lint拒绝；允许变体内部的通用词注释需显式标为contained_generic，不能作为另一个必须禁止的独立实体跨度。

同样，原文真实不可判明和标注员尚未裁决不可混淆：前者属于gold安全处置，后者阻止gold冻结。当前业务review状态不携带细粒度不确定类别时，由评估适配器读取完整失败/回执证据，但不根据gold修改模型结果或强行放行。

## 6. 计算与存储边界

匹配在同article/block内构图；输入gold及预测条目数量需受评估器资源上限保护，但超过上限不得裁剪后算完整。gold保留真实文章容量，业务能力限制作为capacity错误。对异常大输入预登记文件字节/mention数量保护并报告未评分，整篇主通过仍为0；活动完成状态需区分资源错误和正常评估。

没有数据库迁移、生产worker/beat变更、发布开关或QQ调用。没有共享可写状态需要生产锁。运行目录按活动隔离，禁止两个执行器消费同一活动；可用进程级锁或原子操作状态，锁带owner/活动ID/存活信息，进程退出可释放。评分过程只读输入，输出新报告版本，不覆盖旧回执。
