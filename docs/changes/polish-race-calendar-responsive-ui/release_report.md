# `polish-race-calendar-responsive-ui` 发布报告

## 发布结果

- 状态：生产部署与真实浏览器验收通过。
- PR：`#17`
- merge/生产 HEAD：`3772256e606e3f62081eecec162fecedbd1aa23d`
- 上一生产 HEAD：`438ab6a14f9665fd77318d8c12f8bc5a3ca63690`
- 生产镜像：
  `sha256:90c98db7eb048949507bbc3d335ed7b989dc9ce6dab1d3576a5242c2c4d10e49`
- 编排文件：`docker-compose.prod.lowcost.yml`

## 恢复点

- 数据库：
  `backups/db/pre-race-calendar-responsive-20260724T173452+0800.sql.gz`
- 数据库大小：`242013429` bytes
- 数据库 SHA-256：
  `2ed8f391b4b37e3590e22ad558ce6237a53ded073f6a5920aafacad8d8f4ce7f`
- 数据库校验：非空、`gzip -t` 通过、权限 `0600`
- 环境：
  `.env.backup.race-calendar-responsive-20260724T173452+0800`，权限 `0600`

## 部署与验证证据

- 发布前 Celery active/reserved 为空，外部导入和锁均为 `0`，historical runner 为
  `migration_safe`。
- 无待应用 migration；Django check 为 `0 issues`，migration drift 为
  `No changes detected`。
- collectstatic 为 `131 unmodified / 360 post-processed`。
- `web / worker / beat / race_live_worker` 四服务镜像一致。
- 内外 healthz、首页、赛事日历和后台登录入口均为 HTTP 200。
- 生产 CSS：`/static/stable/public.e7932bf85b07.css`。
- 近 10 分钟四个应用服务日志未命中严重错误。

## 视觉验收

- 1440px：月份可直接识别，跨月日期无歧义；徽标为 `42×42px`，无横向溢出。
- 390px：G1、G2、JPN1 在长标题卡片中保持 `42×42px`，标题换行，today 状态保留，
  页面无横向溢出，控制台无错误。
- 320px：抽检徽标仍为 `42×42px`，`scrollWidth=clientWidth=320`。

## 部署过程说明

旧 Compose 容器没有新版 preflight 要求的 Docker health metadata，导致首次
`deploy_lowcost.sh` 在构建前停止；实际 HTTP、PostgreSQL、Redis 和 historical runner
状态均已独立验证。随后严格按脚本第 19–28 行执行等价序列。新镜像构建后，drain 脚本因
worker 已在备份阶段安全停止而无节点响应；基于停止前两次 active/reserved 为空证据，从
下一安全步骤继续并完成四服务强制重建。

## 回滚边界

- 代码父提交：`438ab6a14f9665fd77318d8c12f8bc5a3ca63690`
- 旧镜像标签：
  - `umanewsbot:rollback-pre-calendar-web-20260724T173452`
  - `umanewsbot:rollback-pre-calendar-worker-20260724T173452`
- 本次无迁移或业务数据写入；正常代码回滚不恢复数据库。只有确认数据损坏时才使用上述数据库恢复点。
