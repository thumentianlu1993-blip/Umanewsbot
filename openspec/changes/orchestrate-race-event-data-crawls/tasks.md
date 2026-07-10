## 1. 编排基础结构

- [x] 1.1 (integration) 新增赛事编排服务模块，定义 plan、run state、batch、adapter result、coverage result、apply-check result 的数据结构和读写工具。
- [x] 1.2 (integration) 实现 plan 解析与校验，覆盖 `target_layer=race_event`、五地区、source authority、series list、三模块、年份范围、批次大小、限速和网络授权。
- [x] 1.3 (integration) 实现运行目录创建与 artifact 复制规则，确保 plan、state、命令记录、stdout/stderr 摘要、候选产物、审计产物固定落盘。
- [x] 1.4 (application) 新增 `orchestrate_race_event_crawl` 管理命令骨架，支持 `plan`、`prepare`、`audit`、`dry-run`、`apply-check` 和 `resume` 阶段参数。
- [x] 1.5 (integration) 实现目标 `RaceEvent` 行预检，按地区、赛事系列、年份和 slug 检查现有行，并为缺失深历史目标输出 draft seed review artifact。

## 2. 候选生成 Adapter

- [x] 2.1 (integration) 为现有 `runtime/tools` 详情脚本建立 adapter manifest，声明地区、来源、模块、必需输入、必需输出和 source authority。
- [x] 2.2 (integration) 扫描首批目标脚本的真实命令行契约，记录特殊参数、前序依赖、固定年份输出名和 source cache 需求，禁止实现层假设统一 `events_csv/output_dir` 接口。
- [x] 2.3 (integration) 实现 adapter subprocess 调用层，记录实际命令、退出码、stdout/stderr 摘要，并在缺少必需产物时失败。
- [x] 2.4 (integration) 实现 adapter 产物归一化，把固定年份或来源特有文件名复制/索引为 run 目录中的标准候选 JSONL、review CSV、summary 和 source cache artifact，同时保留原始路径。
- [x] 2.5 (integration) 为存在前序依赖的脚本实现依赖检查，例如 `--review-csv`、`--source-html`、`--runner-jsonl` 和 `--pdf-dir`，依赖缺失时阻止执行并输出可复核错误。
- [x] 2.6 (integration) 为 `runners/results` 脚本接入 adapter：JRA、NAR、HKJC、UK Sporting Life、France ZEturf、US HRN/Equibase 缺口路径。
- [x] 2.7 (integration) 为 `history_winners` 脚本接入 adapter：JRA、NAR、HKJC、UK Sporting Life、France Wikipedia、US TOBA。

## 3. Series Mapping 与覆盖审计

- [x] 3.1 (integration) 实现 series mapping artifact 读取与校验，区分 approved、needs_review、ambiguous 和 new_series_candidate。
- [x] 3.2 (integration) 实现候选 JSONL 解析审计，检查 year/slug、模块、items、source_url、source authority、重复 slug、重复年份和 source URL 一对多污染。
- [x] 3.3 (integration) 实现三模块覆盖审计，按地区、赛事系列、年份和模块输出 complete、missing_runners、missing_results、missing_history_winners。
- [x] 3.4 (integration) 将目标 `RaceEvent` 行预检接入 coverage audit，缺失目标行时输出 `missing_race_event` blocker，并引用 draft seed review artifact。
- [x] 3.5 (integration) 实现已有正式数据 diff/review 摘要，记录现有来源、新来源、行数变化、年份覆盖变化和 manual lock 冲突。
- [x] 3.6 (integration) 实现 coverage audit JSON 与 review CSV 输出，明确 blocker、warning、info 分级和禁止 apply 的原因。

## 4. Dry-run 与 Apply 门禁

- [x] 4.1 (application) 在管理命令中实现 dry-run 阶段，调用现有 `import_race_event_detail_candidates --dry-run` 或等价校验，并保存输出。
- [x] 4.2 (integration) 实现 apply-check 阶段，校验 coverage 无 blocker、dry-run 通过、首批人工确认、diff/review、生产健康证据、外部导入锁证据和备份证据。
- [x] 4.3 (integration) 实现显式 apply 命令生成，不执行无人值守自动 apply，并在 artifact 中记录命令、适用范围和仍需人工确认的风险。
- [x] 4.4 (application) 确保单场人工修复仍可沿用现有 importer 流程，同时在编排文档中区分单场修复与历史批量回填。

## 5. 五地区验收样本与运行文档

- [x] 5.1 (operations) 为日本、香港、英国、法国、美国分别准备第一验收小批 plan fixture，每个地区使用少数核心赛事系列且包含三模块目标。
- [x] 5.2 (operations) 编写 source authority 矩阵，标明官方源、权威第三方源和参考源的默认等级与风险说明。
- [x] 5.3 (operations) 更新 `docs/deploy_runbook.md`，记录手动分批/一次性容器运行、resume、生产锁检查、备份和 apply-check 步骤。
- [x] 5.4 (operations) 更新 `docs/current_state.md` 和 `docs/project_status.md`，记录编排工具验收边界、五地区第一批策略和长期历史回填方向。

## 6. 验证

- [x] 6.1 (application) 添加管理命令参数与错误路径测试，覆盖缺 plan、target_layer 非 race_event、缺模块、历史深度不一致和未授权网络。
- [x] 6.2 (integration) 添加 adapter manifest 测试，覆盖特殊参数、前序依赖、固定年份输出归一化、缺依赖失败和原始产物追溯。
- [x] 6.3 (integration) 添加 adapter 与 artifact 测试，覆盖成功产物、缺产物、脚本失败、source authority 记录和 resume 跳过已完成阶段。
- [x] 6.4 (integration) 添加 coverage audit 测试，覆盖完整三模块、缺模块、缺目标 `RaceEvent` 行、重复候选、source URL 冲突、series mapping 待审和 manual lock 冲突。
- [x] 6.5 (integration) 添加五地区第一验收 fixture 测试，确认日本、香港、英国、法国、美国的小批 plan 均能产出三模块目标、adapter 选择和预检结果。
- [x] 6.6 (integration) 添加 apply-check 测试，覆盖首批人工确认缺失、dry-run 缺失、备份证据缺失、外部导入锁未清空和全绿生成显式 apply 命令。
- [x] 6.7 (application) 运行 `DB_ENGINE=sqlite python server/manage.py check`。
- [x] 6.8 (application) 运行相关 `stable` 测试或目标测试集。
- [x] 6.9 (operations) 运行 `openspec validate orchestrate-race-event-data-crawls --strict` 和 `openspec validate --all`。
- [x] 6.10 (operations) 运行 `git diff --check -- openspec/changes/orchestrate-race-event-data-crawls server docs runtime`。

## 7. Code review 返修

- [x] 7.1 (application) 保护 `attribution_locked=true` 的新闻主地区，来源提升和重复抓取不得覆盖人工归因。
- [x] 7.2 (integration) coverage audit 按 `year + slug` 聚合分模块 adapter 候选，仅在同一模块重复时生成 `duplicate_candidate`。
- [x] 7.3 (integration) apply-check 只把指向 `started` run 的锁视为活跃锁，持久化空闲锁行不得阻断。
- [x] 7.4 (application) 实现 adapter 粒度输入指纹和真实 resume，跳过输入未变化的成功 adapter、重试失败 adapter，并支持修正候选后重跑 audit。
- [x] 7.5 (operations) 重新运行目标测试、完整 `stable` 测试、Django check、迁移漂移检查、OpenSpec 校验和 `git diff --check`。

## 8. 第二轮 Code review 安全返修

- [x] 8.1 (integration) 为候选 JSONL 建立路径、大小和 SHA-256 身份，强制 coverage、dry-run 与 apply-check 绑定同一份候选文件。
- [x] 8.2 (application) 将 dry-run 结果改为结构化 artifact，并在 apply-check 中校验 `status=passed`、候选哈希和 artifact 内容。
- [x] 8.3 (integration) 由 adapter manifest 向候选注入来源、地区、模块和 source authority，coverage 阻断缺失/冲突 provenance，apply-check 强制确认实际混合来源组合。
- [x] 8.4 (integration) resume 跳过成功 adapter 前校验所有必需输出及哈希，缺失或变化时重新执行并记录原因。
- [x] 8.5 (application) 让 dry-run、apply-check 的成功与失败完整写入 `RunState`，并允许 resume 使用保存的阶段输入恢复。
- [x] 8.6 (operations) 补齐上述失败场景测试，更新运行文档并重新执行目标测试、完整 `stable` 测试、Django/OpenSpec/迁移和 diff 校验。

## 9. 第三轮 Code review 完整性返修

- [x] 9.1 (integration) 在网络抓取前生成绑定 plan 哈希的独立应到清单和运营 review CSV，让空候选、缺失目标、额外目标与 series 不一致全部 fail closed
- [x] 9.2 (integration) 将各 adapter 归一化候选汇总为 run 级 combined JSONL，并让 audit、dry-run 默认复用该 artifact
- [x] 9.3 (integration) 校验并落实 batch/rate limit，让全部默认网络 adapter 共享持久化运行级请求预算且预算损坏时停止请求
- [x] 9.4 (application) 补强第一验收的地区模块 adapter 覆盖校验，以及 apply-check 的真实备份文件与 diff approved 证据校验
- [x] 9.5 (application) 增加空候选、意外候选、应到快照、候选汇总、共享预算、地区 adapter 缺口和 apply 证据失败测试
- [x] 9.6 (operations) 更新运行文档并重新执行目标测试、完整 `stable` 测试、Django/OpenSpec/迁移和 diff 校验

## 10. 第四轮 Code review 写入门禁返修

- [x] 10.1 (integration) 从 coverage 候选推导实际地区、来源和模块组合，apply-check 对账 apply scope 并要求每个实际组合分别确认。
- [x] 10.2 (application) apply-check 生成按哈希命名的 approved candidate，importer 增加 `--expected-sha256` 并在任何写库前从同一批字节复核哈希。
- [x] 10.3 (integration) 严格校验 adapter payload，拒绝未知形态、空 command、缺 modules/outputs 的自定义 manifest，prepare 不得静默跳过。
- [x] 10.4 (integration) coverage 分离行级 blocker/warning，支持 `complete_with_warnings` 且 warning 不降低 complete count。
- [x] 10.5 (application) 补齐多范围候选、批准后篡改、无效 adapter、已有数据三种完整性状态测试。
- [x] 10.6 (operations) 记录技术审查自动修复与产品/交互仍需用户审核的协作边界，更新 runbook/current state/project status 并执行完整验证。

## 11. 第五轮 Code review 证据链返修

- [x] 11.1 (integration) 将多地区新闻迁移顺延为 `0023` 并依赖主干 horse profile `0022`，消除迁移叶节点冲突。
- [x] 11.2 (integration) 为应到清单建立绑定 SHA-256 的显式审批 artifact，真实网络 prepare 前必须 `approved` 且包含批准人和批准时间。
- [x] 11.3 (integration) 从已审批应到清单按地区生成 adapter `events_csv`，禁止共享旧输入把计划外赛事送入抓取器。
- [x] 11.4 (integration) coverage 仅接受 `mapping_status=approved`，并将空 `items`、缺 `source_url` 视为 blocker。
- [x] 11.5 (integration) apply-check 复核 coverage 与当前应到清单身份、真实解压校验 gzip 备份，并要求每条范围确认包含 approved 状态、批准人和批准时间。
- [x] 11.6 (application) 补齐应到审批、地区输入、空模块、mapping typo、证据调包、伪 gzip、确认元数据和来源 URL 测试。
- [x] 11.7 (operations) 更新 OpenSpec 与项目运行文档，并执行目标测试、完整 stable 回归、Django/迁移/OpenSpec/diff 校验。
