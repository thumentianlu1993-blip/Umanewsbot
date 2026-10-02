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
