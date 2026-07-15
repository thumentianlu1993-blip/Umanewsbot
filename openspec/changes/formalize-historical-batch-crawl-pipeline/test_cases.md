# 完整测试用例

## 1. 测试层级与固定 fixture

- `S`：纯 service / artifact 单元测试，不访问网络或生产数据库。
- `C`：Django 管理命令集成测试，默认 SQLite；标记 PostgreSQL 的用例必须使用真实 PostgreSQL 16。
- `R`：historical runner 计划、权限、资源和恢复测试。
- `O`：生产运维验收，只允许可信生产主机和固定 AMD64 镜像。

固定 fixture：

- approved selection：五地区、10 个年份分组，默认 25 targets；性能组为 1250 targets。
- 每个 target 均有稳定 `target_id / target_sha256 / series_key / year / country_region / inventory_manifest_sha256`。
- approval 必须绑定 manifest SHA 并列出全部 approved target IDs。
- 合法详情 candidate 同时包含 complete runners/results，马号和名次唯一，保留来源原文距离单位。
- 所有外部请求在测试中 mock；只有 `O` 层允许真实网络。

## 2. Selection、approval 与 plan 基础身份

| ID | 前置条件 | 操作 | 预期 | 层级 |
| --- | --- | --- | --- | --- |
| TC-PLAN-001 | selection/approval/manifest/image/tool SHA 全部匹配 | 生成 stage plan | 成功输出 stage manifest、summary、每 shard scope 与 plan | S/C |
| TC-PLAN-002 | selection 文件字节变化 | 生成 plan | SHA mismatch，最终输出目录不存在 | S/C |
| TC-PLAN-003 | approval 为 pending | 生成 plan | 拒绝，指出 approval 未批准 | S/C |
| TC-PLAN-004 | approval approved_target_ids 少一个 | 生成 plan | 拒绝，指出批准范围不完整 | S/C |
| TC-PLAN-005 | approval 含 selection 外 target | 生成 plan | 拒绝，指出 unexpected target | S/C |
| TC-PLAN-006 | manifest SHA 与 approval 不同 | 生成 plan | 拒绝且不生成部分 shard | S/C |
| TC-PLAN-007 | image ID 不是完整 `sha256:<64>` | 生成 plan | 拒绝 | S/C |
| TC-PLAN-008 | revision 不是 40 位 commit | 生成 plan | 拒绝 | S/C |
| TC-PLAN-009 | tool manifest SHA 与镜像工具不同 | 生成 plan | 拒绝 | S/C |
| TC-PLAN-010 | descriptor schema 未知 | 生成 plan | 明确 unsupported schema | S/C |
| TC-PLAN-011 | shard ID 重复 | 生成 plan | 拒绝 | S/C |
| TC-PLAN-012 | shard 输出目录重复或父子重叠 | 生成 plan | 拒绝，避免跨 shard 覆盖 | S/C |
| TC-PLAN-013 | 同一输入仅键顺序不同 | 生成 plan 两次到不同空目录 | canonical 文件 SHA 完全一致 | S/C |
| TC-PLAN-014 | 目标输出目录已存在且非空 | 生成 plan | 拒绝覆盖 | S/C |
| TC-PLAN-015 | descriptor 引用 artifact 根外路径 | 生成 plan | path escape 拒绝 | S/C |
| TC-PLAN-016 | descriptor 引用 symlink 输入 | 生成 plan | 拒绝 symlink，不跟随到根外 | S/C |
| TC-PLAN-017 | selection 的 target ID/year 使用布尔值 | 生成 plan | 拒绝，布尔值不能冒充整数身份 | S/C |

## 3. Shard 覆盖与 typed recipe 目标绑定

| ID | 前置条件 | 操作 | 预期 | 层级 |
| --- | --- | --- | --- | --- |
| TC-SHARD-001 | 1061 targets 合法拆成多个 shard | 生成 plan | 全量 target 恰好一次，地区计数与 selection 一致 | S/C |
| TC-SHARD-002 | 一个 target 出现在两个 shard | 生成 plan | duplicate target 拒绝 | S/C |
| TC-SHARD-003 | 一个 target 未进入任何 shard | 生成 plan | missing target 拒绝 | S/C |
| TC-SHARD-004 | shard 声明法国但含英国 target | 生成 plan | region mismatch 拒绝 | S/C |
| TC-SHARD-005 | shard 含 250 targets | 生成 plan | 允许 | S/C |
| TC-SHARD-006 | shard 含 251 targets | 生成 plan | 拒绝 | S/C |
| TC-SHARD-007 | shard 请求预算为 1/250 | 生成 plan | 两个边界均允许 | S/C |
| TC-SHARD-008 | shard 请求预算为 0/251/非整数 | 生成 plan | 全部拒绝 | S/C |
| TC-SHARD-009 | typed recipe 的 events CSV 少一个 target | 生成 plan | 实际输入 scope mismatch 拒绝 | S/C |
| TC-SHARD-010 | typed recipe 的 events CSV 多一个 approved target | 生成 plan | 实际输入 scope mismatch 拒绝 | S/C |
| TC-SHARD-011 | provider JSONL 含跨 shard target | 生成 plan | 拒绝 | S/C |
| TC-SHARD-012 | candidate JSONL target_id 重复 | 生成 plan | 拒绝 | S/C |
| TC-SHARD-013 | selection subset SHA 正确且目标精确 | 生成 discovery recipe | builder 自行生成 argv，禁止 descriptor 注入 argv | S/C |
| TC-SHARD-014 | descriptor 直接提供 `argv` | 生成 plan | 拒绝任意 argv | S/C |
| TC-SHARD-015 | 使用已在 runner 白名单但无 binding policy 的工具 | 生成 plan | 拒绝并指出 missing policy | S/C |
| TC-SHARD-016 | 使用 `tmp/` 脚本 | 生成 plan | 拒绝 | S/C |
| TC-SHARD-017 | 使用 artifact 内 Python 脚本 | 生成 plan | immutable tool root 拒绝 | S/C/R |
| TC-SHARD-018 | recipe 输入 target 顺序变化 | 生成 plan | scope 和 plan SHA 不受顺序影响 | S/C |
| TC-SHARD-019 | discovery recipe 缺少 `year` 或 selection 混入其他年份 | 生成 plan | 拒绝，实际 scope 必须与该年 shard 精确一致 | S/C |
| TC-SHARD-020 | 详情 recipe 的非零 `limit` 小于 shard 目标数 | 生成 plan | 拒绝，禁止静默截断目标 | S/C |
| TC-SHARD-021 | 法国 recipe 的日期范围排除任一 events CSV 目标 | 生成 plan | scope mismatch 拒绝 | S/C |
| TC-SHARD-022 | fragment/gap 同时声明 target ID 与系列届次但两者冲突 | 生成 plan/merge | 拒绝，不任选其中一个身份 | S/C |
| TC-SHARD-023 | 同一 catalog URL 覆盖两个届次年，parser 按年分片 | request/cache/parse | URL 只请求一次，ledger 引用为两届 scope 并集，每个 parser 只输出本届 target | S/C |
| TC-PLAN-018 | target/source identity 为布尔值、分数或空字符串 | validate/build | 拒绝，不做整数或字符串宽松转换 | S/C |

首批 typed recipe 必须各有成功和 scope mismatch 用例：

| ID | Recipe |
| --- | --- |
| TC-RECIPE-001 | `discover_historical_race_band_sources.py` |
| TC-RECIPE-002 | `cache_historical_race_date_sources.py` |
| TC-RECIPE-003 | `prepare_jra_race_detail_candidates.py` |
| TC-RECIPE-004 | `prepare_hkjc_race_detail_candidates.py` |
| TC-RECIPE-005 | `prepare_uk_sportinglife_race_detail_candidates.py` |
| TC-RECIPE-006 | `prepare_france_zeturf_race_detail_candidates.py` |
| TC-RECIPE-007 | `prepare_us_equibase_result_candidates.py` |
| TC-RECIPE-008 | `prepare_cached_historical_race_details.py` |
| TC-RECIPE-009 | `package_historical_race_detail_candidates.py` |
| TC-RECIPE-010 | `merge_historical_race_batch_fragments.py` |

## 4. Shard artifact 根与资源限制

| ID | 前置条件 | 操作 | 预期 | 层级 |
| --- | --- | --- | --- | --- |
| TC-RESOURCE-001 | 两个合法 shard | 生成计划 | 两个独立宿主目录，各自 plan/scope/input copies，无 symlink | S/C |
| TC-RESOURCE-002 | 两个 shard 被配置到同一 artifact 根 | 生成计划 | 拒绝 | S/C |
| TC-RESOURCE-003 | crawl plan 有完整 resource_limits | validate | 接受并规范化 | S/R |
| TC-RESOURCE-004 | plan request_budget 与 settings 相同 | 创建 run | 允许 | R |
| TC-RESOURCE-005 | plan request_budget 与 settings 不同 | 创建/恢复 run | 在创建 run 或取锁前拒绝，数据库无新 run | R |
| TC-RESOURCE-006 | cache bytes 与 settings 不同 | 创建/恢复 run | 拒绝 | R |
| TC-RESOURCE-007 | free disk floor 与 settings 不同 | 创建/恢复 run | 拒绝 | R |
| TC-RESOURCE-008 | request interval 与固定 settings 不同 | 创建/恢复 run | 拒绝 | R |
| TC-RESOURCE-009 | legacy schema 1.0 smoke plan | smoke 启动 | 保持兼容 | R |
| TC-RESOURCE-010 | formal descriptor 请求 legacy plan | 生成 plan | 禁止降级 | S/C |
| TC-RESOURCE-011 | 两个 shard 依次运行 | 检查资源 artifact | 各自拥有独立 ledger/cache manifest/state/checkpoint | R/O |
| TC-RESOURCE-012 | shard 暂停后篡改 ledger | resume | blocked，不创建新额度 | R |
| TC-RESOURCE-013 | resource_limits 任一整数字段为布尔值 | validate | 拒绝 | S/R |
| TC-RESOURCE-014 | plan shard IDs 不属于 selection 或 approval | validate | 在创建 run 前拒绝 | S/R |

## 5. Date fragment 合并

| ID | 前置条件 | 操作 | 预期 | 层级 |
| --- | --- | --- | --- | --- |
| TC-DATE-001 | 多个 provider JSONL 完整覆盖 scope | `date` merge | complete=scope、gap=0、确定排序 | S |
| TC-DATE-002 | 相同 provider row 重复出现 | merge | 规范化去重，summary 记录 duplicate evidence | S |
| TC-DATE-003 | 同 target 日期不同 | merge | complete 移除，生成 conflict gap，保留双方 SHA | S |
| TC-DATE-004 | 同 target result URL 不同 | merge | conflict gap | S |
| TC-DATE-005 | target SHA 不匹配 selection | merge | fail closed | S |
| TC-DATE-006 | inventory SHA 不匹配 | merge | fail closed | S |
| TC-DATE-007 | `(series_key, edition_year)` 不存在 | merge | unexpected target 拒绝 | S |
| TC-DATE-008 | provider row 完全缺少 target 且无 gap | merge | missing target，整体失败 | S |
| TC-DATE-009 | target 有显式来源失败 gap | merge | complete+gap=scope，允许输出 | S |
| TC-DATE-010 | target 同时在 complete 和 gap | merge | overlap 拒绝 | S |
| TC-DATE-011 | gap 缺 target SHA/原因/证据身份/时间 | merge | 拒绝无证据 gap | S |
| TC-DATE-012 | 香港赛事实际日期跨届次年度 | merge | 保留 edition year，并输出 actual year/cross-year reason | S |
| TC-DATE-013 | 法港日纯数字距离 | merge | 只有有明确来源单位时写 `m`，不跨地区猜单位 | S |
| TC-DATE-014 | 英美原文为 `2m4f`、`3m210y`、`8.5f` | merge | 原单位原样保留 | S |
| TC-DATE-015 | 输入文件顺序反转 | merge | provider/gap/summary SHA 相同 | S |
| TC-DATE-016 | 日期外形合法但日历不存在 | merge | 不进入 complete，生成有证据 invalid_fragment gap | S |
| TC-DATE-017 | gap recorded_at 不是合法带时区时间 | merge | 拒绝 | S |
| TC-DATE-018 | 真实 provider 行只有系列+届次、不含 target SHA | merge | 从冻结 selection 补入身份；若显式 SHA 存在则仍必须匹配 | S |
| TC-DATE-019 | discovery/package gap 为 JSON 数组且只有 reason/code | merge | 用 selection、输入文件 SHA 与绑定时间规范化为正式 gap | S |
| TC-DATE-020 | gap 行内自带与实际文件不符的 evidence identity | merge | 以实际读取文件的 size/SHA/行号重新绑定，不信任内嵌身份 | S |

## 6. Detail fragment 合并

| ID | 前置条件 | 操作 | 预期 | 层级 |
| --- | --- | --- | --- | --- |
| TC-DETAIL-001 | 多地区 candidates 完整覆盖 scope | `detail` merge | 每 target 一条正式候选，gap=0 | S |
| TC-DETAIL-002 | candidate 缺 runners | merge | 转 incomplete gap 或按显式失败证据留 gap，不进入 complete | S |
| TC-DETAIL-003 | candidate 缺 results | merge | 同上 | S |
| TC-DETAIL-004 | runners/results `is_complete=false` | merge | 不进入 complete | S |
| TC-DETAIL-005 | runners/items 为空 | merge | 不进入 complete | S |
| TC-DETAIL-006 | 同一非空马号重复 | merge | conflict/incomplete gap | S |
| TC-DETAIL-007 | 同一有效名次重复 | merge | conflict/incomplete gap | S |
| TC-DETAIL-008 | 退赛/未完赛状态 | merge | 可无数值名次但保留状态，不伪造名次 | S |
| TC-DETAIL-009 | 同 target 两份 canonical candidate 相同 | merge | 去重并记录两份输入身份 | S |
| TC-DETAIL-010 | 同 target 胜马或 1 号马不同 | merge | conflict gap | S |
| TC-DETAIL-011 | source URL 不是 HTTPS | merge | 拒绝 complete candidate | S |
| TC-DETAIL-012 | source-cache manifest 文件大小/SHA 漂移 | merge | fail closed | S |
| TC-DETAIL-013 | candidate source URL 不在 cache manifest | merge | fail closed | S |
| TC-DETAIL-014 | target/inventory SHA 漂移 | merge | fail closed | S |
| TC-DETAIL-015 | gap 与 complete 合计少一个 | merge | 整体失败 | S |
| TC-DETAIL-016 | gap 与 complete 有交集 | merge | 整体失败 | S |
| TC-DETAIL-017 | 仅部分 targets complete | merge | 只输出 complete candidates，gap 保留全部未完成 ID | S |
| TC-DETAIL-018 | 输入顺序和 JSON key 顺序变化 | merge | candidate/gap/summary SHA 相同 | S |
| TC-DETAIL-019 | 马名/骑手原文含 Unicode | merge | UTF-8 canonical 输出无损 | S |
| TC-DETAIL-020 | 地区距离单位各异 | merge | 不统一换算，原始值及 provenance 保留 | S |
| TC-DETAIL-021 | 权威来源未提供马号 | merge | 多个空马号允许，但马名和其他完整性仍必须满足 | S |

## 7. 人工 evidence fragment

| ID | 前置条件 | 操作 | 预期 | 层级 |
| --- | --- | --- | --- | --- |
| TC-EVIDENCE-001 | target SHA 与 expected old value 匹配 | 应用人工补证 | 生效并保留 URL/authority/reason/reviewer/time | S |
| TC-EVIDENCE-002 | target SHA 已变化 | 应用补证 | 该 target 转 conflict gap，其他 target 继续，候选不被覆盖 | S |
| TC-EVIDENCE-003 | expected old value 不匹配 | 应用补证 | 该 target 转 conflict gap，其他 target 继续 | S |
| TC-EVIDENCE-004 | 同字段两份人工补证新值不同 | merge | conflict gap | S |
| TC-EVIDENCE-005 | 缺来源 URL 或理由 | merge | 拒绝 | S |
| TC-EVIDENCE-006 | 来源 URL 为 HTTP/file | merge | 拒绝 | S |
| TC-EVIDENCE-007 | 补证只修日期，不声明其他字段 | merge | 仅日期变化，其他字段保持原值 | S |
| TC-EVIDENCE-008 | 扫描 tracked merger/descriptor fixtures | 静态检查 | 不含生产 target ID 常量或 batch006 绝对路径 | S |
| TC-EVIDENCE-009 | reviewed_at 非法或无时区 | merge | 拒绝 | S |
| TC-EVIDENCE-010 | 补证尝试修改 target/selection 身份字段 | merge | 拒绝 | S |

## 8. 原子发布、路径和恢复

| ID | 前置条件 | 操作 | 预期 | 层级 |
| --- | --- | --- | --- | --- |
| TC-ATOMIC-001 | 正常生成多文件 artifact | 发布 | 临时目录 fsync 后一次 rename，最终目录完整 | S/C |
| TC-ATOMIC-002 | 写第二个文件时注入异常 | 发布 | 最终目录不存在，输入不变 | S/C |
| TC-ATOMIC-003 | manifest 校验时注入异常 | 发布 | 最终目录不存在 | S/C |
| TC-ATOMIC-004 | 最终目录已存在空目录 | 发布 | 默认拒绝，不能把空目录当作可覆盖 | S/C |
| TC-ATOMIC-005 | 临时目录残留 | 新一轮发布 | 不读取旧临时输出，使用唯一临时名 | S/C |
| TC-ATOMIC-006 | 输出路径逃逸 artifact 根 | 发布 | 拒绝 | S/C |
| TC-ATOMIC-007 | source-cache/resource artifact 为 symlink | checkpoint/merge | 拒绝 | S/R |
| TC-ATOMIC-008 | shard 完成后普通 web 部署 | runner 状态检查 | checkpoint/output 不受影响 | R/O |
| TC-ATOMIC-009 | 最终目录 rename 成功后父目录 fsync 失败 | 发布 | 返回失败并删除最终目录，重跑不被半确认产物阻塞 | S/C |
| TC-ATOMIC-010 | 两个 step 的输出文件/目录相同或互为父子 | validate | 创建 run 前拒绝全局路径重叠 | S/R |
| TC-ATOMIC-011 | checkpoint 后普通输出文件替换为同内容 symlink | resume | 拒绝，不以相同 size/SHA 放行 | R |

## 9. 数据库阶段 verifier

| ID | 前置条件 | 操作 | 预期 | 层级 |
| --- | --- | --- | --- | --- |
| TC-VERIFY-001 | date apply 全部正确 | verify date | ready 数量、日期、event identity、manifest/source URL 全部一致 | C |
| TC-VERIFY-002 | 一个 target/event 日期不同 | verify date | 非零退出，报告 target ID | C |
| TC-VERIFY-003 | target 缺 materialized event | verify date | 非零退出 | C |
| TC-VERIFY-004 | detail-source apply 正确 | verify detail-source | target/event approved source 均存在 | C |
| TC-VERIFY-005 | target 有来源但 event 缺来源 | verify detail-source | 非零退出 | C |
| TC-VERIFY-006 | final apply 正确 | verify final | imported、模块 complete、数量/provenance 一致 | C |
| TC-VERIFY-007 | runner 数量少一个 | verify final | 非零退出，报告 expected/actual | C |
| TC-VERIFY-008 | result 数量多一个 | verify final | 非零退出 | C |
| TC-VERIFY-009 | applied candidate source 不匹配 | verify final | 非零退出 | C |
| TC-VERIFY-010 | complete target 仍 pending | verify final | 非零退出 | C |
| TC-VERIFY-011 | 任一历史 event 为 published | 任意 stage verify | 非零退出并报告 published count | C |
| TC-VERIFY-012 | gap target 保持 pending | verify final | 不算 imported 错误，单独报告 gap pending | C |
| TC-VERIFY-013 | PostgreSQL verifier 正常运行 | 抓 SQL | 事务内首先设置 READ ONLY，仅 SELECT | C/PostgreSQL |
| TC-VERIFY-014 | verifier 内注入 UPDATE | 运行 | PostgreSQL 拒绝写入，业务值不变 | C/PostgreSQL |
| TC-VERIFY-015 | 相同输入重复 verify | 运行两次 | 输出 canonical 业务结果一致，数据库零变化 | C |
| TC-VERIFY-016 | 1250 targets | verify | 查询数不超过 20，无逐 target 查询 | C/PostgreSQL |
| TC-VERIFY-017 | gap target 已有关联 published event | verify | 非零退出并计入 published count | C |
| TC-VERIFY-018 | 同一模块保留多条历史 APPLIED candidate | verify final | 按 applied_at/id 取最新一条核验，旧记录只保留审计 | C |

## 10. 性能与资源

| ID | 前置条件 | 操作 | 预期 | 层级 |
| --- | --- | --- | --- | --- |
| TC-PERF-001 | 1250 targets/10 shards | plan builder | 30 秒内、额外 RSS <=256 MiB | S/C |
| TC-PERF-002 | 1250 targets，每场 20 runners+20 results | detail merge | 30 秒内、额外 RSS <=256 MiB | S |
| TC-PERF-003 | 10 个 source manifests 含大 source body 文件 | merge | 只流式计算 SHA，不把 body 常驻内存 | S |
| TC-PERF-004 | 生产 artifact 文件系统低于 5 GiB | 启动 shard | 宿主和 Django 双层拒绝，未创建 run | R/O |

## 11. 回归与生产 batch006 验收

| ID | 前置条件 | 操作 | 预期 | 层级 |
| --- | --- | --- | --- | --- |
| TC-REG-001 | 既有 runner smoke/schema 1.0 | 跑历史 runner 测试 | 全部通过 | R |
| TC-REG-002 | batch002-batch005 artifact | 读取/审计 | 不重写旧 artifact，legacy 口径保持 | C |
| TC-REG-003 | 既有 date/source/import commands | 聚焦回归 | 行为不变 | C |
| TC-REG-004 | 完整 stable | 测试 | 全部通过，仅既有环境 skip | C |
| TC-REG-005 | Django check/migration drift/OpenSpec/diff | 验证 | 全部通过，无迁移 | C |
| TC-PROD-001 | main 双构建 | 比较镜像 | AMD64 image ID 完全一致，labels 精确 | O |
| TC-PROD-002 | 部署前安静窗口 | 备份 | custom dump SHA、bytes、`pg_restore -l` 通过 | O |
| TC-PROD-003 | 新镜像切换 | 验收 | 仅 web/worker/beat 替换，DB/Redis/runner/network 未重建 | O |
| TC-PROD-004 | 新 runner smoke | crawl/apply/pause/resume/tool root | 全部通过，无残留容器/run | O |
| TC-PROD-005 | batch006 artifact | 核对 | manifest `62aca6...`, selection `b9a3ad...`, approval `a119e3...`, 1061 targets | O |
| TC-PROD-006 | 正式 stage descriptor | 生成 shards | 11 个地区×届次年 scope：FR `120/130`、HK `35/26`、JP `88/138/24`、UK `196/54`、US `83/167`；全量零重叠零遗漏，每 shard <=250 targets/请求 | O |
| TC-PROD-007 | 正式 crawl | 运行 | 每 shard 独立账本/cache/checkpoint，暂停恢复不重抓 | O |
| TC-PROD-008 | 少量歧义 | crawl/merge | 写入 gap ledger 后继续其他 shard，不等待用户逐条确认 | O |
| TC-PROD-009 | date/detail-source/final apply | 每阶段 | 写前独立备份，dry-run 通过，正式 verifier error=0 | O |
| TC-PROD-010 | batch006 收口 | 验收 | complete+gap=1061、逐地区计数明确、published=0、常驻开关 false | O |
| TC-PROD-011 | 服务收口 | 核对 | healthz ok，队列/active/reserved/事务/runner 为 0 或可解释 | O |
| TC-PROD-012 | 下一标准批次 | 生成 | 排除既有有效 selection，继续 2016-2025 直至该年代带无 eligible pending | O |

## 12. 执行顺序

1. 先把 `TC-PLAN`、`TC-SHARD`、`TC-RECIPE`、`TC-RESOURCE`、`TC-DATE`、`TC-DETAIL`、`TC-EVIDENCE`、`TC-ATOMIC`、`TC-VERIFY`、`TC-PERF` 和全部 `TC-CALENDAR` 写入测试套件，并确认旧实现因缺少新能力而失败。
2. 再实现 plan builder、typed policies、resource identity、merger、verifier、年度赛历 request/cache/parse 和白名单。
3. 跑聚焦与完整回归；任何失败先修复，再进入代码 review。
4. 反复 review/修复/重新 review，直到一次无 actionable finding。
5. 最后执行 `TC-PROD`；先重新部署包含赛历能力的新固定镜像，再启动 batch006，生产公开和常驻历史开关始终保持关闭。

## 13. 年度赛历请求与缓存

| ID | 前置条件 | 操作 | 预期 | 层级 |
| --- | --- | --- | --- | --- |
| TC-CALENDAR-REQ-001 | selection 某地区年份有两份年度目录 | 展开 catalog | 每 target 绑定两份来源，共享 URL 在 cache 仅请求一次 | S |
| TC-CALENDAR-REQ-002 | catalog 漏掉一个 target | 展开 | fail closed，最终输出目录不存在 | S |
| TC-CALENDAR-REQ-003 | source 地区/年份跨 scope | 展开 | 拒绝并指出 source ID/target | S |
| TC-CALENDAR-REQ-004 | 重复 source ID、未知 parser/adapter | 展开 | 拒绝 | S |
| TC-CALENDAR-REQ-005 | URL 非 HTTPS、含凭据或 host 不在 adapter allowlist | 展开 | 拒绝 | S |
| TC-CALENDAR-REQ-006 | selection/catalog 输入顺序变化 | 展开两次 | provider/summary/manifest 业务 SHA 一致 | S |
| TC-CALENDAR-REQ-007 | 输出目录已存在或发布中注入异常 | 展开 | 拒绝覆盖；失败不留半套 artifact | S |
| TC-CALENDAR-REQ-008 | 一条 URL 被多个年份 source 共用 | 展开/cache | 生成全量 target reference 并只请求一次，ledger 引用必须精确匹配来源 scope 并集 | S/R |
| TC-CALENDAR-CACHE-001 | 全部唯一 URL 成功 | cache | ledger 每 URL 一条，target references 完整，summary success=all | S/R |
| TC-CALENDAR-CACHE-002 | 一个 URL 失败，默认模式 | cache | 返回非零，ledger 保留失败与受影响 targets | S/R |
| TC-CALENDAR-CACHE-003 | 一个 URL 失败，显式 allow-partial | cache | 所有请求均为终态后返回零；failure_count 与 affected_target_count 非零 | S/R |
| TC-CALENDAR-CACHE-004 | partial 时请求未形成终态 | cache | 拒绝成功收口 | S/R |
| TC-CALENDAR-CACHE-005 | provider 重复引用同一 URL | cache | 只消耗一次请求预算，references 去重确定排序 | S/R |

## 14. 年度赛历离线解析

| ID | 前置条件 | 操作 | 预期 | 层级 |
| --- | --- | --- | --- | --- |
| TC-CALENDAR-PARSE-001 | JRA schedule/history 缓存 | 解析 | 唯一目标生成 provider row 与 events_japan.csv | S |
| TC-CALENDAR-PARSE-002 | TOBA 年鉴缓存 | 解析 | 同名赛事按场地/距离拆线并生成 Equibase 直接 URL | S |
| TC-CALENDAR-PARSE-003 | BHA 平地+障碍 PDF 文本 | 解析 | 合并年度目录，英制距离原样保留，目标恰好一次 | S |
| TC-CALENDAR-PARSE-004 | France Galop 平地+障碍 PDF 文本 | 解析 | 公制距离保留 `m`，场地/届次正确 | S |
| TC-CALENDAR-PARSE-005 | HKJC 跨年赛季文本 | 解析 | edition year 与自然日期分别保留，单位为明确公制 | S |
| TC-CALENDAR-PARSE-006 | PDF 无可提取文本 | 解析 | 受影响 targets 进入带 cache identity 的 gap，不猜格式 | S |
| TC-CALENDAR-PARSE-007 | request ledger failed | 解析 | 受影响 targets 进入 source_request_failed gap，其他继续 | S |
| TC-CALENDAR-PARSE-008 | 匹配缺失或多义 | 解析 | 对应 target 进入明确 gap，complete+gap=scope | S |
| TC-CALENDAR-PARSE-009 | cache manifest path/size/SHA/source URL 漂移 | 解析 | fail closed，最终目录不存在 | S |
| TC-CALENDAR-PARSE-010 | catalog/selection 地区或年份漂移 | 解析 | fail closed | S |
| TC-CALENDAR-PARSE-011 | 未知 parser 或 parser options 类型错误 | 解析 | fail closed | S |
| TC-CALENDAR-PARSE-012 | 同 target 被两份来源解析出冲突日期 | 解析 | conflict gap，保留双方身份 | S |
| TC-CALENDAR-PARSE-013 | recorded_at 无时区或不固定 | 解析 | 拒绝 | S |
| TC-CALENDAR-PARSE-014 | 输入顺序变化、同 recorded_at | 解析两次 | canonical 业务输出一致 | S |
| TC-CALENDAR-PARSE-015 | 输出第二个文件时异常/目录已存在 | 解析 | 原子失败，不覆盖、不留半套 | S |
| TC-CALENDAR-PARSE-016 | 1250 targets、10 个年度源 | 解析 | 30 秒/额外 RSS 256 MiB 内完成，不常驻 PDF body | S |
| TC-CALENDAR-PARSE-017 | BHA/France/HK 目录只有年度赛历 URL | 解析 | events complete，但不生成伪 result provider row | S |
| TC-CALENDAR-PARSE-018 | JRA/TOBA 有唯一直接赛果 URL | 解析 | events 与 provider row 同时生成，URL/provenance 一致 | S |
| TC-CALENDAR-PARSE-019 | cache artifact 复制到新 shard 根 | 解析 | manifest 原 root 只作 provenance，按声明复制根和相对 path 复核成功 | S/C |
| TC-CALENDAR-PARSE-020 | France Galop 固定列障碍分组汇总 PDF | 解析 | layout 模式保留列边界，补齐详细赛程未覆盖的赛事 | S |
| TC-CALENDAR-PARSE-021 | 同目标详细赛程与汇总表日期冲突且同质量 | 解析 | 详细赛程优先，汇总表不覆盖；输出仍唯一完整 | S |
| TC-CALENDAR-PLAN-001 | 新 parser recipe 声明地区+年份 | build plan | actual scope 精确等于 shard，cache 目录逐文件绑定 | S/C |
| TC-CALENDAR-PLAN-002 | recipe 少地区/年份/recorded_at | build plan | 拒绝 | S/C |
| TC-CALENDAR-PLAN-003 | recipe selection 实际含额外年份/地区 | build plan | 按显式地区+年份过滤；若仍与 shard 不等则拒绝 | S/C |
| TC-CALENDAR-PLAN-004 | parser 工具不在白名单或 SHA 漂移 | validate/run | 创建 run 前拒绝 | S/R |
| TC-CALENDAR-PLAN-005 | verify parse stage 声明 network=true/write=true，或 cache 尚未完成 | 生产门禁 | 拒绝启动 | R/O |
| TC-CALENDAR-PLAN-006 | legacy descriptor 缺 phase | build plan | 继续按 crawl 生成，既有 batch 行为不变 | S/C |
| TC-CALENDAR-PLAN-007 | verify descriptor 有 resource_limits 或非零 request budget | build plan | 拒绝 | S/C |
| TC-CALENDAR-PLAN-008 | verify descriptor 合法且 parser tool 已批准 | build/run | plan 为 network=false/write=false，保留锁/心跳/checkpoint | S/R |
| TC-CALENDAR-PLAN-009 | parser recipe 输出目录 | build/run | plan 使用 output_directories，checkpoint 绑定全部成员相对路径/size/SHA | S/R |
| TC-CALENDAR-PLAN-010 | 完成后输出目录新增/删除/替换成员或 symlink | resume | checkpoint mismatch，拒绝跳过已完成 step | R |
