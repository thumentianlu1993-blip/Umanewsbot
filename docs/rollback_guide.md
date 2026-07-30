# 回滚指南

本文档给出最小可行回滚流程，确保上线异常时可以快速恢复。

## 1. 回滚前原则

- 先确认故障范围（代码、容器、数据库、OSS）
- 先保全现状数据（先做一次数据库备份）
- 回滚后优先恢复可用性，再做根因分析

## 2. 代码与容器回滚

使用脚本：

```bash
./deploy/rollback.sh <git-ref>
```

示例：

```bash
./deploy/rollback.sh v0.0.1
```

脚本行为：

1. 获取 host-local 部署锁（与 deploy/manual release 互斥；竞争失败立即非零退出）
2. `git fetch --all --tags` 并把目标 ref 一次解析为不可变 `TARGET_OID`；OID 必须是
   单行 40 位小写十六进制，空/多行/非 hex 在任何检查前非零拒绝
3. 在任何 checkout/停服前，对该 OID 逐一 `git cat-file -e` 核对
   `deploy/release_contract_v1` marker 与全部 v1 helper；任一缺失直接拒绝
   （零 checkout、零停服、零 release）
4. 既有 web 上执行 historical runner preflight 后，`git checkout` 解析出的不可变 OID
   并重建 `web` 镜像
5. 复用与部署完全相同的 release 编排：停 beat -> 排空全部 Celery worker ->
   停 worker 和当前运行的 race_live_worker -> 停 web -> 单次 one-shot
   release task -> 启动 web 并等待 healthy -> 启动 worker/beat/nginx ->
   按冻结的恢复意图恢复 race_live_worker

**警告：release task 的 forward migrate 不等于数据库回退。** 它只会把目标代码已知的
migration 推到其 forward head，绝不撤销数据库中较新的 migration。若当前 schema 与
目标代码不兼容，必须在 release 前停止，由人工选择已审核的反向 migration 或恢复
部署前已校验的备份；脚本不会自动猜测兼容性，也不会自动恢复数据库。

### 2.1 首次发布的 pre-contract 回滚兼容桥

`fix-single-migration-owner` 首次生产发布后，若要回退到此前没有 release contract 的
旧版本，不能使用上面的通用 rollback（旧 ref 会在 marker 核对处被拒绝），而应使用：

```bash
COMPOSE_FILE=docker-compose.prod.yml \
  ./deploy/rollback_pre_single_owner.sh <部署前冻结的旧 image tag>
```

该桥保留新控制面 checkout（不做 `git checkout`），在同一部署锁内停 beat、排空
worker、停 worker/原本运行的 race_live_worker/web，然后把冻结旧 image
`docker tag` 回 `umanewsbot:prod`，只启动一个旧 web（旧 image 的启动入口是它自己的
唯一 migration owner），web healthy 后再恢复 worker/beat/nginx 并按原始运行态恢复
race_live_worker。它不调用新 one-shot release task，也不调用旧 rollback 脚本。
当 `SCHEMA_COMPATIBLE_WITH_TARGET=false` 时，桥会在 image 切换前非零停止；数据库
恢复必须另行授权，本桥不执行。

## 3. 数据库回滚（RDS）

优先使用 RDS 自动备份做时间点恢复（PITR）：

1. 在 RDS 控制台选择恢复时间点
2. 先恢复到新实例验证
3. 应用 `.env` 切换 `POSTGRES_HOST` 指向恢复实例
4. 重启 compose

## 4. 媒体资源回滚（OSS）

- OSS 建议开启版本控制与生命周期策略
- 出现误覆盖时按对象版本恢复
- 如出现全量故障，优先恢复关键封面和近 7 日热点稿件图

## 5. 失败释放后的受审恢复（resume）

release 流程失败导致服务保持停止时，受审恢复顺序为：修复根因 ->
`./deploy/manual_release.sh`（需要重跑 schema/static 时）->
`COMPOSE_FILE=<allowlisted> ./deploy/resume_stopped_release.sh` 恢复服务。resume 与
deploy/rollback/manual release/pre-contract bridge/p0 closed-admission 共享同一主机级
部署锁（action 全集：deploy、rollback、manual-release、pre-contract-rollback、
p0-closed-admission、resume-release），任一应用服务仍在运行、restarting 或状态不可读时
拒绝启动；它绝不执行 one-shot release task，race_live_worker 只按可信冻结意图恢复。

## 6. 回滚后检查

1. `https://your-domain/healthz/` 返回 `200`
2. 后台可登录
3. 前台可打开至少 3 篇文章
4. `worker`/`beat` 正常
5. 抓取、翻译、推送日志恢复写入

