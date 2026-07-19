# 准实时公开 Beta 上线门禁修复发布与回滚

## Gate A：方案审核

五份 artifact 与真实代码、生产去标识证据一致；blocker/high 和必要 medium 全部关闭。
未通过前不得写生产代码。

## Gate B：RED/GREEN

先取得 coupled number、rollback bundle、maintenance CAS 和 PostgreSQL 恢复链 RED，
再由 implementation subagent 完成最小 GREEN。禁止用真实网络或生产依赖作为自动化测试。

## Gate C：代码审核与授权

未参与实现的 reviewer 执行 Codex 原生只读 review；成功后冻结 scope、parent、content
hash 和 fingerprint。用户只授权该精确冻结版本；任何内容变化重新 review 和授权。

## Gate D：候选镜像和发布前 rollback 演练

1. 构建 AMD64 候选镜像并核对 full image ID、revision、tree、registry SHA。
2. 历史 runner migration preflight、Celery active/reserved、live queue/claim 均为空。
3. 停 Beat 和两个 worker，创建并校验数据库、`.env` 和旧 image 回滚点。
4. 用候选镜像只读生成绑定其 full image ID 和 filtered env SHA 的 rollback bundle；
   generator 必须同时证明 enabled regions 为空、tracking 全关；final 目录 root-owned
   `0700`、三文件 root-owned `0600`，记录 manifest SHA。
5. dry-run 后单事务进入四层 maintenance；确认 event 924 暂时隐藏。
6. 用同一候选 image ID、manifest SHA 和 filtered env：
   `validate -> restore-policies-coarse -> validate -> restore-policy-event`。
7. 确认 event 924 恢复同一 provisional revision、7 条结果和页面，四层 policy version
   精确等于 restore snapshot。
8. 任一步失败不切镜像，并按真实阶段 handoff：
   - maintenance：四层 off，下一步仅 coarse restore；
   - coarse-restored：三层 restore、event off，event 仍隐藏，下一步仅 validator 后
     event restore；
   - restored：四层已恢复，只允许只读复核。
   使用已审核命令续跑或数据库备份，禁止手工 SQL。

## Gate E：镜像切换

1. retag 候选为 prod；应用 legacy runner identity migration，再执行
   check/drift/collectstatic。
2. 先 web、普通 worker、race-live worker，健康后 Beat。
3. 四个 app 容器必须同 image/revision。
4. scheduler/monitor=false、enabled regions 空、selector claim 0、队列/active/reserved 0。
5. 内外 healthz、event 924、五地区赛事页、日志和资源通过。

## Gate F：法国来源重验

1. 使用原 Free 账户、reviewed v2 registry 和最多一次法国 today racecard 请求。
2. event 733–735 显式 prepare；artifact 单独记录 SHA 和 blocker。
3. 不再出现 `racecard_schema_invalid` 才说明 coupled parser 修复有效。
4. 若 complete：initializer dry-run/apply/verify/replay，policy/event 仍 shadow，
   scheduler/monitor 和 enabled regions 不变。
5. 若 not-found、identity、grade 或其他 blocker：保持 off，不扩大请求或猜测。

## 回滚

- parser hotfix 包含 legacy runner identity migration；代码异常时保持全部新范围 off，
  再按下项兼容边界切回旧 image。
- migration 对旧 image 为 additive-column/constraint-compatible；若已产生 coupled legacy
  rows，旧 image 回滚后必须保持对应地区/event tracking 关闭并禁止旧动态更新器处理这些
  event。需要完全撤销时使用切换前数据库备份。
- maintenance 演练失败时不切镜像，按 Gate D 第 8 项记录真实阶段；只使用绑定 manifest
  的受审 one-shot 续跑恢复，失败则从已验证数据库备份处置。
- 法国 prepare/initializer 失败只隔离对应 artifact/event，不影响 event 924。

## 收尾

只向 evidence allowlist 追加实际 image、备份、manifest/env SHA、演练、法国 blocker 或
shadow 结果。复用本需求代码 reviewer 审核 evidence patch 后提交；不递归记录 evidence
commit SHA。
