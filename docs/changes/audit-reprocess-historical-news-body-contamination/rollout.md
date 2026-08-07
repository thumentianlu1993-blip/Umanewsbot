# 历史新闻正文污染盘点与重处理发布方案

## Gate 0：当前规划

- 当前只完成探索、规格、方案审核与交接。
- 禁止写测试、应用代码、生产数据，禁止 commit/push/PR/deploy。

## Gate 1：工具实现与本地验证

- subagent 按文件边界实现 inventory、candidate、review、apply/verify/rollback。
- GREEN、真实 PostgreSQL、安全/性能检查与独立原生代码 review 全部通过。
- 无 migration 为预期；若需要 migration，返回方案审核。

## Gate 2：工具发布

- 创建数据库和环境恢复点，核对服务器 checkout、四个应用服务镜像、容器内 revision。
- 部署工具但不运行正式 inventory/candidate/apply。
- 验收 Django check、migration drift、命令 help、worker/beat、内外 healthz。

## Gate 3：正式只读 inventory

- 再次取得生产只读执行授权。
- 使用一次性容器、专用 SELECT-only 角色（或 PostgreSQL 强制 read-only transaction 并执行拒写探针）
  和显式挂载：
  `/opt/umanewsbot/runtime/news_body_history:/app/runtime/news_body_history`。
- 不使用 `docker compose run`，避免重建依赖。现有 web 容器持有可写凭据，不能作为“只读”证明；
  优先使用受控 `docker run --network` + 专用只读 role。若临时使用 `docker exec`，必须先对连接强制
  read-only 并用写探针证明 DB 拒绝，记录实际命令、镜像 ID 和 revision。
- 生成冻结 `source_site=horse_racing_nation,id<=9788` 总账，预期探索基线为 282 篇。
- 独立核对 ID-set SHA、分类穷尽、文件权限、artifact SHA 及业务表/OperationLog 零写入。
- 任何集合漂移先报告，禁止直接进入 candidate。

## Gate 4：候选准备与人工定稿

- 候选准备涉及模型/API 调用与费用，单独授权；默认每批最多 10 篇。只允许 detached DTO + pure
  provider，禁止会写 TranslationRun/Article 的在线任务/服务。
- 网络只在 prepare 阶段启用，成功或失败后立即关闭；prepare 不写数据库。
- 首批包含 `9623`、`9519`、一个正常 no-action 反例和合适的未公开候选。
- 工作簿逐篇审核 exact output；已发送 QQ 的文章明确标记旧消息不可修改。
- 定稿后输出 approved manifest 和 SHA；任何编辑必须重新生成 manifest 并重新审核。

## Gate 5：历史 pilot apply

- 针对 exact approved manifest SHA 再取得用户明确生产写入授权。
- 写前：
  - 暂停相关自动抓取/翻译调度或证明不会竞争；
  - 等待 worker active/reserved 安全；
  - 生成 custom-format PostgreSQL 备份，核对 size/SHA/`pg_restore -l`；
  - 保存当前镜像/环境恢复点；
  - 原子预写含完整 before 值的 rollback artifact，完成 file/directory fsync 并固定 SHA；
  - 运行 dry-run 并人工核对字段 diff。
- apply 使用离线 exact output，最多 10 篇、单事务、全集锁定、漂移整批零写。
- 写后立即运行 verifier，再用实际 1440px/390px 页面检查 `9623/9519/正常反例`。
- 不重发 QQ，不改变发布时间，不触发自动发布。

## Gate 6：后续小批

- pilot 全部通过后，按风险顺序：
  1. 未公开、无 QQ、无人工字段；
  2. 已公开但无 QQ；
  3. 已公开且 QQ 已发送；
  4. 复杂状态/人工字段继续人工处理，不自动批量。
- 每批独立 manifest/授权/receipt/verifier；上一批失败即停止。

## 回滚

- 代码异常：切回部署前镜像/checkout；普通代码回滚不恢复数据库。
- 数据异常：使用 DB 事务前已持久化并由 OperationLog 绑定 SHA 的 rollback manifest，在当前状态仍
  匹配 after fingerprint 时精确恢复本批字段。receipt 缺失可重建，不能因此重复 apply。
- rollback 也要求用户授权、manifest SHA、单事务和写后 verifier。
- 若数据库状态已继续变化而 CAS 不匹配，不自动恢复；进入维护窗口评估 PostgreSQL 备份恢复。
- QQ 已发送消息不能通过数据库回滚恢复或撤回，只在最终报告中保留不可逆说明。
