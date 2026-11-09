# 技术设计

沿用现有 Django 候选、pre-race lease、共享快照、host budget、多来源身份和 result writer，无模型迁移。France Galop 报名与预计名单写候选；比赛临近时 Geny 完整编号卡接管，再由既有调度更新正式卡及结果。代码按日期与赛事身份发现来源，不硬编码 2026 或验收名单。

## 来源与字段

- 官方名单以 Après Engagements、Second-Engagements、Partants probables 判阶段。表头 Partants 不足以认定正式卡；报名 N° 不写正式马号，00h00 保持未知。
- Geny 完整卡与结果按 race ID、日期、号码及马名核对；显式 NP 才补为非出走。未知状态、截断、身份漂移拒绝写入。TRA 仅保存交叉核验证据，单一完整来源足够。
- 保留原始 kg、分配及调整后负重、Genybet 报价平台与采集时间，差距明确为距前马。报名没有骑师、闸位时不填造。
- 采集失败保留上次有效名单；相同早期名单不重复生成候选。同价报价的新观测保留独立快照；法国元数据摘要纳入规范化卡表并与来源元数据互校，避免主字段同值去重丢失新采集时间/调整后负重。马号使用number:槽位身份，换马必须通过既有名称或人工映射校验。

## 数据包

`apply_france_release` 绑定 manifest、策略及原始可见文档归档 SHA；只回放本地证据，不联网。目录补档、来源名称、产品映射和59场结果在同一事务内完成；默认 dry-run 全部回滚，apply 写收据，重复执行返回原收据。

80个唯一目标：现有71条减凯旋门重复1条，加10场 AQPS。保留两条数据库记录及旧URL，产品映射4→784；不删除赛事或系列。AQPS 单列类别，等级存 G1/G2/G3，完整长参赛条件存来源元数据，不截断到短字段。7场历史AQPS依据Geny原表，3场未来依据France Galop详情，不能称全部来自普通平地Pattern PDF。

执行前锁定事件与系列并核对基线；已有结果、名单、人工锁、暂停、写权或来源绑定漂移即失败。生产执行须在既有单一发布协调窗口内停写；不把事务替代发布锁。

## 浏览器与认证

独立容器只访问 France Galop/Geny 的赛事路径，固定 Europe/Paris，限时限量，关闭下载；应用仍持有配额与lease。France Galop会话由独立正常登录工具生成外部0600文件，仅保留法国域会话，经只读挂载使用。失效返回错误，不自动读取个人Chrome配置或导出身份提供方Cookie。

`france_archive` 将已采集的可见DOM文档转成解析器输入，SHA绑定原文档。这是可见内容回放而非原网页HTML；未记录时区的历史采集不反推开赛时刻。


## 2026-11-10 已确认的旧登记交接修订

用户已确认 772/785/790/791/828/830/833/839/840/841 十场显式交接。固定 manifest 保存 owner、旧登记、跟踪、检查点及 lifecycle 控制快照；只接受当前 `historical + retired` 或 `data_sync + enrolled` 的 v1 组合，无人工暂停、活动 claim 或 v2 binding。已批准范围内允许为新 Geny 来源做强身份匹配和准入后，原位转换 v2、递增 owner/enrollment generation，保留旧登记主键、旧来源、不可变修订及 before/after 审计。普通自动发现入口保持拒绝旧归属，不自动扩大接管。

France release 在既有单事务中消费显式 handoff；十场交接、法国目录/511行结果及49日港换绑任一失败全部回滚。默认无handoff时仍拒绝旧登记，收据重放不得再次递增代数或改写历史。补含真实旧控制状态的PostgreSQL回归，覆盖dry-run零留存、末项失败、apply/replay、状态/代数漂移和人工锁拒绝。修改源码与精确数据包后重新冻结镜像和包，独立review按根AGENTS.md交付。

交接快照直接嵌入法国数据 manifest 的 `legacy_handoffs`，与目录和赛果共同由 manifest SHA 绑定；外层 activation 再绑定该文件 SHA。无需增加第二个独立授权文件或先行事务。普通 `attach_multisource_observation` 默认参数为空，仅此显式发布路径传入控制快照。
