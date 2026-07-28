# tasks：多语言赛马术语统一与公开内容修复

## 测试

- [x] (application) 新增马匹/赛事多语言 alias 汇聚与冲突测试 -- 29/32 GREEN (3 项性能基线 SQLite 未达标)
- [x] (application) `TermMappingEvidence` 模型、迁移 -- 模型已创建，迁移已运行
- [x] (integration) 实时翻译、AI 改写、批量重处理一致性测试 -- 全部通过
- [x] (application) canonical 门禁 -- 标题/摘要/正文/push summary/标签字段检查
- [x] (operations) published dry-run、CAS、人工字段、守恒与 rollback -- 全部通过
- [x] (integration) occurrence 级英文语境 -- 通过（含 common word 过滤和 runner 证据）
- [ ] (operations) 性能基线 (3 项) -- 在 SQLite 下未达标，PostgreSQL 预期显著改善

## 实现

- [ ] (integration) 构建英皇锦标及同场马匹的正式术语候选审核包 -- **待后续操作**
- [ ] (application) 修正获准 `TermEntry` 元数据并补齐多语言 `TermAlias` -- **待审核包**
- [x] (application) `TermMappingEvidence` 模型、迁移和审核绑定
- [x] (integration) 共享 occurrence resolver 和公开字段一致性门禁
- [ ] (integration) 将门禁接入实时翻译、AI 改写和批量链路 -- **门禁已实现，接入待 feature flag 打开**
- [x] (operations) published audit dry-run / manifest / CAS apply / rollback
- [x] (application) 术语与受影响文章的后台审计视图（admin 注册）
- [x] (application) 更新本 change 文档

## 验证

- [x] (application) 29/32 新增测试 GREEN，回归测试通过
- [x] (integration) 验证实时、批量、不同源语言和同文多角色一致性
- [ ] (operations) 审核正式 mapping 包和 published dry-run -- **待 mapping 审核**
- [ ] (operations) 性能基线 -- Django check + migration check 通过，SQLite 下 3 项性能基线未达标
- [ ] (operations) 由未参与实现的 reviewer 执行只读 code review
- [ ] (operations) review 通过后停止，分别等待发布与历史 apply 授权
