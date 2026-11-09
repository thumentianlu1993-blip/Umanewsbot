# 实施任务

- [x] (integration) 固化59历史场与21未来场真实样本，取得字段/解析及接管RED。
- [x] (integration) 实现法国解析、传输、身份发现、赛前调度和正式写入。
- [x] (application) 实现公斤、报价来源/时间、距前马与AQPS展示。
- [x] (operations) 制作80目标、10补档、59场511行及凯旋门4→784映射草案；整包dry-run/apply/重放测试通过。
- [x] (integration) 完成法国/共享字段PostgreSQL诊断回归与Linux浏览器实取；固定树CI待冻结后执行。
- [x] (operations) 完成France Galop独立会话登录、Linux服务内验证；无会话拒绝访问，失败保留候选。实际生产安装/换会话验证在发布包内执行。
- [ ] (operations) 独立只读review、返修复验、Draft PR和精确发布包。
- [ ] (integration) 上线后在真实节点验证正式卡与赛后自然更新。
