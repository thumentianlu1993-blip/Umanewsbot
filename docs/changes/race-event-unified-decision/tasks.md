# 实施拆分（全部待授权后实施）

当前任务只交付设计；下列复选框不代表已开始代码工作。人工确认边界以根 AGENTS.md 为准。

## 2A：历史公开依据兼容

- [ ] (application) 测试：D13–D16/D26 与列表/详情同判定先取得 RED；撤销、摘要缺失和错误 publication 引用均拒绝。
- [ ] (integration) 实现：固定 11 场 inventory 与只读证据核验；先报告可证/缺证，再生成绑定原版本的迁移 manifest；不新增赛果/抓取。
- [ ] (application) 实现：追加不可变 RacePublicationAuthorityProof 与 v1 兼容 validator，保留既有 v2 publication 逻辑、撤销与公开控制。
- [ ] (operations) 验证：先解决/独立验证当前完整恢复缺陷，完成新 schema 的受保护发布/中断恢复合同；真实数据副本演练；固定样本逐场公开判定自然验收。

## 2B：纯决策与影子诊断

- [ ] (application) 测试：D01/D02/D05–D07/D17/D22–D26 的冻结输入/输出及无副作用合同取得 RED。
- [ ] (application) 实现：DTO、loader、纯 decision、规则版本和差异分类；coverage/admin 消费统一诊断，保留估计与真实排程区别。
- [ ] (integration) 实现：把现有时间/频率/能力窗口映射成初始 policy；全部真实来源仍由现有执行器运行，影子只比较。
- [ ] (operations) 验证：同 as_of 全目标与近期 cohort 对照；预算、查询数、artifact 上限；至少一个赛日前后窗口；不凭差异总数为零掩盖规则本来应该改变的场景。

## 2C：状态证据、能力解析与授权换代

- [ ] (integration) 测试：D03/D04/D08–D12/D16/D25 及现有原子绑定/claim 合同取得 RED。
- [ ] (integration) 实现：adapter 独立身份/能力解析、合法选源；统一地区时区能力表；受影响登记 inventory 与受审换绑闭环。
- [ ] (application) 实现：cohort 内唯一状态 writer 接入新事实决策；统一日历/详情的预计与事实语义；旧时钟入口不再对同 cohort 写状态。
- [ ] (application) 验证：完整 runner、参考/正式/更正、延期/取消、日期精度和历史兼容；七场已恢复赛事不回退。

## 2D：可靠派发与小范围切换

- [ ] (operations) 测试：D18–D21/D27/D28，覆盖队列拥堵、断连、crash 和发布恢复，全部隔离环境执行。
- [ ] (integration) 实现：与原 claim 同事务的派发 outbox/收据及有界重试、清理；保留原 owner/lease/generation CAS。
- [ ] (operations) 实现：race_control 资源预算和路由；扩充新 schema/新服务的精确部署、排空、恢复合同；独立主机心跳探针。
- [ ] (operations) 验证：先小 cohort、单写入口；自然两周期与来源赛前/赛后/更正；回退演练；确认无活跃依赖后才退役旧入口。

## 相邻但独立的工作

- [ ] (application) 凯旋门 4/784 等重复赛事按强身份/manifest 做定向 canonical 修复，保留旧 URL 和关联；不直接全表按名称去重。
- [ ] (integration) 持续赛历刷新从“产生 diff”推进到候选可见、可处理、可对账；是否自动 apply 另列产品/生产范围。
- [ ] (operations) 新闻/术语重复键造成的完整备份恢复失败，单独诊断并修复；不会在本设计任务中操作生产数据。
