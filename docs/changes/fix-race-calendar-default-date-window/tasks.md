# 赛事日历默认比赛日窗口任务

## 测试

- [ ] (application) 测试 subagent 新增默认锚点、平衡窗口、空数据、非连续日期、跨月/跨年、
  上海时区和公开资格用例。
- [ ] (application) 测试 subagent 新增显式 cursor、region、grade、tab、when、year、q
  与空筛选结果回归。
- [ ] (application) 运行目标测试并保存由缺失新行为导致的真实 RED。
- [ ] (application) 新增查询数与无 N+1 断言，记录修改前 SQL 基线。

## 实现

- [ ] (application) 新增可测试的比赛日平衡纯函数和有界 distinct date 查询服务。
- [ ] (application) 拆分日历公开基础 queryset，确保日期窗口和赛事列表资格一致。
- [ ] (application) 仅在默认模式应用最多 11 个实际比赛日窗口，并以代表赛事优先策略保持
  40 卡上限且覆盖每个日期。
- [ ] (application) 贯穿同一个 `shanghai_today`，给默认锚点增加语义标记与水平居中。
- [ ] (application) 保留显式 cursor、year、q 语义及现有响应式/徽标视觉合同。

## 验证

- [ ] (application) 运行日期窗口聚焦测试及日历 view/template 回归。
- [ ] (application) 运行筛选、搜索、时区、缓存和查询预算测试。
- [ ] (application) 运行超过 40 场的 11 日高基数覆盖测试。
- [ ] (application) 运行 Django check、迁移漂移检查和 `git diff --check`。
- [ ] (application) 在 1440px、390px，必要时 320px 做真实浏览器验收。
- [ ] (operations) 确认无模型、迁移、配置、Celery、生产数据或首页范围外改动。

## Review

- [ ] (application) 未参与实现的独立 reviewer 以 Codex 原生只读 `/review` 审核完整未提交
  范围，保存前后 fingerprint 与结论。
- [ ] (application) 若有 actionable finding，在同一 reviewer 会话完成限定复审直至清零。
- [ ] (operations) 冻结最新成功 review 的 scope、approved parent 和 content hash，停止等待
  当前 fingerprint 的发布授权。

## 发布

- [ ] (operations) 仅在最新成功代码 review 后取得用户针对当前 fingerprint 的明确发布授权。
- [ ] (operations) 授权后按 fingerprint transition 完成 commit、push、PR/merge 与部署。
- [ ] (operations) 验证默认/显式入口、1440px/390px、healthz、日志及零业务数据写入。
- [ ] (operations) 按 evidence-only 规则回写真实发布结果并由同一代码 reviewer 审核。
