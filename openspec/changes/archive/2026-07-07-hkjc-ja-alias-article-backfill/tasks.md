## 1. 术语概念合并实现

- [x] 1.1 (integration) 实现 HKJC horse 日语 alias 概念合并 plan service，输出 candidate、skipped、summary artifact 数据结构
- [x] 1.2 (integration) 实现概念合并 apply service，重新校验当前 term/alias 状态和其它 active owner 占用，写入目标 alias，停用冗余日语主术语并记录 notes
- [x] 1.3 (application) 增加概念合并 management command，支持 dry-run 默认模式、从已审核 plan artifact 显式 `--apply`、term/type/source 过滤、artifact 输出目录和 summary stdout

## 2. 已发布文章术语回填实现

- [x] 2.1 (integration) 实现文章术语回填 plan service，按 term、文章 ID、发布时间范围、来源语言、limit 过滤并生成字段级 diff，JSON artifact 保留完整 before/after 字段值
- [x] 2.2 (integration) 实现文章术语回填 apply service，复用现有术语替换语义，默认跳过 `manually_edited_fields` 发布字段并保持幂等
- [x] 2.3 (application) 增加文章术语回填 management command，支持 dry-run 默认模式、从已审核 diff artifact 或显式过滤范围执行 `--apply`、从 merge artifact 读取 term 范围和独立过滤执行
- [x] 2.4 (application) 确保回填不会修改文章发布状态、审核状态、workflow 状态或 QQ 推送状态

## 3. 自动化测试

- [x] 3.1 (application) 增加概念合并测试，覆盖 dry-run 不写库、apply 写 alias、停用源术语、其它 active owner 占用跳过、冲突跳过和重复执行幂等
- [x] 3.2 (application) 增加文章回填测试，覆盖字段级 diff、完整 before/after artifact、apply 替换、无命中不改、手工编辑字段跳过和 summary 计数
- [x] 3.3 (application) 增加命令层测试或 smoke 测试，覆盖 dry-run 默认安全行为、`--apply` 显式写入和 artifact 文件生成
- [x] 3.4 (application) 增加无审核 artifact 或显式过滤范围时拒绝文章回填 apply 的回归测试

## 4. 文档与运维

- [x] 4.1 (operations) 更新 `docs/current_state.md`，记录该变更的目标、范围、当前实施状态和生产执行边界
- [x] 4.2 (operations) 更新 `docs/deploy_runbook.md`，记录生产 dry-run、复核、apply、验收和回滚步骤
- [x] 4.3 (operations) 更新 `docs/project_status.md`，同步项目级状态摘要

## 5. 验证与生产准备

- [x] 5.1 (application) 运行 `DB_ENGINE=sqlite python manage.py check`
- [x] 5.2 (application) 运行 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable`
- [x] 5.3 (operations) 在生产执行前准备数据库备份、记录当前 commit/container/healthz，并先跑 dry-run artifact 供人工复核
- [x] 5.4 (operations) 生产 apply 后抽查术语后台搜索、受影响文章页面、summary 计数和 `/healthz/`，并将命令与 artifact 路径写回文档
