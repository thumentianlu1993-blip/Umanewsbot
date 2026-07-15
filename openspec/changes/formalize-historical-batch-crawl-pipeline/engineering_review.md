# 工程评审

Review mode: Full（profile: feature）

结论：**APPROVED**。proposal、design、两份 delta spec 与 tasks 已形成完整、可测试、可回滚的实现边界；没有剩余架构、数据一致性、性能或生产安全阻断项。

## 2026-07-15 年度赛历入口补充评审

Review mode: Full（profile: feature）

结论：**APPROVED**。batch006 实跑前发现原 typed recipes 只能消费已经带日期的 events/provider 输入，无法由年度官方目录正式生成这些输入。补充方案复用现有 cache、地区 parser/matcher、source-cache manifest 和 runner stage，不引入新网络客户端、模型、迁移或第三方依赖。

1. **网络与解析不得混在同一工具**：已锁定 request/catalog -> network cache -> offline parse 三段；parse stage 明确无网络，且只消费已完成 cache checkpoint 的冻结副本。
2. **部分来源失败不能既阻断全批又被静默忽略**：cache 默认仍失败；只有显式 partial 且每个请求都有终态时才继续，parse 必须把受影响 target 转为带 ledger/source identity 的 gap。
3. **不能继续手工生成逐 target provider JSONL**：新增纯 tracked catalog expander，要求 selection 全覆盖并检查地区、年份、adapter、parser、HTTPS 与 host allowlist；它在 plan 前运行，不扩大 runner 白名单。
4. **PDF/跨年/单位规则必须确定**：复用现有 parser/matcher，catalog 显式选择 parser；BHA 保留英制、France Galop/HKJC/JRA 保留公制，香港 edition year 与 actual local date 分离。
5. **缓存文件不能只信 manifest 文本**：解析器同时交叉核对 ledger、manifest、cache root 和磁盘 path/size/SHA/source URL；身份漂移 fail closed，不降级成 gap。
6. **plan builder 不能把整份 selection 当作单年 scope**：新 typed policy 要求地区+年份并按两者过滤实际 scope，目录输入逐文件复制绑定；缺少任一选项或 scope 不相等即拒绝。
7. **现有 crawl phase 固定拥有网络，不能承载离线解析**：复用 runner 已有 `verify` phase，不新增模型/迁移/相位。builder 对旧 descriptor 缺省 crawl；新 verify descriptor 必须无 `resource_limits`、shard request budget 为 0，并由 runner 既有 phase 权限校验固定为无网络无写入。
8. **年度目录不能冒充逐场赛果来源**：parser stage 的 complete 以可信日期 event row 为准；JRA/TOBA 有唯一直接结果链接时才产 provider row，BHA/France Galop/HKJC 先交给既有详情 preparer，真实赛果 URL 到位后才进入 date merger。
9. **cache manifest 原始绝对 root 在跨 stage 复制后会变化**：原 root 仅保留 provenance；parser 必须使用 plan 已声明、成员逐 SHA 绑定的复制根解析相对 path，并同时核对 manifest/ledger/source URL，不能因路径搬迁放弃文件身份校验。
10. **typed recipe 的 output_dir 会被现有 runner 当成普通文件验收**：plan 新增向后兼容的 `output_directories`；builder 按 policy 输出类型生成声明，runner 对非空目录拒绝 symlink/特殊文件并记录全部成员相对路径、size、SHA，resume 复核完整成员集合。

新增 `TC-CALENDAR-*` 覆盖请求展开、partial cache、五类解析器、单位/跨年、gap 分母、原子发布、性能与 plan/runner 边界。必须先落测试，再实现，并在部署新 revision 后继续 batch006。

## 2026-07-15 年度赛历实现复审收口

Review mode: Full（profile: feature）

结论：**APPROVED**。新增年度赛历实现完成 4 轮独立 review，最后一轮没有 actionable finding。已修复：全量 ledger 被错误限制为单 shard、共享 URL 跨年份引用不完整、跨 step 输出路径可覆盖既有 checkpoint、selection/catalog 及 ledger/fragment 的布尔或分数身份被宽松转换、普通文件输出可被同内容 symlink 替换，以及法国障碍汇总摘要覆盖详细赛程日期的问题。

- 正式执行改为 11 个地区×届次年 scope，每片不超过 250 targets；request/cache 可复用全量 URL ledger，parse 始终按明确地区+年份收口。
- 法国 2023、2024 真实官方缓存 smoke 分别得到 `120/120`、`130/130`，`issues=0`；障碍汇总表只补充详细赛程未覆盖目标。
- 完整 stable `1524/1524` 通过（11 skip），年度赛历/来源专项 `118/118`（1 skip）、runner `70/70`、性能 `3/3`、OpenSpec `30/30`，Django check、migration drift、Python compile 和 diff 检查通过。

## 范围与复用

- 继续使用现有 approved inventory/selection、historical runner、请求预算、source cache、地区详情 preparer、日期/来源 apply 和最终 candidate importer。
- 最小新增面为 plan builder、通用 fragment merger、阶段 verifier，以及 historical runner 对正式 plan 资源身份的校验；不新增模型、迁移、第三方依赖、Celery task 或公开页面。
- `tmp/build_batch005_*.py` 只作为行为参考和历史证据，不进入镜像白名单，不复制到新 artifact。

## Round 1

1. **shard 声明没有约束工具实际读取的目标集合**：仅在 descriptor 列 target ID，仍可能让 events CSV 或 selection input 多抓/漏抓。已改为 typed recipe + per-tool target-binding policy，禁止任意 argv 和无 policy 工具。
2. **plan 请求预算未与 runner phase env 绑定**：声明值可能与实际 settings 不同。已新增正式 plan `resource_limits`，runner 在创建/恢复 run 和取双锁前逐项比较。
3. **gap 可能掩盖完全遗漏**：若 merger 自动把无输入目标转 gap，accounted 看似完整但无证据。已要求 gap 必须有 selection/target SHA、原因、来源或失败身份和时间；完全缺失直接失败。
4. **verifier 只靠代码约定只读**：业务角色仍有写权限。已要求 PostgreSQL `transaction.atomic()` 内首先执行 `SET TRANSACTION READ ONLY`，并加入意外写入失败测试。

## Round 2

1. **多个 shard 共用 artifact 根会共用 250 次请求账本**：已改为每 shard 独立宿主目录、挂载根、账本、cache manifest、state 和 lock；父 stage 只保存身份与全量覆盖汇总。
2. **逐文件 rename 仍会发布半套 artifact**：已改为同级临时目录完整构建、文件/目录 fsync、校验后一次目录 rename，目标目录预先必须不存在。
3. **缺少规模性能合同**：已锁定 1250 targets、10 shards、每场 20 runners/results；纯 artifact 编排不超过 30 秒/256 MiB，数据库 verifier 不超过 20 条查询。

## 验收门禁

- 实现前先完成 `test_cases.md` 并写入失败回归。
- 完成后运行聚焦测试、完整 stable、Django check、迁移漂移、OpenSpec strict/all、diff/shell 检查和性能合同。
- 代码必须反复 review、修复、重新 review，直到一次 review 无 actionable finding。
- 生产部署保持历史公开、常驻网络和常驻写入关闭；每次 apply 前独立备份，写后逐 target verifier error=0 才进入下一阶段。
