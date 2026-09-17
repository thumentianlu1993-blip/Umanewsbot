# PR #203 生产发布验收

2026-09-18（北京时间），用户明确同意上线后执行已冻结发布包。PR #203 已合并为 `6c8bfdde2eac6ad4d25ab8301652197dcc37ac0d`；实际发布仍固定经过完整 CI 的 `d0bb40fb8defe3e9de1029aa255edd2e06e1e0c6`，没有使用后续纯文档提交替换应用构件。

## 实际发布与验收

- 固定候选 CI run 35242927242 已 SUCCESS。5,012 项仍有 45 个与主线参考一致的旧失败、新增 0；45 项发布合同通过，不能解释为全量测试全绿。
- 独立目录 `/opt/umanews-release-d0bb40fb-PR203-20260918/umanewsbot`，Compose project `umanewsbot`。没有覆盖原服务器目录或本机脏工作树。发布前导入锁空闲，无活跃导入进程/未结束导入；历史 runner 为 completed，无需暂停或恢复采集任务。
- 原 `deploy_lowcost.sh` / 0078 coordinator 返回 0，Web、worker、Beat、race_sync_v2_worker 同镜像 `sha256:677fe69f68b8421e306a02bb0c522e4425ee862ee9a7c48a47b8805ba7bc4bee`。0078→0078，迁移计划为空，Django check 通过；Web healthy，两个 worker ping/queue 响应一致，仅消费 celery / race_sync_v2。
- 四应用实际镜像 revision、`/app/.umanews-release-commit`、Django settings 都为 `d0bb40fb…`；原环境变量仍为旧 `ca6e9d…`，沿用发布前配置，未声称该变量已同步。settings 优先读取镜像文件，本次发现任务使用 settings。直接读旧环境变量的历史日历修复工具不在本次范围。
- `.env` 唯一新增 `RACE_DATA_SYNC_JRA_PRE_RACE_ENABLED=false`，有效 Compose、四容器 env 和 Django settings 均核对为关闭。既有其他配置、持久挂载、standing policy 保持；DB/Redis/OneBot/Nginx 原容器保留，Nginx 测试并 reload。审计 configuration=ready、capacity=valid、route_drift=[]，原有 5 个 blocker 未增加。
- 队列采样 celery 17→0、race_sync_v2 0→0、race_live 7543→7543；旧 race_live_worker 未启动，没有消费者。发布锁、active pointer、restricted marker 均清理。

## 两条数据动作

Manifest SHA `31dbf9f1d8400f0ef33a7f7b8dd18931488bfb562fa0437c26e29febf2f5827b` 原文未变。重新 dry-run 通过后在生产发布锁内 apply：104 新增 `産経賞オールカマー` 日语别名；829 改正为 `PRIX DE CHAMBLY` 并新增法语别名，原旧别名保留。审计 ID `552430`；apply 前后受保护字段摘要、slug/public_path 不变；后续 dry-run 返回 replayed=[104,829]，changed=[]。没有改赛时、状态、runner 或赛果。

## 公开页与范围限制

双域名共 20 个赛事详情 GET 均为 200 且路径不变：99、104、105、755、828、829、830、956、962、963。99 显示“赛期已过，资料待补”；828/830 无冠军、仍“赛果待确认”，出马表分别 7/5 行；829 名称已更正。755/956/962/963 正式赛果保持 11/10/9/11 行和冠军、双时区显示。另双域名首页、healthz、即将开赛/完赛筛选共 8 次 GET 通过，过期 99 不进 upcoming，未确认 828/830 不进 finished。

本次代码中的 D−4、3h / 1h / 10min 节奏已发布，但 JRA 仍关闭，104/105 时间与出马表尚缺；不宣称自然调度已验收。828/830 正式证据仍缺，829 仅修复身份，未手工回填其时间/名单。现场法国 TRA 当日额度已用 192，不提高额度或强制付费请求。原冻结的 79 场历史清单补齐赛果 0；新增 section_gaps 的全局审计为 88 条过期未纳管记录，筛选范围不同，不把两个数字作同口径增减。

独立 reviewer 对发布边界 APPROVED，并提醒新 JRA flag 不在旧 WRITER_FLAGS 自动验收内，已补上述逐进程核验；对镜像文件/settings 的实际版本依据也复核 APPROVED。

## 恢复凭据与证据

- 专属备份 `/opt/umanews-release-d0bb40fb-PR203-20260918/umanewsbot/runtime/migration_history_repair/release-0078-recovery/f1a1218054f22f6a5ec64cb8efc6f2ddb15b4dba98520e15136e8baad947f368/backup/rds_horse_news_20260917T182359Z_1617986.dump`，558,542,733 bytes，SHA `4947fea28bfd10db88351e165cc23667978fcc7262be26e70ee73802567be650`，pg_restore --list 1,383 行；发布后重新计算文件 SHA 与 manifest 一致。
- intent SHA `1fe1fcddf6bad5c08c5c224c7e8b2270ce1b3b25949113444b34d8414b5f3895`；manifest SHA `a07f1d39cc6d2fade96b896c36f4b4c76ecfbf623501147370ec3605b5279206`；complete SHA `5bb31441d0a969fb399c1fd4dc0a79b5e3e2333ae4d49fa8281122a22d8c1392`。
- [脱敏验收证据](evidence/release_verification.json)；服务器原始日志/脚本/目标前后/审计/验收在发布目录上一级 `evidence/`，本地 JSON 副本 `/tmp/pr203-release-evidence/`。验收完成时间 `2026-09-17T18:32:17.990786+00:00`。
- 普通代码 rollback 仍禁用；本次已完成，有问题前向修复。未完成意图才用同一 exact intent 恢复；不对这两条身份修复进行整库覆盖。
