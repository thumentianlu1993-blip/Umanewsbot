# 准实时公开 Beta 上线门禁修复测试

## 1. Coupled entries

1. `test_racecard_accepts_distinct_horses_with_shared_number`
   - 两个不同 `horse_id` 共享 `number=1` 时解析成功；
   - 两条 participant 顺序、ID、号码、draw 均保留。
   - mutation：恢复 `runner_numbers` 唯一集合后测试应 RED。
2. `test_racecard_rejects_duplicate_horse_id_even_when_numbers_differ`
   - 同一 `horse_id` 出现两次继续拒绝。
   - mutation：删除 runner ID 唯一检查后测试应失败。
3. `test_unrelated_coupled_race_does_not_poison_target_prepare`
   - 同页一场 coupled race 与一场普通目标赛事；
   - prepare 完成并只匹配目标 event。
   - mutation：整页 number 唯一门禁回归后测试应失败。
4. 字段空值、非字符串、空 runners、race/runner 超限和重复 race ID 原有测试继续绿色。
5. PostgreSQL initializer/refresh 对 coupled target 分别创建两个 participant、
   source identity、revision item 和 legacy runner；两行共享号码但 external ID 唯一。
6. migration 删除号码唯一约束、新增 external ID 条件唯一约束；空 external ID 的历史
   rows 可共存，重复非空 external ID 拒绝。
7. 动态更新优先 external ID；号码多行时唯一 name 才更新，缺 name/name 仍歧义时
   `skipped_ambiguous=1` 且零行改变。恢复 `.first()` mutation 后测试应失败。

## 2. Rollback bundle 生成

8. 完整 provisional baseline 生成 deterministic strict manifest，绑定 image/env/commit、
   revision/publication/allowlist/tracking 和四层 policy。
9. maintenance=`off/current+1`、restore=`current mode/current+2`，digest/validity 不变；
   source restore 非 provisional 时拒绝。
10. scheduler/monitor=true、enabled regions 非空、任一 active claim、
   tracking enabled/next poll/token/expiry 非空、pointer/publication/allowlist/source/
   policy 漂移或 validity 过期时拒绝且不发布目录。
11. image ID、SHA、commit、run ID、绝对路径、0700 root、symlink、重复目录和 1 MiB 边界
   均 fail-closed。
12. root EUID/UID/GID、`lstat/fstat/O_NOFOLLOW`、同目录 staging、file+directory fsync、
   no-replace、替换父目录、失败清理和 exact/duplicate-key schema 均覆盖。
13. final 目录为 root-owned `0700`，三文件为 root-owned `0600` regular non-symlink；
   manifest/report 不含
   `THE_RACING_API`、password、SMTP、通知或 DB 值。

## 3. Maintenance CAS

14. dry-run 零写入，输出四层 from/to 和 manifest SHA；enabled regions 非空时零写。
15. apply 在一个事务中把四层从 baseline 推进到 maintenance；event read gate 隐藏，
    OperationLog 恰一条。
16. 精确重放返回 already applied，版本和 OperationLog 均不增加。
17. 单 scope version/mode/digest/expiry 漂移、部分 maintenance、tracking lock/全关字段、
    enabled regions 或 active
    claim 漂移均整批零写入。
18. scheduler/monitor=true、confirmation 错误、manifest/SHA/commit 漂移均拒绝。

## 4. PostgreSQL 与 one-shot

19. PostgreSQL 可控交错：等待中的 direct claim、due-selector claim 与 policy CAS 在
    maintenance 成功后均不能领取 claim或产生部分四层状态。
20. maintenance 后 frozen-image wrapper `validate` 使用 read-only transaction 退出 0；
    任何尝试写入导致失败。
21. `restore-policies-coarse` 后 global/region/source 为 restore、event 仍 maintenance；
    第二次 validate 退出 0；`restore-policy-event` 后四层均恢复。
22. coarse replay、event replay 零写；event-before-coarse 拒绝；第二次 validator 失败
    时 event 仍隐藏，修复漂移后能从 coarse-restored 阶段继续。
23. event 924 最终仍指向同一 provisional revision，legacy results、7 条展示结果、
    tracking 和前台“暂定赛果”不变。

## 5. 回归与生产验收

24. 准实时 SQLite 组合、PostgreSQL 专项、Django check、migration drift、compileall、
    Compose config、JSON、shellcheck/diff check 通过。
25. 候选 AMD64 镜像内 registry SHA、Django check、两个新 management command help 和
    rollback wrapper 合约通过。
26. 生产法国 event 733–735 prepare 不再出现 `racecard_schema_invalid`；若为
    not-found/match blocker 则保持 off 并如实记录。
27. 本 change 不开启 scheduler/monitor/regions，不自动 promotion，不执行 official
    网络复核。

## 6. 首次代码审核回归

28. rollback bundle 在 public read admission 不可见、revision 非 dedicated
    provisional、官方复核 route 过期或 observation/revision hash 漂移时拒绝，且零
    artifact、零数据库写入。
29. fresh initializer 遇到任一既有 legacy runner 时拒绝且零 live 写入；已初始化
    replay 精确核对 runner 数量、external ID、号码、名称和额外行，删除、篡改、新增均
    拒绝。
30. P0 同号码 coupled runners 使用不同 external identity participant key，形成两条
    active source；空 external ID 继续兼容号码 key。
31. dynamic update 的号码零匹配但 horse name 全 event 唯一时回退更新；号码多匹配时
    仍只在该号码集合内按唯一名称消歧。
32. unchanged racecard replay 对唯一 legacy `source_refs.external_runner_id` 惰性写入
    新列；多行或新列/旧 refs 冲突时拒绝，observation、tracking 和 runner 均零写。

## 7. 限定复审直接回归

33. 同号码 coupled runner/result 各自携带不同 external runner identity 时一一配对，
    只形成两个 participant/profile/source，不产生四条拆分来源。
34. 相同 external runner ID 但 `source_key` 不同的记录保留两个来源身份空间，不自动
    合并 profile。
35. generated manifest 必须透传 `expected_current_revision_id`；maintenance 后或
    coarse-restored 后 pointer 漂移时，restore 整阶段 policy 零写入。
36. rollback validator 在 scheduler 或 monitor 开启时拒绝，control、tracking、policy
    和 OperationLog 均零写入。
37. 普通 racecard refresh 与 unchanged replay 遇到 runner 新列/source refs 身份冲突
    时，在 observation、tracking、runner、participant、revision 任一写入前拒绝。

## RED 证据要求

- 在生产代码修改前运行用例 1、3、5、8、15；至少分别证明 coupled number、完整落库与 rollback
  生成/maintenance 能力缺失。
- RED 必须是目标断言失败或 command/service 不存在；导入路径、环境或 fixture 错误不算。
- 自动化测试禁止真实网络、生产 PostgreSQL/Redis/队列和 SMTP。
