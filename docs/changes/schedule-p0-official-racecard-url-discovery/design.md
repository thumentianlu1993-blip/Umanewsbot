# P0 官方出马页面 URL 定时发现设计

## 1. 组件

计划新增：

- `stable/services/p0_racecard_url_discovery.py`
  - P0 可判窗枚举与有界 orphan 审计；
  - provider adapter 注册、唯一选择与严格 identity match；
  - URL 策略验证；
  - canonical state 合并；
  - generation bundle、manifest 和原子 current 切换。
- `stable/tasks.py`
  - `discover_p0_racecard_urls_task`；
  - feature flag 关闭时立即 noop。
- `app/settings.py`
  - enable flag、artifact root、route registry、预算与 Celery schedule/annotation；
  - 不配置显式 task route，沿用普通 worker 实际消费的 Celery 默认队列 `celery`。
- `runtime/policies/p0_racecard_urls/official_url_routes_v1.json`
  - provider、region、allowed host/path、access mode、automation flag、稳定身份字段、
    contract/version/evidence。
- `.env.example` 与 `docker-compose.prod.lowcost.yml`
  - 默认关闭；
  - 普通 worker 挂载持久化宿主目录。

无数据库 migration。复用 `TaskExecutionLog`，但新 task 使用专用脱敏完成/失败记录函数。

## 2. 执行流

1. task 读取开关；关闭即返回 `disabled`，不查询 provider、不写文件。
2. 冻结 `run_started_at` 与 `[start, end)`。
3. 枚举可判窗 P0 与有界 orphan，构建不可变目标快照。
4. 以 `source_refs namespace + region + track identity + contract` 唯一选择 adapter。
5. 先按受审模板离线构造 URL，再按 route 的 `verification_method` 发 `HEAD` 或既有受审
   marker 请求；只保留最小状态，不缓存 body。
6. 校验 provider identity、host/path、scheme、redirect 与 contract。
7. 取得文件锁，通过受控 `current` 读取当前 generation。
8. 若当前 `last_completed_run_started_at > run_started_at`，标为 stale 并拒绝写。
9. 合并旧 URL 保护规则，生成不含 digest 字段的 canonical payload。
10. 按固定算法计算 SHA、渲染 Markdown/JSON/manifest。
11. 写 `generations/.tmp-<run_id>`，逐文件和目录 `fsync`，rename 为最终 generation。
12. 创建临时相对 symlink 并 `os.replace` 为 `current`，再 `fsync` root。
13. 通过 `current` 回读并校验；清理到只保留当前与上一完整代；写脱敏运行摘要。

## 3. 并发与文件安全

- `.publish.lock` 使用非阻塞 `flock`；网络阶段不持锁。
- stale-run CAS 防止旧运行覆盖新运行。
- root 必须为绝对非 symlink 目录；拒绝 `..`、越界和非普通文件。
- `current` 是唯一允许 symlink：目标必须为相对两段式 `generations/<64hex>`，resolve 后仍在 root；
  其他 symlink 全部拒绝。
- 临时 generation 与 root 同 filesystem，文件 `0640`、目录 `0750`。
- generation 完成前不可见；`current` 是唯一批次可见性切换点。
- Markdown 转义赛事名/原因/URL，URL 只允许 HTTPS。
- 崩溃不得删除 `current` 指向的最后验证 generation。

## 4. canonical 与 SHA

`latest.json` 顶层最小字段：

```json
{
  "schema_version": 1,
  "generated_at": "...",
  "run_started_at": "...",
  "window": {"start": "...", "end": "...", "timezone": "Asia/Shanghai"},
  "coverage": {"future_expected": 0, "orphans": 0},
  "events": [],
  "canonical_payload_sha256": "...",
  "markdown_sha256": "..."
}
```

事件包含 `event_id/year/slug/series_key/name_zh/country_region/local_date/timezone_name/priority/
inclusion_basis/provider/provider_event_id/discovery_outcome/persisted_status/url/last_confirmed_at/
last_checked_at/provider_contract_version/verification_method/verification_scope/reason`。

无环算法：

1. canonical payload 不含任何 digest；
2. 事件按 `local_date nulls last, country_region, event_id` 排序；
3. 用 UTF-8、LF、`ensure_ascii=False`、`sort_keys=True`、`separators=(",", ":")` 编码并计算
   `canonical_payload_sha256`；
4. Markdown 包含 canonical payload SHA，但不包含 Markdown/JSON/manifest 自身 SHA；计算
   `markdown_sha256`；
5. `latest.json` 加入 canonical payload SHA 与 Markdown SHA，计算 `json_sha256`；
6. `manifest.json` 写入两个文件 SHA；manifest SHA 由 verifier 对文件 bytes 复算，不写入自身。

`generation_id = canonical_payload_sha256`。相同 canonical state 重放可复用 generation，但
检查时间变化会形成新 generation；状态语义仍幂等。

## 5. adapter 与存在证据

统一接口：

```python
discover(event_identity, context) -> DiscoveryResult
```

outcome 只允许 `found/listing_reachable/not_published/candidate_unverified/identity_missing/adapter_disabled/
policy_blocked/identity_conflict/duplicate_match/path_unverified/source_error`。persisted status
由 merge 层按 spec 转移表派生；reason code 与 outcome 同名并属于同一封闭 enum。

- JRA：`source_refs.jra` 必须提供 JRADB identity；只接受对应 `accessD`。
- NAR：`source_refs.nar` 提供 `race_id` 或 `kaisai_date+jyo_code+race_no`；只接受
  `TodayRaceInfo/DebaTable`。
- HKJC：`source_refs.hkjc` 提供 `RaceDate+Racecourse+RaceNo`。
- 英国：BHA 日期索引由 `event.local_date` 精确构造 hash URL；provider identity 绑定
  `internal event_id + country_region + local_date`，`verification_scope=date_listing`。应用
  HEAD 2xx 仅为 `listing_reachable`。
- France Galop：允许 registry 保存由官方马场页证明的精确场地 token 映射；当前会议 URL
  真假路径均跳认证，保持 `path_unverified`。
- 美国：当前 Equibase route 使用根级官方 `track_code + event.local_date` 生成
  `RaceCardIndex{TRACK}{MMDDYY}USA-EQB.html`；直接请求 `tvg.equibase.com`，HEAD 2xx/404
  可区分。registry 仍须按 track code 保证与赛场 provider 唯一分流。

选择算法收集全部满足 namespace、region、track identity、contract 的候选：唯一候选调用；零候选
为 `identity_missing`；多候选为 `identity_conflict`。adapter 在一个 provider 内得到多个精确
正向页面时返回 `duplicate_match`。禁止按注册顺序、赛事名或日期打破平局。

route 增加：

- `identity_source=source_namespace|event_fields|root_source_refs`；
- `verification_method=head_exact_path|head_application_entry|get_identity_marker`；
- `verification_scope=event|track_date_racecard_index|date_listing`；
- 可选 `url_fragment_template`，其内容只用于最终人工 URL，不进入 HTTP request target。

`head_exact_path` 的 2xx 是 provider-specific 正向存在证据，404 为 `not_published`；
`head_application_entry` 的 2xx 只能是 `listing_reachable`；`get_identity_marker` 沿用精确 marker
规则。认证跳转、普通非 2xx/404、无法区分真假路径为 `path_unverified`。
`automation_allowed=false` 时 transport 必须为零。

## 6. 故障、日志与容量

- provider 故障不阻止其他 provider，但所有目标必须有逐项状态。
- 枚举、canonical、发布或回读校验失败属于整批失败，旧 current 不变。
- `TaskExecutionLog.payload` 仅写
  `future_expected/orphans/found/listing_reachable/not_available/preserved_previous/blocked/errors/
  by_region/by_provider/duration_ms`。
- 新 task 不复用把 `str(exc)` 写入 detail 的 `_log_failure` 路径。异常分类器只返回固定
  allowlist code；数据库与应用 logger 均不得含原始 exception、request URL、Location、query、
  header 或 body。
- 每次最多目标 500 场、每 provider/host 有独立 request 上限、总耗时受 soft/hard limit 控制；
  超界目标进入 blocker，不截断后伪称全量。
- transport 在批次内按 `method + request URL（不含 fragment）` 去重；所有 BHA 日期索引因此
  只发一次应用入口 HEAD。每 host 保存上次请求单调时钟，按 route 的
  `min_interval_seconds` 等待；Equibase 为 5 秒。等待必须响应 Celery soft timeout。
- HEAD 分支调用 `response.read(0)` 或等价零正文路径；测试以会在任何 body read 时失败的
  response fixture 锁定该行为。
- 告警条件：整批失败、future_expected>0 且 found=0、连续两次 provider error、manifest/SHA
  不一致；本 change 不接外部通知。

## 7. Celery 与发布

- schedule 为 `crontab(minute=30, hour="6,18")`，`CELERY_TIMEZONE=Asia/Shanghai`。
- task 不写 `CELERY_TASK_ROUTES` 项，投递到普通 worker 默认消费的 `celery` 队列；集成测试与
  rollout 必须通过 route/inspect/消费 smoke 验证，不依赖未记录生产覆盖。
- 代码可带 schedule 发布，但 `P0_RACECARD_URL_DISCOVERY_ENABLED=false`。
- 先做 flag-off smoke，确认 transport=0/file_write=0。
- 后续发布授权后创建宿主目录、备份 `.env`、设置普通 worker bind mount、部署并单次受控运行。
- 每个 provider route 独立启用；总开关不能覆盖 provider contract。
- 回滚先关 flag，再恢复镜像/compose；不需数据库恢复。
