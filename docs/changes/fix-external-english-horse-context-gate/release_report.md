# 英文单词型马名语境门禁发布证据

## 结论

`fix-external-english-horse-context-gate` 的代码已合并并部署到生产，四个应用容器运行同一镜像，
基础服务与只读业务 smoke 均通过。生产配置保持
`ENGLISH_TERM_CONTEXT_MODE=shadow`，因此新三分类已部署但尚未改变实际发布门禁；切换
`enforce` 需要独立明确授权。

## 受审版本与本地验证

- reviewed fingerprint：
  `7ff685325de93578f0131a73746a50f23d627f5cd1dbb266f2afee372eb9aabd`
- content hash：
  `53d957ed41e6e0e5e0e68f4331cf9d0078a563129fbb9a995c845895f381a2cb`
- review session：`019f9252-e50c-7d30-8e49-d6765919a51d`
- review 结论：`CORE APPROVED`
- 本地验证：完整矩阵 `333/333`、语言专项 `77/77`、Django check、
  `makemigrations --check --dry-run` 与 `git diff --check` 通过

两个非核心 P2 继续 deferred 到后续 change
`fix-term-discovery-visible-occurrence-aggregation`，未在本次发布扩大实现范围。

## 发布链路

- release commit：`1c34a00715aa3a0ac49153553622360afa10e049`
- PR：[Umanewsbot #14](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/14)
- merge commit / production HEAD：
  `2a3c249f4ffce2e97a2133f9a932234f74ec1e1e`
- 生产目录：`/opt/umanewsbot`
- 生产 Git：`97a38cf5 -> 2a3c249f`
- 部署命令：`bash ./deploy_lowcost.sh`
- 数据库迁移：无

部署脚本重建 `web/worker/beat`；随后使用低成本 Compose 精确 force-recreate
`race_live_worker`。最终四应用镜像一致：

`sha256:316e4563b306ca70bde8e55a78c79d48de1ac8ca09d7259a8a7d0b4f5044c364`

## 生产验证

- web healthy；
- Django check 与 `makemigrations --check --dry-run` 通过；
- 容器内、外网与 `www` healthz 通过，首页和 admin login 均返回 HTTP 200；
- Celery 两节点 ping 正常；
- 部署前 active/reserved 为空；部署后自然 netkeiba crawl 为 active，reserved 为空；
- 外部导入 `started=0`、locks `=0`；
- 磁盘可用 `54G`。

## article 9595 只读 dry-run

在生产进程内临时 override `enforce`，仅执行 dry-run：

- `workflow=published`
- `automation=auto_published`
- `horse_alert_codes=[]`
- `Logician`：`confirmed_horse`，已有正式译名，`needs_preserve=false`
- `Africa`、`East`：`common_word`，`needs_preserve=false`

本次未保存、未重处理、未发通知、未修改生产数据。该结果只证明受控样本在
`enforce` 计算下的预期行为，不代表生产已启用 `enforce`。

## 当前运行边界

生产 `ENGLISH_TERM_CONTEXT_MODE=shadow`。代码已上线，但新分类尚未改变实际门禁。
任何 `shadow -> enforce` 切换都必须作为独立生产变更重新授权、执行并验证，不属于本次
evidence-only closure。

## 回滚与复核

如需代码回滚，先取得独立授权，再将生产代码恢复到 `97a38cf5`，使用
`docker-compose.prod.lowcost.yml` 重建 `web/worker/beat/race_live_worker`。回滚后验证：

1. 四应用镜像一致，web healthy；
2. Django check 与 migration drift 通过；
3. Celery 两节点 ping 正常，active/reserved 符合自然任务状态；
4. 内外及 `www` healthz、首页和 admin login 返回 HTTP 200；
5. `ENGLISH_TERM_CONTEXT_MODE=shadow` 未漂移。

本次无 migration、无历史 apply、无生产业务数据写入，正常代码回滚不恢复数据库。若将来另行
授权 `enforce` 或历史写入，其回滚必须使用该独立变更自己的证据与授权，不能复用本报告。
