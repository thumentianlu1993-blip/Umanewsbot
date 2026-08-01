# Lifecycle 非重点赛事纳管 R0 发布报告

## 代码发布

- 功能提交：`69fbbb8b75842d21dcbe0c8071e8f9115c55b222`；
- PR：[#62](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/62)；
- main merge commit：`7252d59a52529834945fcfea6b0b7154eb8458f6`；
- 合并内容经过 fingerprint `89ade10e…f065` 的独立只读 review，结论 `APPROVED`。

## 首次关闭态部署结果

- 从精确 merge commit 创建隔离 release 目录
  `/opt/umanews-release-7252d59a-boCrQy/umanewsbot`，复制既有 `.env` 与证书目录；生产主
  checkout 的既有改动未触碰。
- 发布前确认 web/worker/beat 均为 `false/off`、control/transition 为 `0/0`、race-live
  未运行；共享部署锁成功获取。
- `historical_runner_preflight.sh` 首次调用
  `deploy/docker/compose-wrapper.sh` 时返回 `Permission denied`，远端命令 exit `126`。
  merge commit 中 wrapper Git mode 为 `100644`，而部署脚本要求直接执行它。
- 失败发生在数据库备份、rollback tag、pull/build、停止 beat、Celery drain、停止服务、
  release task、迁移和重启之前。退出 trap 已释放部署锁；新备份和新 rollback tag 计数均为 0。
- 失败后线上镜像仍为 `sha256:ccf28ce6c85055ba7b6a97bfe299e932c221c51538c1cd6912a75e360f194a1b`；
  web/worker/beat/nginx 保持运行，web healthy，HTTP healthz 与赛事页均为 200，lifecycle
  继续 `false/off`、control/transition `0/0`。

## R0 直接执行图修复候选

- 独立分支 `codex/fix-compose-wrapper-executable-bit` 基于 merge commit `7252d59a`；
- 测试先行真实 RED 证明 wrapper 执行位为 0；测试使用 fake Docker，不调用真实 Compose；
- 首轮 reviewer 发现 fake harness 会统一 chmod，掩盖另外五个 raw-checkout 入口/helper
  缺执行位；仅修 wrapper 仍会在根入口或停 beat 后的 drain 阶段 exit `126`。
- 修复扩展为完整 R0 标准/lowcost 直接执行图：`deploy.sh`、`deploy_lowcost.sh`、
  `deploy/deploy.sh`、`deploy/deploy_lowcost.sh`、`deploy/docker/compose-wrapper.sh`、
  `deploy/wait_for_celery_drain.sh`，六个 Git mode 均从 `100644` 改为 `100755`；所有脚本内容
  SHA-256 前后不变。
- 测试直接解析真实源码调用图并检查 raw checkout mode，不经过 harness chmod；wrapper 的
  fake-Docker direct-exec smoke 继续保证不调用真实 Docker。
- migration-owner、historical runner 与 race-live P0 部署合同合计 `165/165` 通过，Django
  check、migration drift、全 deploy shell syntax 和 diff check 通过；
- 当前等待同一 reviewer 对 P1 修复限定复审，尚未 commit、push、PR 或生产重试。

## R0 关闭态重新部署结果

- 执行位修复提交为 `4d0a0a7404b4bfbcf4e19266358e1fec877ae655`，经 PR
  [#63](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/63) 合并为
  `main@2dba891fd0b4e5b5671d4a18ed30289e08febc96`。发布使用该精确 merge commit 的隔离目录
  `/opt/umanews-release-2dba891f-LDatiL/umanewsbot`，未修改生产主 checkout。
- 发布在共享部署锁内重新执行全部门禁。historical runner preflight 为
  `migration_safe`；旧镜像冻结为
  `umanewsbot:rollback-pre-remove-lifecycle-key-race-gate-20260801T170915Z`。
- 数据库恢复点为
  `/opt/umanewsbot/backups/db/pre-remove-lifecycle-key-race-gate-20260801T170915Z.dump`，
  `373763059` bytes、TOC `1288`、mode `0600`，SHA-256
  `285de333ac811363edf3377336e4f036a76a605d19b96a0d4a000c4c2a7edc7f`。
- Celery 在停止 worker 前自然排空，观测值为 `active=0 / reserved=0 / active_confirm=0 /
  workers=1`。唯一 one-shot release task 报告 `No migrations to apply`，随后 web 通过 healthy
  硬门禁，worker/beat/nginx 才恢复；race-live 部署前不存在，发布后也未启动。
- 最终镜像为
  `sha256:24fc89cfd801f624c4c2e42bfb5654def6cf50785bda6f8a4d89bb9028c67b9f`，
  web/worker/beat 使用同一镜像；容器内 enrollment service SHA-256 为
  `1b7d3287b19d8db8e43c17d1a1b73fe44153bfba92b99a7c63100d8c20e8381e`，
  compose wrapper mode 为 `0755`。
- web/worker/beat 均为 `RACE_EVENT_LIFECYCLE_ENABLED=False`、mode `off`；control、transition、
  active claim 为 `0/0/0`。关闭态 scanner 返回
  `enabled=False / claimed=0 / dispatched=0`，本轮没有创建 control、推进赛事状态或执行其他
  lifecycle 业务写入。
- 迁移计划为空，Celery ping 为 `1 node online`；HTTP `/healthz/` 与 `/races/` 均为 200。
  发布后 15 分钟窗口内 web/worker/beat 的 `Traceback/ERROR` 计数均为 0，Nginx 502 为 0；
  共享部署锁和 race-live 意图文件均已清除。HTTPS 仍为既有未启用状态，不属于本次 R0 范围。
