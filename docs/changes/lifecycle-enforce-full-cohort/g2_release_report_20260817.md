# Lifecycle full-cohort G2 关闭态发布报告（2026-08-17）

## 结论

- PR `#105` 已以 merge SHA `93cfd240b9ba7e95caf79bf54e9c6d089885f11c` 部署到
  `/opt/umanews-release-93cfd240-PR105-20260817/umanewsbot`。
- 新 image 为 `sha256:06885466d50171d0853997844106ed45a5ab5c65a314ba2f4947a60683885904`；
  web/worker/Beat 运行同一 image/revision，migration leaf 为 `stable.0073_lifecycle_enforce_registry`、
  plan 为 `0`，实际 release task 输出 `No migrations to apply`。
- lifecycle 始终为 `false/off`，legacy/registry 运行信任根为空；race-live scheduler/monitor 为 false，
  `race_live_worker` 保持 `Created`、未启动。未授权也未执行 enforce、registry promotion、race-live 或
  公开赛事状态写入。

## 恢复点与发布证据

- fresh custom-format PostgreSQL 备份：
  `/opt/umanews-pr105-g2-20260816T173211Z/pre-pr105.dump`；大小 `445635636` bytes，TOC `1325` 行，
  SHA-256 `e6741b7aa896dc2255a7ba1de372f5de6f85f6639b4333cac0de1b47bd0a7893`，mode `0600`。
- 回滚 image tag：`umanewsbot:rollback-pre-pr105-20260817`；image ID
  `sha256:22e815115dcec7b4c8a027be02082c20a4132fbe40c478eb522d82300b8a9c05`。
- Release B preflight artifact SHA-256：
  `d255b2aae7e2e9cc12a15b5b087cc7e21a47daf53154e967ff9e86c1b4177b82`。
- 生产 HTTPS Nginx 配置按已运行版本保全，active/release SHA-256 均为
  `a506e857d959529deb6cfbbe8712864031defddfb8583c628d64e50197748b9c`；仓库候选配置 SHA 为
  `3f1145f2519d261a2187cf387c0b05794cf885c92b2808e4b0533fe2de450099`，因此隔离 release 中唯一 tracked
  偏差仍是该生产 Nginx 配置。此偏差避免覆盖现有 HTTPS/证书路由，后续须另行把生产配置安全归档入库。

## Legacy 186/187 canary 收口

- 旧 manifest raw SHA-256 为
  `eacffda63284e25b59c3efa5815d138a562c10e86eec7fe5ed1ed41219d303fc`，approved commit 为
  `a7e3783ff7d188481cecd421cd2595f43e9a706b`，范围精确为 event `186,187`。
- 在共享部署锁内停止 Beat、等待普通 worker 从 `active=1` 自然排空到 `0` 后停止 worker；未杀任务。
  第一次相同命令返回 `outcome=disarmed`，第二次返回 `outcome=replay`。
- before/mid/after 证明赛事状态和 transition 未变；control 只从 active evidence 写成 canonical inactive
  evidence，仍保留 `mode=enforce` 作为历史纳管记录。mid 与 after 文件逐字相同，SHA-256 都为
  `82ce3b1704bb27a5ca33afb3d423c39c07de857368783a61d2dbffacf36a14cb`，证明 replay 零写。
- before 证据 SHA-256 为 `f4dd39542cd8604caefc7c67d8a833573beccdea1b56d64b68d7fd8e2dce6ed0`；
  event 186/187 公开状态继续为 `finished`，详情页与赛事日历均返回 HTTP `200`。
- 首次外围 evidence verifier 错把 inactive evidence 的空 `activation_id`/`activated_at` 字段预期为字段缺失，
  因而在两个业务命令已经成功后非零退出。其 cleanup 正常恢复 worker/Beat 并释放锁；随后按真实 schema
  只读重验上述三份冻结文件通过，没有重做 disarm 写入。

## 生产只读 census

- 最终证据目录：
  `/opt/umanews-pr105-g2-20260816T173211Z/registry-readonly-20260816T174522Z`。
- `datetime_7d_canary`、limit `20`、generation `1` 共检查 `9867` 场，返回
  `status=no_candidates`：included/required/ready/blocked_us/batches 均为 `0`。
- census SHA-256 为 `cd49fe675709e6cf068507815f91fcab767512f1ddb6b87497a8fd2ea67c3224`；
  enrollment plan SHA-256 为 `9eb75815b0e3a24a39d76a7b45962b647d22e61aa263001603d425a93dea6b47`。
  未生成 registry artifact，因此 promotion dry-run 为“不适用”，不得记作 promotion 已验证。
- control/transition/registry/membership 四表 before/after 逐字一致，双方 SHA-256 均为
  `dc6643fa1a786dcedc31f2c6042c183716a704fc4be214f6054afd34b0e39b84`，证明 census 零数据库写入。
- 第一次外围脚本在命令正确返回 `no_candidates` 后，误用宿主机 `test -f` 检查容器 `/tmp` 路径而退出；
  修为 `docker exec test -f` 后用新的唯一目录完整重跑并取得上述证据。第一次未进入 after 指纹步骤，
  未产生 registry 或数据库写入，保留为失败 harness 记录而不冒充成功证据。

## 上线验收

- host-wide lifecycle coherence 通过；共享部署锁为空，web/worker/Beat 均稳定运行。
- `https://umafans.run/healthz/`、`https://www.umafans.run/healthz/`、赛事日历及 event 186/187 详情均为
  HTTP `200`。
- web/worker/Beat 最近日志中 Traceback/Critical 均为 `0`；Celery 有 `1` 个正常
  `stable.tasks.crawl_news_source_task` active task、reserved `0`，不是 lifecycle 任务。
- registry/membership 行数均为 `0`；event 186/187 control 均为 `mode=enforce`、
  `activation_state=inactive`、空 activation ID。磁盘当时为 `84%` 使用、约 `16G` 可用。

## 后续边界

- G2 关闭态发布、legacy canary 收口和只读 census 已完成。
- 当前 7 天窗口没有可生成首档 registry 的赛事，不能凭空进入 G3。下一步应先补充或等待具备可信
  `race_datetime` 的未来赛事，再生成新的可审计 census/registry artifact，并单独申请 G3；在此之前继续
  保持 lifecycle `false/off` 与 race-live 关闭。
