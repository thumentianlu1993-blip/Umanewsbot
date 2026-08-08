# Release B 生产数据 apply 确定性停止证据

## 结论

批准的 14-action reviewed artifact 已生成并完成写前备份，但 apply 在单一数据库事务内因 canonical
path 瞬时唯一冲突失败。事务完整回滚，未生成 receipt/rollback artifact，未启动 verifier 或 2025
`full_network`；生产服务已恢复健康。

## 冻结身份

- census manifest：`85978b9bed6ff75742d1eed4cb0ad1e4f6105c9ebc82146e3c05efdff1682a13`
- review overlay：`8a1f3f2cadd7d7b4446b52548b010be1b2738d0da8c5bebe31ce19259ca26dbe`
- reviewed manifest：`c9e9b22299b94dc62af4a2afccb87dca0d7d906c9f84539a8b8a7727591e4c64`
- action scope：`0f633f215e45c47d6c4fd8cd2b720158436d2849362462f5581c092cb9f0af01`
- approval：`245baaf3aea31e68aceb62105bb5f93bb33e3d2f0affb9476d877dc47aba2420`
- maintenance：`ba8711b2f38d45aca8c3cf788a3a3f0c9e35fb0319dae69aba6a5e59e1dcc3b4`
- 写前备份：`91a38cf276005f614c6171ea13cde87532485a8e63dca1e96e280405d39e17aa`

## 错误与根因

PostgreSQL 拒绝 `uq_race_public_path_event_canonical`，冲突 event 为 `1214`。apply 的临时阶段仅把
受控 paths 改为临时 `year/slug`，没有临时解除旧 `path_kind=canonical`。最终逐行更新时，新轮转 path
先成为 event `1214` 的 canonical，而该 event 的旧 canonical 尚未在后续行降为 legacy，形成仅存在于
事务中间态的双 canonical。

## 回滚与恢复证据

- reviewed manifest receipt：`0`
- 12 个批准 duplicate 的 active canonical link：`0`
- mismatch：`81`
- 当前 census scope：`a324261fc68bc166345b08196d85bc40d08361d4cd6dec8ebd448196be811665`
- event `1214` 仍为 year/edition `2025/2025` published；event `1838` 仍为 `2019/2019` published
- maintenance gate `1` 已为 `exited`
- worker/beat 已恢复；Celery ping、Django check、writer census、内外 HTTP healthz 通过

## 最小修复

在全部 path row lock 持有后，临时 path update 同时写 `path_kind="legacy"`，然后再写最终 reviewed
owner/year/slug/kind。补充一个至少包含“旧 canonical 后处理、新 canonical 先处理”的轮转回归测试，
证明事务中间态不冲突、最终每个 published event 恰有一个 canonical、失败路径仍零写。修复发布后
重新生成并审核全部 artifact，禁止复用本次执行 manifest。
