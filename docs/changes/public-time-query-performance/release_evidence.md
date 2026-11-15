# 公开时间 SQL 性能修复发布证据

2026-11-15 北京时间 20:28:01 发布完成。用户批准合并并执行已审发布包后，PR [#321](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/321) 合并为 `2b01cab40cee1bf7c7a296b386a1c0a622d67c5d`。运行候选为 `29f736b5aa61671418435b8d5f502ed09a285c15`。

## 身份与范围

- 原发布 manifest SHA-256：`3f88e569f5a92f491c97f58e44dafc2b66cdba3bc514d86cc54b01b5b198f085`，原件未改。
- 原六应用基线：`3f298404ba45679955cf1d0c2016a158c358bedc`；原镜像 `sha256:85a6a2e51b69650b39af409dfdf0e18b7d8506202d5f7d515bc41e0b843b2ce2`。
- 新 Web 镜像：`sha256:ccf91e7dc06d9e105f73952099eafd399451f182e4e2579f25cfb5683e7811b1`，继承原依赖，仅覆盖公开时间服务、对应测试文件和版本元数据。Compose 中仅 Web 镜像及 `UMANEWS_RELEASE_COMMIT` 更新，其他解析配置相等。
- 无迁移、seed_admin、collectstatic、业务数据写入、采集范围或功能开关变化。schema 仍为 `0088_p01_sealed_evidence`，迁移记录 106 条，前后摘要相同。
- 其余五个应用、数据库、Redis、浏览器与 OneBot 的容器 ID、运行状态和启动时间均保持。原 OneBot 已停止，发布后仍保持停止。
- Nginx 仅检查并 reload；配置摘要前后均为 `6eee72eeffa260023253969c7576551f11aeb833b0f99d06e8614dca230faa54`。既有爬虫阻断、robots 与字体保持。

## 生产验证

单个 repeatable-read/read-only 事务中执行旧、新查询各一次，单条超时 10 秒；两者参数相同，均返回 9 行，完整结果相等，结果摘要 `fd6dfeddc170cde679b665b3922e04ef6e9db50f0e5f34c72c00db3146264ca0`。

| 生产样本 | 原 SQL | 新 SQL |
| --- | --- | --- |
| 数据 SELECT 耗时 | 0.685934 秒 | 0.062829 秒 |
| 计划中的 pg_timezone_names Function Scan 节点 | 15 | 1 |

生产计划使用 EXPLAIN（未加 ANALYZE），因此这里只证明计划节点数；实际 Function Scan/Loops 的执行证据来自隔离 PostgreSQL 测试。该单次样本约快 10.9 倍，不代表全站或长期分位延迟。

| 路径 | 源站 HTTPS 总耗时 | 本机经公网直达源站总耗时 | 状态 |
| --- | --- | --- | --- |
| `/healthz/` | 0.074 秒 | 1.704 秒 | 200 |
| `/` | 1.614 秒 | 2.546 秒 | 200 |
| `/races/` | 0.688 秒 | 2.546 秒 | 200 |
| `/races/2026/jra-2026-1114-02/` | 0.303 秒 | 2.087 秒 | 200 |

公网探针使用 Host/TLS 域名及固定生产 IP，从本机直连源站，不包含浏览器字体、图片等完整页面渲染，也不是 CDN 或用户 DNS 路径的测量。Web healthy，systemd 发布单元最终 `Result=success` / `ExecMainStatus=0`，发布锁已释放。

## 首轮回滚与复审

首轮的新旧查询和四个 HTTP 检查均通过，但执行器错误要求所有既有容器都处于 Running，误判原本停止的 `umanewsbot-onebot-1`。由此按包自动恢复原 Web，回滚后 healthy、health/赛事页 200，锁释放。随后将验收修正为与原 ID/Running/StartedAt 一致，并独立保存回滚身份凭据；原只读 reviewer 复审无剩余 actionable finding 后，同包重试成功。此项不改变 OneBot 或业务状态。

初次 systemd 启动的 SSH 等待超过 30 秒；服务端独立单元继续执行，未重复启动。重试使用非阻塞启动，以服务端收据判断最终结果。

## 维护与恢复面

服务端产物目录：`/opt/umanews-external-staging/public-time-29f736b5/`。最终 Web 的完整 Compose 链共 25 份：原受审 23 份，加本目录的 `rollback-identity.json`（固定旧 Web 镜像）和 `release-identity.json`（固定新 Web 镜像及版本）。后续维护应读取运行容器的完整配置链，不只使用原基础 compose 或工作目录 HEAD。

`config-backup/` 和私有 resolved-config/container 快照留在服务端；原件权限受限，不入仓库。首轮报告保存在 `attempt1/`；最终报告为 `release-report.json`。旧镜像保留，本次自动回滚实际验证过恢复路径；无数据库恢复或清队列动作。后续操作仍按根 AGENTS.md 判断。

本机完整收据：`/Users/mentianlu/.codex/runtime/public-time-query-performance/production-release-receipt.json`；公网样本：同目录 `public-http-receipt.json`。业务代码已合并并发布；本次新增的事后证据文档独立提交，不改变运行版本。
