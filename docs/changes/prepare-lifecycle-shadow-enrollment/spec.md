# Lifecycle shadow 纳管准备规格

## 1. 目标

本 change 为既有赛事生命周期阶段 A 建立一条可重复、可审核、默认零数据库写入的 shadow
纳管准备链。它不新增状态机、赛事模型、Celery 调度器或外部数据源，只解决以下上线前缺口：

1. 从明确的赛事 ID 生成冻结的 enrollment manifest，而不是由操作人手工拼 JSON 和哈希；
2. 让同一份 manifest 的 dry-run 与 apply 使用同一套严格解析、时区、资格和数据库漂移校验；
3. apply 只创建或精确重放 `mode=shadow` 的 control，不允许借本入口进入 enforce；
4. 在全局仍为 `false/off` 时完成 control 纳管和验证，后续再以独立授权打开 shadow；
5. 形成可供人工审核的逐场状态、时间、时区、下一次刷新和预期决策证据。

## 2. 当前生产事实

只读盘点时间为 `2026-07-31`（项目时区），生产 revision 为
`23abf5289f9dac8310c4ba0300b0e925e72d3f40`：

- `RACE_EVENT_LIFECYCLE_ENABLED=false`；
- `RACE_EVENT_LIFECYCLE_MODE=off`；
- control `0`、transition `0`；
- 未来 90 天已发布重点赛事 `172` 场，`race_datetime` 非空 `0`；
- `local_start_time` 非空 `9` 场；
- 未来 45 天 85 场中，79 场满足地区时区合同，6 场不满足；
- 已确认的错误样本包括美国 event `428/434/435/436` 和英国 event `938/940`，
  它们的 `timezone_name=Asia/Shanghai`，不得纳管。

第一次只读查询因使用不存在的 `name_zh` 字段在 ORM 解析阶段失败；修正为
`chinese_name` 后成功。两次查询均未写数据库。

## 3. 范围

### 3.1 包含

- 新增 lifecycle enrollment manifest 的只读 prepare 命令；
- manifest schema v2、严格 loader、canonical payload 和原始文件 SHA-256；
- 精确 event ID、最多 20 场、固定 `shadow`；
- 冻结赛事资格、状态、地区、时区、日期/时间和 control 写前基线；
- 美国逐场 `America/*` allowlist；
- dry-run/apply 共用 preflight 和漂移校验；
- 单事务、排序加锁、整批成功或整批零写；
- 相同 manifest 精确 replay；
- 生成机器可读 summary，供后续人工批准与生产 observation 使用。

### 3.2 不包含

- 不修改 `RaceEvent.status`；
- 不启用 `RACE_EVENT_LIFECYCLE_ENABLED` 或把 mode 改为 shadow；
- 不修改 Beat 周期、队列或 worker；
- 不调用 The Racing API、JRA、HKJC、BHA、France Galop 或其他 provider；
- 不补写 `race_datetime`、`local_start_time` 或时区；
- 不启用 race-live scheduler，不处理 race-live 积压；
- 不实现 enforce、新闻软门禁、赛前刷新或赛果同步；
- 不新增模型或 migration；
- 不自动发现并纳管全部重点赛事。

## 4. 纳管资格

prepare 时每场必须同时满足：

1. 明确传入 event ID，ID 为正整数、无重复，批次为 1–20 场；
2. `RaceEvent.is_key_race=true`；
3. `visibility_status=published`；
4. `status=scheduled`；
5. `country_region` 属于日本、香港、英国、法国、美国五地区；
6. `timezone_name` 满足地区合同；美国必须由 manifest 明确给出非空逐场 allowlist，
   且当前时区在 allowlist 内；
7. `local_date` 非空；
8. `manual_lock_flags` 为空；
9. 不存在 lifecycle control，或只存在与同 manifest 完全一致的 replay control；
10. 不把 `local_start_time` 当成绝对时间；只有 aware `race_datetime` 才进入有时间路径。

任一项不满足时整批 fail closed。不得把错误时区改成服务器时区、项目时区或地区默认值。

## 5. Manifest v2

顶层至少包含：

- `schema_version=2`；
- `generated_at`、`expires_at`（aware UTC，默认有效期 24 小时）；
- `approved_commit`（40 位小写 Git OID）；
- `mode=shadow`；
- `events`，按数字 event ID 升序；
- `content_sha256`：对不含该字段的 canonical JSON payload 计算；
- 文件原始字节 SHA-256：由命令输出，不写入自身。

每场至少冻结：

- `event_id`、`event_updated_at`；
- `region`、`timezone_name`、`allowed_us_zones`；
- `status`、`priority`、`is_featured`、`visibility_status`；
- `eligibility` 三个布尔值；
- `local_date`、`local_start_time`、`race_datetime`；
- `enrollment_schedule_hash`；
- `expected_control`：`absent`，或 replay 所需的完整 manifest SHA、mode、generation、
  `next_refresh_at` 和 `manifest_data` 摘要；
- `predicted_decision` 与 `predicted_next_refresh_at`。

JSON 必须为 UTF-8、拒绝 BOM、NaN/Infinity、重复 key、未知顶层/赛事字段、非普通文件、
symlink 和超过 1 MiB 的输入。canonical JSON 使用 key 排序、UTF-8、
`ensure_ascii=false`、紧凑分隔符和末尾单个换行。

## 6. Dry-run 与 apply

- prepare 只读数据库，只在操作人指定且原本不存在的 artifact 目录写文件；
- reconcile 默认 dry-run，必须完整读取并验证 v2 manifest；
- dry-run 与 apply 调用同一个 loader、资格验证、时区验证、过期验证和 DB CAS preflight；
- dry-run 输出 `would_create/replay/error`、逐场预期决策及 next refresh，数据库零写；
- v1 只保留历史 dry-run/read-only compatibility；任何 v1 `--apply` 无条件非零、零写拒绝；
- apply 必须同时提供 manifest 文件、原始文件 SHA、expected commit 和显式
  `--confirm-shadow-enrollment`；
- v2 apply 在任何锁或写入前必须读取当前进程 settings，并且只接受
  `RACE_EVENT_LIFECYCLE_ENABLED is False` 且 `RACE_EVENT_LIFECYCLE_MODE == "off"`；
  `true/shadow`、`true/off`、`false/shadow`、`true/enforce` 及无法判定均零写拒绝；
- apply 在 `transaction.atomic()` 内按 event ID 排序锁定 event/control，重新验证全部冻结值；
- 任何漂移使整批回滚；不得用旧 eligibility 强行纳管已取消、未发布或不再重点的赛事；
- apply 只允许创建 `mode=shadow` control；现有不同 manifest control 一律拒绝，不做更新；
- 相同 manifest 的完整一致 control 返回 replay，不新增记录、不改变 generation。

## 7. Shadow 开启门禁

control apply 与功能启用是两个授权：

1. 先在生产 `false/off` 下 apply 精确 manifest；
2. apply 前同时核对 Beat/普通 worker 的实际环境也是 `false/off`，且没有 lifecycle
   active/reserved、有效 claim；不满足即停止；
3. 独立 verify control 数、mode、manifest SHA、generation、next refresh 和业务表零变化；
4. 用户对精确赛事集合、manifest SHA、观察窗口和当前部署 revision 再次授权；
5. 才能显式设置 `RACE_EVENT_LIFECYCLE_ENABLED=true`、
   `RACE_EVENT_LIFECYCLE_MODE=shadow` 并只重建必要服务；
6. shadow 只能写 proposal/audit，不能改公开状态、赛果、新闻或 QQ。

当前没有任何有 `race_datetime` 的未来样本，因此首批只能验证无时间的当地次日规则。
`scheduled -> running -> finished` 有时间路径必须等可信时间进入数据库后另行准备样本并授权。

## 8. 验收

- 手工 JSON 不再是推荐生产入口；
- 同一 manifest 的 dry-run 与 apply 对合法/非法输入结论一致；
- v1 apply 永久零写拒绝，只有 v2 能进入首次生产纳管；
- v2 apply 在非严格 `false/off` 的所有组合下零写拒绝；
- 错误地区时区、美国空 allowlist、资格/时间/control 漂移全部零写拒绝；
- shadow control 整批创建或整批不创建；
- replay 不修改 generation、next refresh 或审计计数；
- 功能关闭时 scanner/task 仍不处理；
- shadow 开启后只对 manifest 内 control claim；
- proposal 不改变 `RaceEvent.status`，不触发 race-live、provider、新闻或 QQ；
- 禁用功能后已排队任务在事务内 fail closed。
