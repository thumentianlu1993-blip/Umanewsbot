# 回滚指南

当前0078发布采用同候选续跑、前向修复和精确备份恢复。普通代码回滚保持禁用，
`reviewed_release_b_rollback_migrations.json` 中没有批准的回滚目标。

## 1. 回滚前原则

- 先确认故障范围（代码、容器、数据库、OSS）
- 先保全现状数据（先做一次数据库备份）
- 回滚后优先恢复可用性，再做根因分析

## 2. 代码与容器恢复

`rollback.sh` 和 `rollback_lowcost.sh` 在当前真实策略下会拒绝执行，拒绝发生在
checkout、build、retag、stop、migrate、restore之前。更新迁移清单至0078只用于准确
描述兼容合同，不会产生新的批准目标。

当前发布中断时优先沿同一候选、数据库和备份继续完成；完成后发现代码问题则准备
前向修复。需要恢复旧镜像时必须同时验证完整 schema 与备份范围，不能只把 image tag
改回旧值。旧 pre-contract 桥和0077 artifact 只属于其原固定控制版本的历史恢复流程，
不能作为0078的通用恢复入口。

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

## 5. 发布失败后的恢复（resume）

0078的发布意图在首次stop前已保存，使用 `resume_migration_history_repair.sh`，输入
原 `RELEASE_0078_INTENT_PATH`、`RELEASE_0078_INTENT_SHA256`、`COMPOSE_FILE` 及精确候选
commit/image。实际命令和值由本次发布包给出，不能选择“最新文件”或替换备份。

入口重新获取同一主机部署锁，核对数据库/配置/文件身份后继续原发布：部分停服、closed
handoff尚未写入、DDL marker尚未创建、static失败、schema已完成但服务尚未恢复均可区分。
完成凭据只在static成功后产生；有有效凭据的服务恢复阶段不重复迁移。

active intent期间拒绝新deploy/manual与普通stopped-service resume。没有在途意图时，
`manual_release.sh` 只处理已完整0078且应用服务已停止的环境，并保留原停止状态。
后续 `resume_stopped_release.sh` 的独立服务启动仍先检查exact0078 recorder/catalog。
全部发布与数据恢复授权统一引用根 `AGENTS.md`。

## 6. 回滚后检查

1. `https://your-domain/healthz/` 返回 `200`
2. 后台可登录
3. 前台可打开至少 3 篇文章
4. `worker`/`beat` 正常
5. 抓取、翻译、推送日志恢复写入
