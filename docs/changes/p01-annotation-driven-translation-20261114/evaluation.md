# 离线使用与证据边界

## 版本

九类口径及排除项以 `server/stable/services/news_entity_taxonomy.py` 为机器规范。
legacy/context-v2保持原合同；显式context-v3使用entity-units-v3和256处容量。
本轮不变更默认配置，不维护/检索马库；未知名称保留原文。

## 数据

本地冻结包经SHA256SUMS自身哈希及所列全部文件哈希验证后导入120篇、4619处、44项人工裁决。
原split不变，但曝光样本仅用于development/regression。四组已知跨集合事件连通，原T组不能声称盲测。
完整原文及派生事实仅存专用runtime；仓库保存data-manifest.json/fact-manifest.json。
20篇（10英、10日）共80项AI辅助关键事实，带原文半开跨度、中文命题、可接受表达与混淆点。
这些不是全文人工gold，也不是已完成的真实模型质量评估。

全120篇按新增类别已知表面词扫描，检出3条候选（D010两条嵌套名称实际同一位置、T024一条），
保留在本地recall-audit.json待上下文复核，未更改已冻结参考。该扫描不证明新类别语义召回完整；
umamusume无真实正例，仅有合成合同测试。

## 命令

以下管理命令禁用Django系统检查，只读本地JSON和写指定输出，不调用数据库/模型/网络。
输入/输出路径由操作者指定；不要把新闻全文输出至仓库。

```sh
python server/manage.py evaluate_news_annotations import --input /path/to/package --checksum-manifest-sha 426bf9b73308216f04b009cd86246855710981e67493fa18000075988aa1dc9b --output /runtime/references.json
python server/manage.py evaluate_news_annotations entities --input /runtime/references.json --predictions /runtime/predictions.json --output /runtime/entity-score.json
python server/manage.py evaluate_news_annotations compare --input /runtime/baseline.json --predictions /runtime/candidate.json --output /runtime/comparison.json
python server/manage.py evaluate_news_annotations translations --input /runtime/fact-references-20.json --predictions /runtime/translations.json --output /runtime/translation-score.json
```

实体predictions是数组，每篇含sample_id/source_sha/reference_sha/contract_version/phase/status/mentions。
phase为initial/repaired；mentions用block_id/start/end/text/type，每次提及独立统计。
缺失样本not_run；超时、协议错误、超限均保留全集分母。canonical与预声明acceptable边界分别计分。
同名多片段保留name_groups，不将不连续片段拼成虚构连续跨度。

翻译predictions每篇含sample_id/status/target/review；target包含title、summary及有序blocks，可选body必须与blocks拼接相等。摘要也进入证据映射和target_sha。
review绑定sample/source/reference/target SHA，包含独立reviewer种类和标识、coverage=full_article、
逐fact id/verdict/reason/target_evidence，以及additional_claims/omissions/fluency的verdict和reason。
支持与矛盾均需可定位目标证据；缺失或不确定不能通过。程序只验证证据结构与绑定，
无法认证提供者身份或裁决语义真伪；external_model审阅不冒充人工。
实体质量独立使用entities报告，结构完整不等于实体、事实或中文自然度通过。

当前空预测基线为实体120篇not_run、译文20篇not_run，用于验证失败分母，不能宣传为模型成绩。
