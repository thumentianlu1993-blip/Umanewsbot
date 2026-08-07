# `fix-race-calendar-default-date-window` 发布报告

> 发布日期：2026-07-28（UTC）；本文仅记录已发生的发布事实证据。

## 发布门禁与合并

- 授权后 staging 校验：重算 `review_fingerprint.py`，`content_manifest_sha256`
  `632eb5258cd9a5daf9aaa1fc2470951a020bd12bf719627f7ef845b7b6b66e57` 与 approved content
  hash 逐字节一致，`head` 为 approved parent `7385f59ab87bcce5193f3313ecca6809b165ad89`；
  `FINGERPRINT_SHA256` 与冻结值的差异仅来自 fetch 后 upstream 元数据（`branch.ab +0 -4`），
  受审内容零漂移。`review_release_transition.py index` 返回 `INDEX_TRANSITION_OK`。
- 期间 `origin/main` 推进 4 个提交（PR `#42` 赛事新闻质量），其 `views.py` hunk 位于
  `public_news_feed`（3663 行附近），与本任务日历函数无重叠。
- 实现提交 `64dff42c`；PR `#43` 合并提交 `c8508b4eddd57c6d3dc397397a78f04d24a707ce`。
  合并前 PR 与 main 冲突仅位于 `docs/current_state.md`/`docs/project_status.md`（双方均在
  文件顶部追加条目），本地合并 `f5642138` 保留双方条目（新条目在前）解决；`views.py`
  自动合并干净。合并树验证：窗口聚焦 + responsive 62/62 OK；`test_realtime_race_results`
  仍为改动前既有的 9 个失败；Django check 通过。

## 生产部署

- 服务器 `root@47.239.167.86:/opt/umanewsbot`，compose `docker-compose.prod.lowcost.yml`。
- 部署前状态：`main@8440b897`，6 容器 Up，healthz 200；服务器 12 个 deploy 脚本本地改动
  经核实全部为权限位变化（0 行内容差异），按先例保留。
- 写前恢复点：`.env.backup.pre-race-calendar-20260728T200132Z`（mode 0600）；回滚镜像
  `umanewsbot:rollback-pre-race-calendar-20260728T200132Z`（来自旧 `umanewsbot:prod`
  = `02f2f7d16df1`）。本任务无迁移、无配置变更、无业务数据写入，按轻量代码发布先例未做
  数据库备份。
- `/opt/umanewsbot` `git pull --ff-only`：`8440b897 -> c8508b4e`。
- `./deploy_lowcost.sh` 一次通过：celery drain `active=0/reserved=0`；web 重建；
  `migrate` 显示 `No migrations to apply`；`collectstatic` 1 copied / 130 unmodified /
  360 post-processed；worker/beat 重建；未发生上次部署的 SIGKILL 或 nginx 502 持续故障。
- 新生产镜像 `umanewsbot:prod` = `b7b797467022`。

## 部署后验证（全部实际执行）

- 6 容器 Up（web healthy）；`manage.py check` 0 issues；`migrate --plan` 为空。
- 回环与公网 `healthz` 均 `200 {"status": "ok"}`。
- 公网 `/races/` 200：日期栏精确为 11 个实际比赛日（2026-07-19、07-24、07-25、07-26、
  07-28、**07-29（锚点/今天）**、07-30、07-31、08-01、08-02、08-07）；全页恰好一个
  `data-calendar-anchor`（`class="today anchor"`、`aria-current="date"`）；28 张赛事卡 ≤40。
- 显式入口：`direction=past&cursor`、`year=2025`、`q=宝塚`、`region=japan&grade=g1` 均 200；
  cursor 模式无 `data-calendar-anchor`、无定位脚本。
- 真实浏览器：390px 锚点在日期轴可视区（scrollLeft 354）、纵向 scrollY=0、徽标 42×42；
  1440px 11 日全可见、无横向 overflow；控制台无与本改动相关错误（仅 HTTP 访问的 COOP
  提示，与本改动无关）。
- 日志：web/worker 无 error/traceback；nginx 在 web 重建窗口出现一条瞬时 502
  （Googlebot 请求详情页，connection refused），web healthy 后已恢复。
- 零迁移、零配置变更、零业务数据写入；所有功能开关保持部署前状态。

## 回滚点

- 代码：`/opt/umanewsbot` `git reset --hard 8440b897` 后重跑 `./deploy_lowcost.sh`，或
  `docker tag umanewsbot:rollback-pre-race-calendar-20260728T200132Z umanewsbot:prod`
  后重建容器；不恢复数据库（本任务无 schema/数据变更）。
