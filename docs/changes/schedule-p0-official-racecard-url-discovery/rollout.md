# P0 官方出马页面 URL 定时发现 rollout

## 1. 当前门禁

既有实现曾完成代码 review，但用户要求补齐 provider route 后受审内容将变化，旧 fingerprint
不再是发布基线。provider route TDD、增量实现、v3 bounded proof 与同一代码 reviewer

- commit/push/PR；
- 部署、修改生产 `.env` 或创建宿主目录；
- 启用 Celery 定时任务。

目标 route 状态：

- Equibase：启用 `HEAD` 精确静态路径验证；
- BHA：启用日期索引应用 HEAD，输出 `listing_reachable`；
- France Galop：保留模板但认证跳转不可验证，保持 blocked；
- JRA/HKJC：未来接入、当前窗口无赛事；NAR 保持 robots blocked。

## 2. 实现完成后的候选证据

发布候选必须提供：

- approved parent、受审 fingerprint、content manifest SHA；
- 聚焦/回归测试、Django check、迁移漂移、Compose、strict compatibility 与 diff check；
- fake transport dry-run 产物 SHA；
- provider route 表：authority、host/path、automation flag、证据有效期、稳定身份字段；
- 功能关闭时 `network_requests=0 / file_writes=0`；
- 预期修改文件、无 migration、业务表零写证明。

上线候选必须先完成一次有界 no-write provider proof：当前 6 场预期
`confirmed_racecard=2/listing_reachable=3/暂无=1`。历史证据不能代替上线时实测。

关闭 `TaskExecutionLog` 漏计 finding 后，本地 bounded proof v3 已于
`2026-07-27T05:49:39Z` 至 `05:49:48Z` 完成：精确 3 次 HEAD、BHA 200、
Equibase DMR/CNL 均 200、body bytes 0、Equibase 间隔 7 秒；结果为
`found=2/listing_reachable=3/暂无=1`。未调用 task，业务数据库、`TaskExecutionLog` 和
`current` 写入均为 0。证据：

- `provider_no_write_proof_20260727_v3.json`，SHA-256
  `7e4886a8ff9f02a9c39ef1e8e3e414692ad61528e184dbadb2d4b3c37b9f4b94`；
- `provider_no_write_proof_20260727_v3.manifest.json`。

首次 proof 与 v2 均作为不可变历史证据保留；首次绑定 review finding 修复前代码，v2
绑定后又发生 task 日志修复，因此已由 v3 逐级 supersede，均不能作为发布依据。

v3 使用无自引用绑定：联网前冻结 fingerprint
`199785de6117c490b569b3cc0fa2d50ce9dbe10f05cb6d3dca0c950e5c736c21` 和 content manifest
`103f734252d8659009cc238a10b64f18a1465521fac9398397a52634f907f8a2`，并单独保存
service、task、registry 三个 SHA。联网后只允许新增 v3 artifact/manifest 及更新本 change
的 rollout/tasks/test_cases 和三份状态/运维文档；reviewer 必须核对最终差异未触及执行代码
或 registry。

精确 proof 合同：

- 输入窗口冻结为 proof 启动时的 `[start, start+7d)`，并保存 6 个目标的内部 event ID、
  地区、本地日期和受审外部身份；
- 只允许 `HEAD`：BHA 去重后的
  `www.britishhorseracing.com/racing/fixtures/upcoming/` 1 次，Equibase DMR/CNL 精确静态路径
  各 1 次，总请求上限 3；Equibase 两次请求间隔至少 5 秒；
- France Galop/JRA/NAR/HKJC transport=0；不得 follow redirect，不得读取响应 body；
- proof 不调用 Celery task、不创建 `TaskExecutionLog`、不写业务数据库、不写或切换
  `current`；只在隔离 proof 目录写不可变 JSON/manifest；
- receipt 保存 provider、method、host、path template ID、响应类别、时间和候选 URL SHA-256，
  不保存 header/body/cookie/token；artifact 保存 registry SHA、contract digest、HEAD/code
  fingerprint、目标数、逐 provider 请求计数、结果计数、数据库写入数 `0`、current publish
  数 `0` 和 artifact SHA；
- Equibase contract digest 必须绑定 `tvg.equibase.com/robots.txt` 的 404 状态、证据时间与
  body SHA；若误用 `www.equibase.com` robots SHA，proof 在 transport 前失败；
- 任一超预算、间隔不足、身份缺失、状态异常或 digest 不一致即 proof 失败，不把部分结果计入
  上线覆盖。

固定顺序：

`provider route TDD/实现 -> 精确 no-write bounded proof -> 关闭 proof findings -> 同一代码
reviewer 审核最终代码/registry及直接修复路径 -> 冻结 fingerprint -> 用户针对该精确版本发布
授权 -> 默认关闭部署 -> 单次生产验证 -> 按已获授权启用 06:30/18:30 定时任务`。


最新限定复审使用原生命令
`codex review -c 'sandbox_mode="read-only"' --uncommitted`，session
`019fa221-d2f1-7262-8d38-aad50b634696`。两项原 finding 均关闭，且无直接 P0/P1 回归；
三个新 P2 依限定复审规则仅列后续建议：generation 目录名与 canonical SHA 交叉校验、
HEAD 接受完整 2xx、认证 3xx 的 outcome 归类。文档回写前批准候选为：

- parent `a59956b327157d29630fab1f1c98ba9c9cacfed0`；
- fingerprint `1f665032d5bfc0d19b4f2e9885bd30f2718415de0cdee0c8a441e6b83e192959`；
- content hash `1df171afd380238c205e72d123f8ec3e1bd3e9021267cc4d9dc117c02c119642`。

本段及同步状态文档属于审核后事实回写，必须由同一 reviewer 再做纯文档限定复审，并以其

## 3. 默认关闭部署


1. 核对生产 HEAD/服务/队列/现有任务。
2. 备份 `.env`，记录回滚镜像。
3. 创建 `/opt/umanewsbot/runtime/upcoming_racecard_urls/`，设置最小权限。
4. 部署代码与 worker bind mount，保持
   `P0_RACECARD_URL_DISCOVERY_ENABLED=false`。
5. 执行 Django、migration、Celery、healthz 检查。
6. 运行 flag-off smoke，证明无网络、无文档写入。

## 4. route 与任务启用

启用分两层，均需在发布时列明：

- 总任务开关：控制 task 是否执行；
- provider route：控制某个官方入口是否允许 transport。

推荐先执行一次手工受控 task：

- 报告精确 `[start, end)`；
- 核对 future expected P0 清单与有界 orphan appendix；
- 核对每场 URL/暂无及原因；
- 通过固定 `current/latest.md` 人工入口读取，并用 manifest verifier 校验完整 generation；
- 重跑一次，验证幂等和旧 URL 保护；
- 重建 worker 后确认文件仍在。

让 beat 在上海时间每日 06:30/18:30 触发。
未获准/受阻 provider 保持 `adapter_disabled` 或 `policy_blocked`，不能暗中联网。

## 5. 监控

每日检查：

- 两个时点是否都有成功或明确 noop 日志；
- expected 与文档行数是否一致；
- found、暂无、preserved_previous、blocked、errors 的变化；
- provider 连续失败、全量 found=0、SHA 不一致；
- 文件最后更新时间、权限与磁盘空间。
- `current` 只指向合法完整 generation，manifest/JSON/Markdown SHA 全部一致；
- beat 投递的任务确实被普通 worker 的 `celery` 队列消费。

本 change 只定义告警条件，不新增 QQ、邮件或其他外部通知。

## 6. 回滚

1. 设置总任务开关 false，并重启 worker/beat 使配置生效。
2. 确认后续 task 为 disabled、无 provider 请求。
3. 恢复旧镜像和 Compose；无需数据库 rollback。
4. 保留 `current` 指向的最后已知完整 generation 作为人工参考，除非用户明确要求移除。
5. 若文档损坏，依据 JSON/Markdown SHA 判定不可接受，恢复发布前备份或等待下一次受控重建。

## 7. 非影响

- 不写赛事、出马、赛果、新闻或 QQ 数据。
- 不公开 URL 文档。
- 不启用 race-live、lifecycle 或其他调度。
- 不保存官方页面内容。
