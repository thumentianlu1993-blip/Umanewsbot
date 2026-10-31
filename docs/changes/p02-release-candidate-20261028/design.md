# 依赖与升级设计

## 依赖闭包

P02 补丁可在 main 直接应用，来源适配、来源身份、准入和基础赛果模型均已在 main。保留 P02 涉及的 services、models、settings、tasks、views、模板、fixtures 和测试。交接分支的文章实体绑定、术语、马匹履历、内容审核、公开探针大模板及 0082 不随本候选引入。没有复制那批历史提交，也没有改旧 PR 的比较基线来伪装隔离。

## 两段上线

第一段只做关闭态 schema/代码升级：P02 write/delivery 均 false、cohort 为空、不得启动新网络采集。第二段在来源与目标/容量证据完整后，独立固定 cohort、策略摘要、公开 origin、持久容量文件及 SHA，完成旧/新 writer 切换。旧任务与新任务不能同时取得同 cohort 的写权；队列不清空，迟到任务必须按有效配置和版本被拒绝。

## 精确迁移图

0079 → 0080_translation_retry_budget → 0081_managed_readonly_steps → 0083_race_lifecycle_publication → 0084_race_lifecycle_evidence_guards → 0085_race_observation_acquisition → 0086_race_lifecycle_observation_watermarks。

0080/0081 是 main 已存在的 schema 前置，不开启其业务能力。0083 新表及外键/字段涉及既有赛事表；0084 安装只保护新证据表的触发器；0085 对既有 observation 表增加 acquisition_key 并替换唯一约束；0086 增加观测水位。0085 可能扫描存量、获取强锁，不能以“主要是新表”推定零停机。

## 发布合同

新增独立 P02 代际执行器及合同，不改写 release_0079 的固定摘要/叶，不复用旧 completed 凭据，不运行裸 migrate 绕过保护。正式执行器必须绑定候选 commit/image、生产数据库身份、完整 migration 文件摘要、精确 recorder/catalog、配置摘要、备份及恢复演练摘要、关闭态 handoff 和 intent。目标叶仅 0086；起始只接受精确 0079，续跑只接受与同一 intent 绑定的已提交迁移前缀。

初始 intent 在停写前固定预期身份与唯一备份目录；备份完成后另写不可变 backup receipt（反向绑定 intent SHA），closed handoff 再绑定两者。三者联合形成 DDL 准入，不原地修改 intent。

完成态同时检查 recorder、真实表/字段/索引/约束/触发器和 static 产物；只检查 showmigrations 不足。任一身份变化或 unexpected leaf/recorder 均 fail closed。

本项确定合同和流程；执行器实现及镜像故障注入列入后续发布演练工程任务，未声称现有旧脚本能执行本升级。
