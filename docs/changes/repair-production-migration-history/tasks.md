# 生产 migration history 一致性修复任务

## 0. 探索与方案

- [x] (operations) 只读核对生产 recorder、receipt schema/constraints/indexes/sequence/rows 与
  `0068/0069` 对象缺失状态。
- [x] (application) 对照 Git migration rename/dependency 时间线，形成双分支汇合方案。
- [x] (operations) 冻结脱敏的 receipt/operation-log count 与 canonical SHA 到受审
  `production_audit.json`。
- [x] (operations) 完成独立方案审核并向用户汇报最终范围，已取得明确实现确认。

## 1. 测试先行

- [x] (application) 新增 production-like graph consistency/plan 测试并取得有效 RED。
- [x] (operations) 新增 leaf-set wrapper/preflight contract 测试并取得有效 RED。
- [x] (application) 新增真实 PostgreSQL legacy/fresh/mismatch/partial-state 与 catalog 漂移测试；隔离
  PostgreSQL 16 migration/catalog 专项 `9/9` 通过。
- [x] (operations) 新增第一次 preflight 后数据漂移、artifact trust 与关闭态二次核验 RED。
- [x] (operations) 新增固定旧镜像在 `0068-only/0069-complete` schema 的受限恢复 RED/fixture；已补
  restricted-recovery marker/binding 合同与隔离 PostgreSQL smoke harness，并以固定生产旧镜像
  `sha256:b1fecc4624ac7fc181197156189b6326a40abb36f287feae72c9a2f533341a73` 完成两态真实容器 smoke。

## 2. 实现

- [x] (application) 恢复 `0070` 的 `0067` dependency，并让 `0071` 汇合 `0069/0070`。
- [x] (application) 实现 recorder/schema/plan/receipt digest 的只读 v2 preflight。
- [x] (operations) 实现 mode `0600` no-clobber before artifact、显式 path/SHA handoff 与关闭态 verifier；
  verifier 失败必须发生在 `migrate` 调用前。
- [x] (operations) 更新 Release B wrapper 的完整 leaf-set、restricted-recovery marker 与只允许同一
  repair candidate forward resume 的合同。
- [x] (operations) 关闭独立 review 的动态 B-to-B leaf、manual fresh handoff、resume fresh partial
  handoff、migrate-success marker transition 四项 P1。
- [x] (operations) 关闭第二轮 review 的 rollback DB binding、partial action gate 与
  active-marker/final-boundary 幂等恢复三项 P1。
- [x] (operations) 关闭第三轮 review 的静态 DB identity baseline、migration 前 durable intent、
  active-marker 全普通入口阻断，以及 `0069` decision/function overload 精确 catalog 合同。
- [x] (operations) 关闭第四轮 review 的最小 audit image packaging、rollback checkout/build 前 host
  marker gate，以及 `0071` partial unique predicate canonical exact equality。
- [x] (operations) 关闭第五轮 review 的 marker 内容到文件对象 TOCTOU：可信 fd 贯穿完成转换，
  link/unlink 前后精确核对 dev/inode/owner/mode，并以受控替换竞态证明 replacement 原位保留。
- [x] (operations) 关闭第六轮 review：final forward-resume 保持 reviewed-static；attempt mode 绑定
  artifact 且 required 不可 no-op；rollback 不依赖后置 v2 marker；0071 index 要求 indislive；完成
  转换改为可崩溃恢复的 active→transition→completed 原子 rename 状态机并彻底移除 path unlink。
- [x] (operations) 关闭完整三 suite 暴露的五项兼容回归：attempt mode 仅由实际含绑定字段的精确
  artifact 激活，旧/non-Release-B retry 清理陈旧 env，保留 race-live freeze/restore 与 stopped resume。
- [x] (operations) 关闭第八轮 finding：初始 `{0070}` marker-bound forward-resume；stopped resume
  host marker gate；Linux/macOS 原子 no-replace rename；Compose override 固定 control image，失败后
  用 mode `0600` control-state 精确续跑且从不把 control image retag 为 `umanewsbot:prod`。
- [x] (operations) 关闭第九轮 P1：为 markerless `not-required` B→B rollback 固定专用重试入口，
  state 绑定初始 artifact/lock token/control/target，失败保留、成功 completed，普通服务恢复不可绕过；
  通用 handoff wrapper 显式拒绝 unsupported reverse，禁止静默 forward。
- [x] (operations) 关闭第十轮 P2：control-state canonical SHA 完整覆盖全部 copied control files 与
  Compose override 的 path/mode/bytes SHA；resume 在 lock 前与锁内以 nofollow fd 复核，标准/lowcost
  的逐文件同 mode 篡改、state 篡改和 symlink replacement 均零副作用拒绝。
- [x] (operations) 关闭第十一次 P1/P2：completed control receipt 以 target OID + initiating artifact
  SHA + state SHA 标识 attempt，并用 no-clobber hard-link/idempotent completion；连续两次同 target
  rollback 生成独立 receipt，同 attempt 重放不覆盖。同步修正 rollout 全文陈旧状态。
- [x] (operations) 关闭第十二轮 P1/P2：repair runtime parent 先验且只由持锁普通入口安全初始化；
  stopped resume 对缺失/不可信空 parent fail closed；rollback retry 携带完整 attempt identity，并在
  active 缺失时精确可信验证 completed receipt 后零 Git/Docker/Compose 幂等返回。
- [x] (operations) 关闭第十三轮两个 P1：保留仅限 pre-0070 首次纳管的 historical runner install
  one-shot，阻止无 flag/0070+ 绕过 v2；旧 image smoke 改为专用 PostgreSQL read-only role、权限撤销、
  启动前写拒绝 probe、管理员 digest 与容器/日志 fail-closed。
- [x] (operations) 关闭第十四轮 P2：preflight 先收集/验证 recorder+catalog contract，再允许 receipt
  live audit；schema drift 输出 deterministic JSON/CommandError，OperationalError 不降级；PostgreSQL
  drop-table/drop-column fixture 显式恢复。
- [x] (operations) 关闭第十五轮 P1/P2：rollback target 0071 使用 `git show` exact SHA/dependency
  allowlist，在 checkout/build 前拒绝 placeholder/依赖/operation 漂移；receipt constraint/index 改为
  完整集合精确比较，并用真实 PostgreSQL 覆盖额外 CHECK、UNIQUE、INDEX。
- [x] (operations) 关闭第十六轮 P1：rollback 拆为 pinned-control migrate-verify、exact-target
  collectstatic、pinned-control complete-intent；目标 image ID 前后绑定 artifact，失败保留 state 且
  standard/lowcost、markerless retry、required forward-resume 均可安全重试，不改变 normal deploy。
- [x] (operations) 关闭第七轮 P1：rollback 在 checkout 前保存 v2 control scripts/image，目标 pre-v2
  helper 不负责 artifact 或 one-shot；artifact 仍绑定目标 commit/image，成功后才切目标应用镜像。

## 3. 验证与审核

- [x] (application) 运行 SQLite 与真实 PostgreSQL GREEN、迁移往返和聚焦回归。
- [x] (operations) 用固定生产旧镜像 digest 在两个 partial PostgreSQL schema 执行关闭 flags 的
  web/worker/beat 启动、health/ping/只读 SQL/零写 smoke。
- [x] (operations) 运行本 change 的 Django/migration/Compose/shell/diff 与相邻发布编排门禁；结果记录
  于 `test_cases.md`。
- [x] (operations) 完成十六轮 read-only review/finding 修订；当前已知 finding 清零。
- [x] (operations) 关闭发布前 P2：provenance 仅由 artifact-bound forward-resume 使用；普通
  deploy/manual/rollback/initial-install 双层清理旧环境，并补残留 SHA 的 RED→GREEN 回归。
- [x] (application) 关闭最终 commit review P2：两个 `0071` partial unique index 精确绑定 owning
  schema/table，并补 pure 与 PostgreSQL wrong-table 恢复 fixture。
- [ ] (operations) review 后向用户申请当前精确 fingerprint 的 commit/push/PR/merge/生产发布授权。

## 4. 后续发布

- [ ] (operations) 新建备份与 rollback image，运行候选 v2 preflight，部署 `0068/0069/0071`。
- [ ] (operations) postflight 验证 receipt digest、leaf/plan、flags、容器/HTTP 与队列。
- [ ] (operations) 仅在 Release B 部署证据通过后生成并审核 v2 census。
- [ ] (operations) census 门禁通过后执行生产回填，再启动并监控 2025 full-network。
