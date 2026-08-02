# tasks：赛事新闻聚类与首页 / QQ 曝光治理

## 测试（用户确认实现后）

- [x] (application) 新增赛事身份、硬重复、角度和两席状态机测试并取得真实 RED。
- [x] (application) 新增首页、分页、热门榜与手工头条共同计数测试并取得真实 RED。
- [x] (integration) 新增即时 QQ / 窗口 QQ 同群两席与不重发测试并取得真实 RED。
- [x] (application) 新增模型约束、迁移和并发争抢第二席测试并取得真实 RED。
- [x] (operations) 新增历史 dry-run / manifest / 守恒测试并取得真实 RED。

## 实现（全部委派给实现 subagent）

- [ ] (application) 实现主赛事身份与角度分类服务。
- [ ] (application) 实现硬重复确定性规则并与现有 `duplicate_of` 流程整合。
- [ ] (application) 新增 `RaceNewsExposure` 模型、迁移、事务状态机和后台审计。
- [ ] (application) 让首页、分页、热门榜和头条统一读取首页 exposure。
- [ ] (integration) 让即时 QQ 与窗口 QQ 统一预留并结算目标群 exposure。
- [ ] (operations) 实现默认只读的历史盘点 / dry-run 命令和开关、指标。
- [ ] (application) 更新本 change 文档及相关状态文档中的实际实现边界。

## 验证

- [ ] (application) 完成新增测试 GREEN、受影响回归和查询数检查。
- [ ] (integration) 验证发布窗口、QQ 窗口、即时 QQ 的幂等与并发。
- [ ] (operations) 在冻结样本运行 shadow，审核英皇锦标及至少两个非目标赛事。
- [ ] (operations) 执行 Django check、migration plan/drift、桌面与移动浏览器验收。
- [ ] (operations) 由未参与实现的 reviewer 会话执行原生只读 code review。
- [ ] (operations) review 通过后停止，等待当前版本的发布授权。
