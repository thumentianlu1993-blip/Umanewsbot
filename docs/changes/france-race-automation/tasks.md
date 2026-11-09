# 实施任务

- [x] (integration) 固化59历史场与21未来场真实样本，取得字段/解析及接管RED。
- [x] (integration) 实现法国解析、传输、身份发现、赛前调度和正式写入。
- [x] (application) 实现公斤、报价来源/时间、距前马与AQPS展示。
- [x] (operations) 制作80目标、10补档、59场511行及凯旋门4→784映射草案；整包dry-run/apply/重放测试通过。
- [x] (integration) 完成法国/共享字段PostgreSQL诊断回归与Linux浏览器实取；固定树CI待冻结后执行。
- [x] (operations) 完成France Galop独立会话登录、Linux服务内验证；无会话拒绝访问，失败保留候选。实际生产安装/换会话验证在发布包内执行。
- [x] (operations) 独立只读review、返修复验、PR #292 合并和精确发布包；修正镜像 Web 恢复已验证。
- [x] (integration) 10 场旧登记显式交接实现、真实控制状态的整包事务回归及独立代码审核。
- [x] (operations) 固定提交CI、新候选镜像、后继发布包审核与按根AGENTS交付；PR #293已合并。
- [x] (integration) 重新完成整包数据激活、80公开页/511赛果及49日港换绑验收。
- [x] (operations) 修正并交付后台就绪等待后继包，生产双worker真实pong通过。
- [x] (operations) 修正Compose环境及镜像内release身份，交付仅元数据修正镜像并完成Web/后台恢复与驻留核验。
- [x] (operations) 清理本任务重复传输归档并应用4GiB raw空闲阈值，保留高水位与单文件限制，排空后恢复服务并核验。
- [ ] (integration) 交付Geny同URL主页面重载修复，浏览器合同与两层请求预算一致。
- [ ] (integration) 完成21未来目标自然调度验收；当前20/21，795等待修复后的自然重试。
- [ ] (integration) 上线后在真实节点验证正式卡与赛后自然更新。
