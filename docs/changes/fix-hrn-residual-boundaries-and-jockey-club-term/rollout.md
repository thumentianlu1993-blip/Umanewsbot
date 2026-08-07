# 发布与历史重处理

## 阶段 1：代码发布前

- 使用最新 `origin/main` 的独立 worktree。
- 完成真实 RED、GREEN、受影响回归和独立代码 review。
- 授权前禁止 commit、push、PR、部署和生产写入。

## 阶段 2：代码部署

- 核对生产 HEAD、容器、队列、外部导入、历史 runner 和 health。
- 建立数据库与环境恢复点；虽然无 migration，历史 apply 会写业务字段。
- 部署同一受审提交，确保 web/worker/beat/race-live worker 镜像一致。
- 验证 Django check、migration drift、worker、healthz 和 HRN 只读解析。

## 阶段 3：剩余 36 篇重新 prepare

冻结 ID：

`5712,5716,8314,8381,8904,8962,9042,9279,9284,6158,6184,6371,6373,6488,6492,6495,6511,6515,6620,6626,6629,6631,6637,6642,6645,6646,8512,8637,8657,8804,8805,8894,9045,9051,9062,9067`

- prepare 可按最多 10 篇调用翻译，但不写业务字段。
- 每篇人工抽查后分类为 `approved`、`translation_failed` 或 `review_rejected`。
- source_clean 漂移时重新 prepare 并重新抽查，不复用旧批准。
- `Race Video` 4 篇与机构译名 2 篇是本轮直接回归样本。
- 原有严重截断 4 篇、编辑注 1 篇仍必须独立判断，本轮不自动放行。

## 阶段 4：批准、apply、verify

- 每个 approved manifest 最多 10 篇，绑定 candidate 内容与 SHA。
- apply 前保存 rollback artifact，事务内执行 fingerprint/source evidence/CAS。
- commit 后生成 receipt，再运行独立 verify。
- 任一 SHA、CAS、字段依赖、人工字段或来源证据失败时停止该批。
- QQ 已发送文章只更新数据库与网页正文，不重发 QQ。
- 最终 evidence artifact 记录冻结 36 篇 ID 集合 SHA、每篇唯一最终分类、每批 candidate/
  approved/receipt/rollback 路径及 SHA；发现漏项或重复分类时 fail closed。

## 回滚

- 新代码异常：暂停 HRN 新采集/自动发布，恢复发布前镜像并复核四个应用容器。
- 单批历史写入异常：使用该批 rollback manifest 与 receipt SHA 做 CAS rollback。
- 若当前数据库已被外部编辑，rollback fail closed，转人工处理。
- 证据文档如实记录部分成功；不得把未通过文章标记为完成。
