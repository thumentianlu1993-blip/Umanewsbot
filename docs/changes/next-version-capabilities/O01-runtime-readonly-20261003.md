# O01 运行资源只读预查

观测：2026-10-03 03:00:52（Asia/Shanghai）。通过既有 SSH alias `umanews`，仅查询容器选择字段、固定 release marker、默认部署锁路径、受限进程分类、运行能力布尔值。未调用部署/preflight/pause/resume 入口，未执行数据库查询，未修改服务、配置、队列或数据。

## 已观察

- 八个容器处于 running；web/db/redis 的 Docker health 为 healthy，其他服务未配置此项健康证据。四应用为 web、worker、beat、race_sync_v2_worker，共用镜像 `sha256:73ee1dcf7edb5b7c7bda49f5d6baedffe030d639fcc5bf191b831ece6e9f5930` 与 revision label `ad50abdb74b89669ab8ada2958b040877c1a1849`。web/worker/beat 三个已读 marker 与 label 一致；race_sync_v2_worker 本次未读 marker。
- 应用运行目录 `/opt/umanews-release-ad50abdb-test-fixes-20261002/umanewsbot`，Compose project `umanewsbot`；基础设施保留各自原运行目录，不能据目录不同宣称异常。
- web 完整 ID `9f03d1faa0ccf681d50dd2a9db6018af55a33937bf94517b0d447f453ac2190c`。其 runtime 挂载只有 `/app/runtime/horse_profile_completion`，来源 `/opt/umanewsbot-persistent/runtime/horse_profile_completion`。没有 F02 模板假设的通用 runtime 持久挂载。已让 B 准备独立容器临时产物与专属宿主 artifact 的受控转存方案，不增加挂载或服务变更，不借用马匹目录。
- 默认 `/tmp/umanews-deployment.lock` 不存在；自定义锁路径未核。受限 release/historical/research 命令模式扫描未匹配进程；这不是全部长任务或数据库租约不存在的证明。
- web 可导入 psycopg，五个必需 POSTGRES 环境键均存在，值未输出；uid=0、`/tmp` 可写。数据库容器二进制为 PostgreSQL 16.14，尚未查询实际 ICU/collation/normalize 能力。
- 同轮刷新远端 `origin/main`，仍为 `907f8de699b31a6fcc80acc78e9ba070aadc4f28`。

## 尚缺与后续

O01 保持部分取证：实际锁覆盖/owner、在途 intent、历史任务 DB 租约与暂停批次、队列 active/reserved、资源预算尚未闭合。不得用本快照作为部署空闲证明；实际发布前仍需现场重核并绑定精确发布包。当前没有生产写入授权或发布请求，确认规则仅引用根 AGENTS.md。

F02 实际脚本及参数、来源包绑定、固定脚本摘要、输出/转存目录和恢复收据仍需原 R 技术核对后才能执行既有有界只读采样。读取 runtime 能力不等于采样成功，新增样本与 gold 仍为零。

## 2026-10-03 19:07–19:13 追加只读核对

继续采用既有 SSH alias 和权限。通过 Docker 选择字段、固定 marker、host 文件存在性、五条有界 PostgreSQL SELECT、Celery inspect 及公开 healthz 读取；未运行可能暂停任务的 historical_runner_preflight，也未暂停/恢复/发送/更改配置。数据库连接固定 read-only、repeatable read、statement_timeout 3 秒、lock_timeout 250 毫秒、idle timeout 5 秒；只返回能力布尔、迁移名和运行状态，rollback 后关闭。

- 19:07 四应用仍为 `ad50abdb74b89669ab8ada2958b040877c1a1849` / `73ee1dcf7edb5b7c7bda49f5d6baedffe030d639fcc5bf191b831ece6e9f5930`，restart_count=0、OOM=false。19:11 补读四个 `/app/.umanews-release-commit` 均与 image label 一致，release checkout HEAD 同 SHA。环境变量 `UMANEWS_RELEASE_COMMIT` 是旧值 `9c8891b8...`，不将其当实际运行版本；下一精确包继续以 label/marker/固定构建身份核验，未改旧配置。
- Compose project 选择到七个容器，web/db/redis healthy。另有独立 `umanewsbot-onebot-1`，不带 Compose project/service label，因此仅按 Compose 标签过滤会漏掉它；合计八个运行容器。双域名 `healthz` 均为 HTTP 200，不代表业务链完成。
- 19:09 实际数据库 PostgreSQL 16.14，stable 最新 migration 为 `0079_multisource_race_enrollment`。与 U01 一致的 UTF8 / pg_catalog normalize / `und-x-icu` 元数据探测均 true；这不是候选 SQL 已部署或完整业务验收。
- 同一只读事务未发现有 owner 的 ExternalDataImportLock 或 HistoricalBatchLock；最近五条历史运行有 completed 和一条旧 blocked，未取得全部历史对象完备性证据。有限 host 进程模式未匹配 deploy0079/release0079/release-task/horse-import/historical runner。
- 默认部署锁不存在；实际 release 目录下 restricted-recovery、transition、control 及 0078/0079 active 指针均不存在。宿主 `/opt` 可用约 27.38 GiB。未凭此宣布窗口安全；未知自定义外部发布协调者、队列与当次检查仍由发布前复核。
- 19:10 两个既有 worker 都 pong，active=0、reserved=0；普通 worker `celery@78c9d141f636` 有 scheduled=39，赛事 worker为0。19:13 聚合确认39个均为 `stable.tasks.qq_push_delivery_task`，ETA区间19:13:32–19:13:57（北京时间）；未读取任务参数/用户消息。普通与赛事节点分别消费 `celery` / `race_sync_v2`。现有 drain 脚本只核 active/reserved，两者为0不能据此宣称没有定时/迟到任务；发布前保持消息、核其新旧消费者兼容和实际收尾，不清队列或 revoke。

### Q02/O06 专属网关身份输入（非停用授权）

19:09只读发现独立 NapCat 容器 `9f77b49ec509a223cf30a9360350dfc6b358a193126afb1ba278b61f2cc2c98c`，名称 `umanewsbot-onebot-1`，image `sha256:9254ec12af101576c5eeb4910847abd1d219297bc6d9a35c52511e12500f0f45`，引用 `mlikiowa/napcat-docker:latest`，running、restart_count=0，网络 `umanewsbot_default`。登录目录 `/opt/umanewsbot/napcat/qq` 绑定 `/app/.config/QQ`，配置目录 `/opt/umanewsbot/napcat/config` 绑定 `/app/napcat/config`；另有只读 localtime。未打开登录数据/配置内容。

两份仓库 Compose 的占位声明不是这个独立容器的 owner 证明。O06仍需核创建/恢复命令、监控 owner、实际许可与切点，保留两目录及当前镜像；不能通过 `compose down`/`remove-orphans` 或删除卷代替精确服务停用。以上都是时点输入，执行前重核真实身份，生产状态未变化。
