# P0 官方出马页面 URL 定时发现测试用例

## RED 计划

实现前先新增测试，并实际确认以下核心能力因尚不存在而 RED：

1. `06:30/18:30 Asia/Shanghai` 的 beat schedule。
2. 精确 P0 全量枚举、有界 orphan 审计及半开七天窗口。
3. 同一赛事新 URL 替换、同 URL 重放幂等。
4. transient error 保留上轮 URL。
5. stale 并发运行不得覆盖较新运行。
6. generation bundle 任一崩溃点只暴露上一完整代或下一完整代。
7. disabled/blocked provider 的 transport 为零。
8. JRA/NAR/HKJC adapter 契约在无当前赛事时仍可验证。
9. Equibase `track_code + local_date` 能生成精确 index，HEAD 200/404 分别为
   `found/not_published`，transport 不读取正文。
10. BHA 日期 hash URL 的 HEAD 只检查无 fragment 的应用入口，结果为
    `listing_reachable`，不得升级为 `found`。
11. France Galop 认证跳转及真假路径不可区分时 fail closed。

## 实际 RED / GREEN（2026-07-27）

- provider route 增量 RED：`P0RacecardProviderTests` 17 项真实运行 `exit 1`，
  `11 passed / 4 failed / 2 errors`。失败精确对应尚不存在的
  `LISTING_REACHABLE`、event/root identity、HEAD method、零正文 transport、批内去重/间隔、
  contract digest 校验和仍关闭的 BHA/Equibase tracked route；既有 11 项通过，非环境失败。
- provider route 增量 GREEN：同一 17 项 `17/17`；完整 discovery `44/44`；racecard/lifecycle
  回归 `79/79`，realtime 安全子集 `25/25`。主代理在 macOS 复跑时默认 `/var` 临时目录因父级
  symlink 被 artifact 安全门禁正确拒绝；改用真实 `/private/tmp` 后完整 `44/44`，未放宽防护。
- 最新 code review 三项 P2 回归 RED：摘要计数、可信 provenance、Markdown 分级 4 项真实运行
  `exit 1`，精确为 `1 failure / 3 errors`：缺 `listing_reachable` 独立计数、`DiscoveryResult`
  验证元数据、preserved/checked provenance 与中文链接标签；非环境失败。
- 配置 RED：`P0RacecardUrlDiscoveryConfigurationTests` 共 5 项，首次有效运行
  `exit 1`，其中 4 项因新 setting、beat entry、`.env.example` 和 Compose mount 尚不存在
  失败；默认 `celery` 队列检查 1 项通过。
- 模块/窗口 RED：service contract 与 `enumerate_event_snapshots` 尚不存在时分别
  `exit 1`；不是环境或测试数据错误。
- 并发 RED：较晚失败运行在锁外读取旧 previous，曾把较早运行刚确认的 URL 清空；
  新增线程编排测试精确失败为 `url is None`。
- provenance RED：保留旧 JRA URL 时曾错误绑定到新失败来源 `jra_mirror/test-v2`；
  新增测试精确失败为 confirmed provider 不等于 JRA。
- 首次 code review 的 P1/P2 RED：CGNAT `100.64.0.1` 未被旧 DNS 条件拒绝；service/task
  曾吞掉 `SoftTimeLimitExceeded`，且日志保存异常会遮蔽原 soft timeout。修复后要求每个 DNS
  地址 `is_global is True`，两层显式重抛，task 只尽力写固定脱敏失败终态。
- 限定复审 P2 RED：明文/编码/双编码 dot segment、encoded slash/backslash 曾通过 path
  allowlist；保留 URL 的本轮错误曾漏计，空 checked provider 曾回退到旧确认 provider。
  修复后路径逐层解码 fail closed，errors 按本轮 error outcome 计数，空检查来源统一
  `unresolved`。
- provider route 首次 review P2 RED：`listing_reachable` 曾误计入“暂无”；sidecar 未记录
  `verification_method / verification_scope / source_url`；Markdown 曾把 BHA 日期索引写成
  泛化“官方页面”。4 项聚焦测试取得 `1 failed / 3 errors` 后修复并 `4/4` GREEN。
- 限定复审补充 RED：service 已有 `listing_reachable` 计数，但 task 日志 allowlist 静默丢弃；
  目标测试要求 `TaskExecutionLog.payload["listing_reachable"] == 3`。
- 上述日志 RED 精确失败为 `KeyError: listing_reachable`；修复后 task 六项测试 `6/6`、
  discovery `47/47`，成功与固定失败 payload 均保留该计数。
- GREEN：完整 discovery `47/47`；discovery + racecard/lifecycle 组合 `126/126`；realtime
  安全/配置/fixture 受影响子集 `25/25`。
- 完整 `stable.test_realtime_race_results` 实跑 `166` 项为 `157 passed / 9 failed`。9 项均在
  既有 `RaceLiveTheRacingApiFreeRunnerTests`：fixture 固定 `2026-07-20`，runner 读取当前
  `2026-07-27` 后返回 `checkpoint_claim_expired/mismatch/rate_limited`；无本 change 堆栈。
- Django check、迁移漂移、compile、Compose 无 env 解析、registry SHA、旧规格流程 strict
  `37/37` 与 `git diff --check` 通过。

## 单元测试

### 时间与枚举

- aware `race_datetime == start` 纳入，`== end` 排除。
- 英国/法国/美国跨 DST 的 source local date 转换正确；Asia/Shanghai 调度不随 DST 漂移。
- `local_date` 超集不猜 `local_start_time`。
- P0 纳入；P1、P2、featured-only 排除。
- cancelled 排除；draft/hidden、series pending 不静默排除并带审计状态。
- 缺全部时间身份的 P0 只在窗口涉及年份且 scheduled/postponed 时进入 orphan appendix，
  不进入 future denominator。
- 历史年份、远期年份、finished 空时间不进入 orphan；跨年窗口允许两个涉及年份。

### 状态合并

- 首次无页面写 `not_published`/“暂无”。
- 同一 URL 重跑不新增行，只更新时间。
- 新 URL 精确匹配后替换旧 URL。
- source error、429、5xx、超时或后续 404 保留已确认 URL并标记未验证。
- identity conflict/重复命中不替换旧 URL。
- 离开窗口的事件在成功新快照中移除。
- 旧运行在锁内检测到更新 `run_started_at` 后拒绝发布。
- 十一个封闭 adapter outcome（含 `listing_reachable/identity_conflict/duplicate_match`）到 persisted status 的
  完整转移表、reason code 与计数归属逐项锁定；未知字符串拒绝。

### 来源与安全

- provider/region/identity/contract version 缺任一项则 fail closed。
- 仅接受 HTTPS allowlisted host/path；拒绝 userinfo、非默认端口、IP、DNS/redirect 越界、
  超长 URL。
- `automation_allowed=false`、过期 contract、robots/terms blocker 时 request count 为零。
- 超时、响应大小、redirect、每 host 请求数和总预算受限。
- JRA `accessD`、NAR `DebaTable`、HKJC 参数化 URL 使用固定官方 fixture 精确匹配。
- 日本按 `source_refs.jra/nar` 唯一分流；美国按 namespace/track contract 唯一分流；零/多候选
  fail closed。
- 英国、法国、美国 fixture 分别覆盖正向 identity marker、官方明确 not published、普通 404
  为 path_unverified、duplicate；第三方 URL 被拒。
- 只按模板构造且未执行受审 verification 得到 candidate_unverified，绝不得到 found。
- HEAD transport 发送 `HEAD`、不读取响应正文；fragment 不进入 request target。
- 同一批多个 BHA 日期 URL 对无 fragment 应用入口去重为 1 个 HEAD；Equibase 两个不同路径
  保持 2 个 HEAD，单调时钟间隔不少于 5 秒。
- registry route 缺 robots evidence SHA、method、请求上限、最小间隔或 contract digest 时
  fail closed。
- robots evidence origin 与实际请求 scheme/host/port 不一致时 transport=0；`tvg` route
  不得使用 `www.equibase.com` robots SHA。404 evidence 的状态、时间或 SHA 不匹配同样关闭。
- Equibase DMR/CNL 正向 fixture、伪场地/错误日期 404 fixture 覆盖精确路径判定。
- BHA 有效/无效日期的应用 HEAD 相同，证明该 route 只能输出 listing_reachable。
- France Galop 有效/伪路径相同认证跳转 fixture 均不得输出 URL。
- 无网络测试以 fake transport 完成，测试进程不能访问互联网。

### 文件

- canonical payload 的排除字段、UTF-8/LF、排序、separators 和无环 SHA 顺序有 golden bytes。
- generation 三文件 SHA 可复算，事件数/状态一致。
- 每个 file fsync、generation dir fsync/rename、current symlink replace、root fsync 崩溃点均
  证明 current 只指向完整上一代或下一代。
- root/任意非 current symlink、非法 current target、相对越界、非普通文件拒绝。
- 只保存 URL 与最小元数据；fixture body、马名、骑师、cookie、header 不出现在文件或日志。
- 文件权限与稳定排序正确。

### task 与配置

- feature flag 默认 false；关闭时数据库/provider/file transport 都为零。
- task summary 与应用日志只记录脱敏计数/fixed code；query token、userinfo、Location、正文、
  header、嵌套 `str(exc)` 均不得出现。
- task annotation 有 soft/hard time limit；不写显式 route，真实投递到普通 worker消费的
  `celery` 队列。
- schedule 精确为每天 `6,18` 时 `30` 分。
- Compose worker bind mount 指向持久化宿主目录；beat 不需要写挂载。
- `.env.example` 默认关闭且路径一致。

## 集成与回归

- 临时 PostgreSQL/SQLite 数据构造跨五地区 P0/P1，生成完整 latest 文档。
- 两次运行和模拟并发运行验证幂等与 stale CAS。
- 容器配置检查 mount、环境变量、worker/beat 路由。
- Celery route/inspect 与 worker queue smoke 证明 beat 投递可被普通 worker 消费。
- `TaskExecutionLog` 写前/写后计数正确，业务表计数与字段零变化。
- 相关 racecard/realtime/lifecycle 测试回归。

## 最终验证

- 聚焦测试全绿。
- `python manage.py check`。
- `python manage.py makemigrations --check --dry-run`，预期无 migration。
- Compose config 检查。
- `python -m compileall` 覆盖新增模块。
- 兼容性执行 `旧规格流程 validate --all --strict`，不把它作为新工作流门禁。
- `git diff --check`。
- 独立 reviewer 实际运行 Codex 原生只读 review。
