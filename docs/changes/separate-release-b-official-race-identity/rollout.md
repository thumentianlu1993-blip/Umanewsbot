# 发布与运行计划

## 发布包

- 代码：本 change 的固定 commit/PR；
- migration：无；
- 配置与开关：无变化，历史写入开关在 census 审核前保持关闭；
- 服务：构建固定镜像并按受保护 deploy 编排重启 web/worker/beat/nginx；
- 验证：服务健康、Django check、migration plan 为零、生产 12 对只读身份复算；
- 回滚：在任何数据 apply 前可直接回滚上一镜像；数据 apply 后使用同 manifest 的 exact rollback。

## 数据阶段

1. 生成新的 no-replace census 目录，保存 manifest/census/template/summary 的 size 与 SHA。
2. 独立审核全部 14 actions。12 个 duplicate boundary 必须逐对确认官方身份和 survivor；另外两个
   series 必须审核 edition/target/path 变换。任何模糊项输出给用户并等待，不猜测。
3. 绑定 reviewed manifest、approval、action scope、maintenance evidence 和新备份执行 apply。
4. 运行 verifier，保存 receipt、rollback artifact 与健康证据。
5. verifier 通过后才启动 2025 `full_network=true`；临时网络错误按精确 checkpoint 最多 6 个 run，
   确定性错误立即停止并一次性报告。

## 当前状态

实现与 36 项 Release B 测试已通过；独立只读 review 未发现 actionable defect。尚未提交、合并或
部署，未生成新 census，零生产写入。

## 2026-08-09 path staging follow-up

首次生产 apply 在事务内暴露 canonical-per-event 的中间态冲突并已安全回滚。follow-up 只让受控
paths 在临时 key 阶段统一变成 `legacy`，最终 reviewed topology 写入逻辑不变。新增生产顺序回归后，
SQLite 与 PostgreSQL 16 的完整 Release B 套件均为 `37/37`。旧执行 manifest 不可重试；候选须经
独立 review、发布后重新生成 census/reviewed artifact，并停在新的 G3。

独立 reviewer 会话 `019fe254-9543-7440-bfaf-8fac75d6ff30` 提出 1 个 P1：apply 释放 canonical
后，rollback 也必须对称释放，否则双向 canonical swap 的 exact rollback 仍可能瞬时冲突。候选已
在 rollback 临时阶段同样设 `legacy`，并新增双向 swap 的 apply/rollback 回归后交回同会话复核。
P1 修复后 SQLite 与 PostgreSQL 16 完整 Release B 套件均为 `38/38`。

同一 reviewer 会话随后独立复跑无网络 SQLite 与临时 PostgreSQL 16 完整套件各 `38/38`，并核对
Django check、migration drift、`git diff --check` 和工作树范围，最终结论为 `APPROVED`，无剩余
actionable defect。

## 2026-08-09 path staging follow-up 已发布并冻结新 G3

PR `#80` 已合并并部署固定 commit `75294a4dea51538962741ec6c0835dc3090558ff`，生产 image 为
`sha256:1894484989084e61ced236eec93a30fd0b963b7ee946ad8ee8bd8e15357e413d`。部署后 check、
migration 零计划、health、Celery drain/空队列和关闭开关全部通过。

新 census/review/reviewed/action-scope SHA 分别为 `e626c8b4…70ec`、`083610c5…5883`、
`89387fab…e96b`、`d7052d43…00bd`。静态审计确认 14 actions、177 events、12 tombstones、12
canonical links、12 superseded targets、165 canonical paths、12 legacy paths、2 个跨年 edition，
所有碰撞为 0。未生成 approval/maintenance evidence，未 apply/verifier，未启动 `full_network`；
等待绑定上述精确 artifact 的 G3。
