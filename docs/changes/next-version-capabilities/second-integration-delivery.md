# PR236 合并交付确认材料

2026-10-04，Asia/Shanghai。固定 [PR #236](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/236) head `06b01aea9041eacb3deae9f46968eb06fd459cb6`，base `907f8de699b31a6fcc80acc78e9ba070aadc4f28`。Draft/open，未合并或发布。人工确认统一依根 [AGENTS.md](../../../AGENTS.md) G2。

## 本次代码范围

本PR完整包含首批PR235的F01共享内容合同、U01等级筛选/展示与F02只读导出/转存基础；再加入Q01 QQ发送关闭与网页发布解耦、Q02 QQ入口/专属运行依赖退出、H01目标集合与只读计数、F02隔离PG验证接通、U02七天首页和公开列表来源返回。当前相对main为153个文件，其中包含规划与历史证据文档。

没有新增数据库迁移。代码包含settings与两个生产Compose文件的QQ专属任务/服务声明变更；仅合并不会把这些声明应用到生产，也不执行现有服务退出。A009/A010新helper、B007两负例、C011快照分段以及当前协调过程文档不属于06b候选。

## 固定验证

- 原独立R完成各切片、组合映射和最小测试修复复审；最终06b控制绑定为 `055e193225df95ee58b9b972f64467863cbc5e70`。正式19个controls固定，测试未删减。
- 正常pull_request CI [37137528485](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/37137528485)，北京时间01:04:36完成。full 6378项、46批、0 failure、0 error、10个既定skip；tests与test-plan-gate均成功，所有native batch lifecycle complete。
- 候选目录外main907原verifier SHA256 `7e58cb72042dd76ef064f9121589f1a06655aad6befc1278d389ffc8799c7d7d`，以Python isolated模式独立核验实际CI镜像、重新收集ID/分批、source/control、strict+admins与实时base/head；真实退出0、正式收据verified，结束后本地容器为空。
- 受验merge `0932c240f66eff98dbecafcf02e1994982ba6c6f`，tree `d23998ef537cf4ff7098a4aae0d9efa7987d115d`，plan digest `28935595a67f17499609b3dad568a15dc914573748a00239dd83a5498befebc2`。
- 正式收据 `/Users/mentianlu/.codex/runtime/second-integration-evidence/delivery-06b01aea.json`，SHA256 `47f2340046d82a0de855b6bb8dad451f5b0748c8e0a4d402e47b81123630a894`。
- 实际CI image `sha256:af6c1852ff814a98798637925fab7f55f605cbfdce51751b371a0039957ac983`。固定image ZIP artifact11279688052、396181232字节、官方SHA `b6cf6b79b84c4e807d0949f24bf9f6c905a002f6449665b6a3efc8fac3c23641`，认证metadata前后、完整ZIP及exact shim字节经root和原R `345b13a39fb78c08ca5e0b592b381ae871485c50` 核对。缓存只替换运输，不改变原verifier检查或伪造结果。

旧6378全量中的唯一失败及其单项修复记录保留；本次通过来自06b新合并测试树的完整独立结果。此前bdfb的20个真实HTTP请求/8条journey与实际PG补验是额外范围证据，不替代本次full，也不等于视觉或生产验收。

## 建议与执行边界

建议只合并本PR236，暂不发布。它已包含PR235，因此不必先单独合并PR235改变base；原PR235仅合并问题由本次综合候选确认替代，未答不算批准。

获准后先重核06b head、实时main/base与strict必需检查，固定对象变化按根AGENTS要求处理。通过远端合并，不切换共享main或清理其它工作树；合并后核远端main、tree和PR状态并回写。结果未知先查真实状态，不能重复副作用。

本次只合并的范围为：数据库迁移0，生产配置/feature flag应用0，生产构建/重启0，生产数据动作0，外部抓取/付费调用/消息发送0。生产继续现有版本。若合并后的代码需撤回，按实际合并commit准备revert PR并走正常确认；本材料不授权force-push或生产回滚。

“合并并发布”的精确包尚未就绪：O02完整引用图与整库恢复仍未完成，F02新增真实样本仍为0。若用户选择等待发布包，将先补技术条件并准备固定服务/配置/验证/回滚清单，再按G2确认，不能用此文预批准任意未来发布。
