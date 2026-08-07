# tasks：2026 赛事系列身份归并与双卡片治理

## 0. Pre-declared hypotheses

- H1：正式快照 2026 target 分区严格守恒；任何漏行/重复为 BLOCKER。
- H2：探索基线为 `1085 = 684 + 226 + 11 + 162 + 2`；正式导出只要任一计数变化，必须先生成
  drift 报告并由用户重新确认，不能自动沿用 401 行范围。
- H3：唯一名称匹配不等于批准；首批 action 数必须等于用户定稿中
  `merge_and_link + keep_independent + ignore_false_match` 的可执行行数，defer/不兼容行为 0。
- H4：正向 apply 前后 event 详情哈希、总量、URL、中文名和公开状态完全守恒；任一变化为 BLOCKER。
- H5：首批每个 source/destination/target/event 在正向动作中各出现一次，目标系列不存在同年 event；
  不满足则不生成 manifest。

## 1. 方案门禁

- [x] (application) 完成首次方案审核；修复全部 findings，并在同一 reviewer 会话限定复审通过

## 2. 测试先行

- [x] (application) 为分类守恒、跨地区排除、别名候选、同名歧义和无匹配写 RED 测试
- [x] (application) 为依赖检查、批内身份互斥和 `do_not_merge` 写 RED 测试
- [x] (application) 为 JSON/CSV/XLSX 一致性、可编辑列、防篡改和文件 SHA 写 RED 测试
- [x] (application) 为原始 manifest 信任根、跨包错配和导出字段/敏感键白名单写 RED 测试
- [x] (application) 为 reviewed workbook → 既有 decisions/空 repairs 转换写 RED 测试
- [x] (integration) 为既有 prepare/apply/verify/rollback 集成与详情守恒补 RED/回归测试
- [x] (integration) 为 PostgreSQL repeatable-read、并发锁和同年唯一性补专项 RED 测试

## 3. 实现

- [x] (application) 实现 `stable.services.race_series_identity_2026_review` 的批量快照、分类和依赖索引
- [x] (application) 实现穷尽分类、异常清单、canonical snapshot/review/manifest JSON 与平面 CSV
- [x] (application) 使用现有 openpyxl 生成六 sheet 审核工作簿（审核说明、唯一名称匹配、同名多候选、
  无名称匹配、未举办、异常清单）并实现安全回读
- [x] (application) 实现原始 manifest 信任根校验与 reviewed workbook 到既有 decisions JSON 的严格适配；
  只有唯一匹配表可产生动作，不新增写库路径
- [x] (application) 实现 `review_2026_race_series_identities` 管理命令的导出和 build-decisions 模式
- [x] (integration) 接入既有 `reconcile_race_series_identity_review` prepare，保持 field repairs 为空

## 4. 本地验证

- [x] (application) 运行新增专项与 `stable.test_race_series_identity_review` SQLite 回归
- [x] (integration) 在一次性 PostgreSQL 16 运行快照、锁、apply/verify/rollback 与并发专项
- [x] (integration) 运行 Django check、migration drift、compile、diff 和工作簿结构/视觉检查
- [x] (operations) 验证三份 Compose config；确认无迁移、无新配置、无自动调度入口

## 5. 代码门禁

- [x] (application) 完成独立原生代码 review；前后 fingerprint 一致、内层只读、actionable 清零

## 6. 生产只读审核包

- [ ] (operations) 部署代码但不运行数据写入；核对生产 HEAD、镜像、命令 help、healthz
- [ ] (integration) 在生产 repeatable-read 只读导出新快照；记录与探索基线的 drift
- [ ] (integration) 按字段白名单复制脱敏审核包到本地，校验独立记录的 manifest SHA 和全部文件 SHA，
  完成工作簿结构与视觉 QA
- [ ] (operations) 用户审核完整未关联总账，优先定稿唯一名称匹配表
- [ ] (integration) 从定稿工作簿生成 decisions，运行既有 prepare 与 prepared verifier

## 7. 数据发布门禁

- [ ] (application) 对精确 decisions/manifest 和直接触及路径完成同一代码 reviewer 限定复审
- [ ] (operations) 执行 custom-format 生产备份、SHA-256 和 `pg_restore -l`
- [ ] (operations) 以首批单一 manifest 运行既有单事务 commit；立即运行 independent verifier
- [ ] (integration) 核对全量/逐事件守恒；对每个实际含正向动作的地区至少抽查 2 个系列（不足则全量），
  并检查五地区赛历入口
- [ ] (operations) 失败则按 rollback ledger 或数据库备份执行另行授权的回滚

## 8. 收尾

- [ ] (operations) evidence-only 更新 current_state、project_status、deploy_runbook 和 release_report
- [ ] (operations) 记录未处理的特殊/歧义/无匹配行，不把它们记为已解决
- [ ] (operations) evidence review 通过后提交文档；不为记录 evidence commit SHA 递归更新

## 9. 非阻塞后续建议

- [ ] (application) 扩充公开 URL 敏感 query 参数拒绝词表，覆盖 `password/passwd` 等凭据命名
- [ ] (application) 让原始审核包校验与工作簿解析复用同一次安全读取的 bytes，消除校验后二次读取窗口
- [ ] (application) 对导出的 XLSX/CSV 外部字符串做公式注入转义或拒绝，覆盖 `= / + / - / @` 前缀
- [ ] (application) 若要用探索基线自动判断是否需重新确认，增加 target/candidate identity-set digest，
  防止候选集合等量替换仅靠计数无法发现
