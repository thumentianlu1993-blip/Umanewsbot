# `prepare-lifecycle-shadow-enrollment` 独立方案审核交接

## 1. 审核身份与范围

你是未参与本方案编写的独立 reviewer。全程只读，只审核本 change 的文档设计与它引用的
既有 lifecycle 代码事实，不修改文件、不实现、不联网、不连接生产。

工作目录：
`/Users/mentianlu/Code/umanews/.worktrees/prepare-lifecycle-shadow-enrollment`

基线：
`origin/main@43b81fd3288a1e7b997ffad78d03565327e3d990`

## 2. 必读文件

1. 根 `AGENTS.md`
2. `docs/codex_workflow.md`
3. 本目录 `spec.md`
4. `design.md`
5. `test_cases.md`
6. `tasks.md`
7. `rollout.md`
8. `HANDOFF.md`

核对事实时读取：

- `server/stable/services/race_event_lifecycle.py`
- `server/stable/management/commands/reconcile_race_event_lifecycle_controls.py`
- `server/stable/tasks.py`
- `server/stable/models.py`
- `server/stable/test_race_event_lifecycle.py`
- `server/stable/test_race_event_lifecycle_postgres.py`

## 3. 当前事实

- 阶段 A 已部署但生产保持 `false/off`；
- 当前生产 control/transition 为 0；
- 未来 90 天 172 场重点赛事 `race_datetime` 为 0；
- 未来 45 天 85 场中 6 场地区时区错误为 `Asia/Shanghai`；
- 现有 v1 manifest dry-run 只提取 IDs，没有执行 apply 的完整 schema/US zone/frozen
  eligibility/schedule 校验；
- 本 change 只准备 manifest v2 和首次 shadow control 纳管，不打开功能。

## 4. 重点攻击

请逐项检查：

1. 是否重复建设既有 lifecycle 状态机、control、scheduler 或 race-live 链；
2. strict manifest v2 是否真的能消除手工 JSON 和 dry-run/apply 差异；
3. content SHA、文件 SHA、自引用和 canonicalization 是否自洽；
4. event/control CAS 是否覆盖取消、下架、时区、日期/时间、人工锁和并发 control；
5. 单事务 ≤20 场、排序锁、replay/不同 manifest 规则是否会死锁或产生部分提交；
6. v1 兼容是否可能绕过 v2 shadow-only 生产入口；
7. 美国 allowlist、英国/法国 DST、无时间当地午夜语义是否正确；
8. `local_start_time` 是否被错误当作绝对时间；
9. control apply 与全局开关启用是否真正分离；
10. false/off 下 apply、true/shadow、mid-flight disable 和回滚是否闭环；
11. 当前无 `race_datetime` 时，方案是否诚实限定了线上可验证范围；
12. 测试矩阵是否能取得真实 RED，并覆盖 PostgreSQL 并发和零业务副作用；
13. 生产选择、观察、停止条件和与其他批次互斥边界是否可执行；
14. 是否遗漏模型/migration/配置变化或夸大现有能力。

## 5. 输出

先列 findings，按 P0/P1/P2/P3，给出 `文件:行`、触发场景、影响和建议。再给：

- 状态机/时区/并发/事务/回滚结论；
- 测试覆盖结论；
- 残余风险；
- 最终结论 `APPROVED` 或 `REVISE`。

存在任何开放 P0/P1/P2 时不得 APPROVED。只读命令不可用或审核范围无法完成时输出
`BLOCKED`，不得猜测通过。

## 6. 首轮 reviewer findings 与修正

同一 reviewer session `019fb494-dfc3-7c71-a543-fa75421ef21a` 首轮结论 `REVISE`：

1. P1：v2 apply 没有技术强制 `false/off`，enabled worker 可能在 verify/二次授权前 claim。
   已在 spec/design/rollout/tasks/tests/HANDOFF 锁定写前 settings 硬门禁、Beat/worker
   运行态 preflight、零 active/reserved/claim，并增加四种错误组合 RED。
2. P1：保留 v1 apply 可绕过 v2 的 shadow-only、≤20、CAS 和整批事务。
   已锁定 v1 永久 dry-run/read-only compatibility，任何 v1 apply 零写拒绝，并增加 mode/
   批量边界 RED。

限定复审只需确认两项 P1 已闭环及修正直接触及路径；如有直接 P0/P1 回归可继续阻断，
其他新建议记录后结束。

## 7. 限定复审结论

- reviewer session：`019fb494-dfc3-7c71-a543-fa75421ef21a`；
- 原生 reviewer 启动头确认 `sandbox: read-only`；
- 两项 P1 均关闭；
- 没有新的直接 P0/P1；
- 最终结论：`VERDICT: APPROVED`。

残余风险：

- 当前只批准方案，代码尚未实现，必须先取得真实 RED/GREEN 再做独立代码 review；
- 生产 apply 当时仍须重新核验 Beat/worker 配置、active/reserved 和有效 claim；
- 当前生产无 `race_datetime`，首批线上观察只能证明无时间路径。

## 8. 实现完成后的独立代码 review 交接

用户已明确“确认实现”。以下实现由测试子代理和实现子代理完成，代码 reviewer 不得复用
方案 reviewer 身份，必须只读审核全部未提交变化。

### 8.1 精确应用与测试文件

- 新增 `server/stable/services/race_event_lifecycle_enrollment.py`；
- 新增 `server/stable/management/commands/prepare_race_event_lifecycle_enrollment.py`；
- 修改 `server/stable/management/commands/reconcile_race_event_lifecycle_controls.py`；
- 新增 `server/stable/tests/test_race_event_lifecycle_enrollment.py`；
- 新增 `server/stable/test_race_event_lifecycle_enrollment_postgres.py`；
- 本目录规格/交接与四份仓库状态文档仅作状态同步。

没有模型、migration、settings、Beat、Compose 或 provider 变化。

### 8.2 TDD 与验证证据

- 初始真实 RED：13 项中 10 errors 来自 prepare 命令不存在，1 failure 证明 v1 apply
  仍能创建 control，另 2 项通过；不是 fixture、迁移、语法或环境错误。
- 第二个真实 RED：显式 event `9/10` 时 canonical `sort_keys` 按字符串输出 `10/9`，
  producer 生成的 manifest 被 loader 自拒绝；修复为 `events` key 按整数排序且所有
  content/raw SHA 与 loader 共用同一 canonical encoder。
- SQLite enrollment 30 项 + 既有 lifecycle 56 项：`86/86 OK`。
- 日历/页面/字段/race-live/scheduled-result 相邻回归：`190/190 OK`。
- 临时、无持久卷的隔离 PostgreSQL 16 容器中，新增双 apply + 既有 lifecycle 并发：
  `6/6 OK`；容器已停止并自动删除。
- `manage.py check`、`makemigrations --check --dry-run`、`git diff --check` 通过。

### 8.3 代码 reviewer 重点攻击

1. strict loader 是否真的拒绝 BOM、重复 key、NaN/Infinity、未知/缺失字段、symlink、
   非普通文件、超限文件和非 canonical 字节；
2. numeric event key canonicalization 是否确定、无递归误伤，content/raw SHA 是否自洽；
3. prepare 输出目录校验与原子 rename 是否可能经祖先 symlink、`..` 或既有路径越界；
4. prepare 是否数据库零写，资格/US zone/aware time/人工锁门禁是否整批 fail closed；
5. v2 dry-run/apply 是否共用相同 loader 与 CAS；apply 缺 SHA/commit/confirm 是否零写；
6. strict `false/off` 是否在任何锁/写前 fail closed；服务函数是否存在可绕过命令门禁的
   生产调用面；
7. apply 的 event/control 排序锁、事务、并发 create/replay 是否在 PostgreSQL 下无
   死锁、重复或部分提交；
8. replay 是否精确且不改变 generation、next refresh、claim、transition；不同 manifest
   是否绝不更新现有 control；
9. v1 dry-run compatibility 是否保留，但所有 v1 apply 变体均不可达旧写链；
10. 是否错误推导 `local_start_time`、改变赛事状态、dispatch provider/race-live/news/QQ，
    或引入隐式全表/N+1；
11. 测试是否 load-bearing，是否遗漏 manifest expiry、DB drift、跨位数 ID 和真实 PG 并发；
12. 文档是否诚实保持“未 commit/push/PR、未部署、未生产 apply、未打开 lifecycle”。

有任何 P0/P1/P2 finding 时结论必须 `REVISE`。审核通过后主线程才可冻结实现 fingerprint，
并仍须停止等待 commit/push/PR 授权。

## 9. 首轮代码 review findings 与修复

独立 reviewer session `019fb637-a018-7f43-a119-4f54f55cba00` 原生启动头确认
`sandbox: read-only`，退出码 0，审前/审后 fingerprint 均为
`353496ea86a961f9fe250d9eae0ec570c2ef6886c28ecffc56d41d267c93d663`。
结论 `REVISE`，共 1 项 P1、3 项 P2：

1. P1：`apply_enrollment()` 服务可绕过命令层 strict `false/off` 门禁。已把同一硬门禁
   下沉至服务，并保证在 `transaction.atomic()`、锁和写之前执行。
2. P2：preflight 用 frozen `generated_at` 重算决策，未过期 manifest 跨时间边界后仍可
   apply。已让 preflight/apply 使用当前 aware `now` 重算，决策动作/目标/原因/错误漂移
   即整批拒绝，并在 preflight 重新检查 expiry。
3. P2：artifact 只检查直接父目录，间接祖先 symlink 可越界。已逐级 `lstat` 全部现有
   祖先并拒绝可控路径中的 symlink/非目录。
4. P2：schema peek 在 strict loader 前无界 `read_bytes()`。已让 peek/loader 共用
   1 MiB 有界 reader，并使用 `lstat`、`O_NOFOLLOW`、`fstat` inode/size 二次校验。

四项均先取得真实 RED；修复后 SQLite enrollment 23 + lifecycle 56 为 `79/79 OK`，
隔离 PostgreSQL 复跑仍为 `6/6 OK`。同一 reviewer 会话下一轮只需复核上述 finding
及其直接触及路径。

## 10. 第一轮限定复审 findings 与修复

同一 reviewer 复用 native session `019fb637-a018-7f43-a119-4f54f55cba00` 后仍为
`REVISE`，新增 3 项直接 P2：

1. public `preflight_enrollment/apply_enrollment(now=...)` 可由调用者回拨时间。已移除
   两个公开签名的 `now` 参数，内部只读取 `django_timezone.now()`；测试通过 patch clock，
   生产调用者不能注入时间。
2. `/var`、`/tmp`、`/etc` 字符串 alias 例外违背全祖先 symlink 拒绝。已删除全部例外，
   且额外 RED 证明 prepare 命令也不得预先 resolve 用户 output-dir 来绕过 writer；
   命令现原样传递路径。
3. bounded reader 缺少读后复核。已在读取后再次 `fstat`，对 dev/ino/size/mtime_ns/
   ctime_ns 做 lstat/open/read 三阶段一致性校验，并核对读取字节数等于稳定文件大小。

上述三项和命令层 alias 绕过均先取得真实 RED。修复后 SQLite enrollment 27 +
lifecycle 56 为 `83/83 OK`；隔离 PostgreSQL 再次实跑 `6/6 OK`。下一轮仍复用同一
reviewer session，只复核本节直接触及路径。

## 11. 第二轮限定复审 finding 与修复

同一 reviewer 第二轮限定复审仍为 `REVISE`，剩余 1 项直接 P2：writer 在祖先检查后仍
使用路径名 `mkdtemp/os.replace`，验证与发布之间可把可写 parent 替换为 symlink。

测试先用真实竞态把已验证 parent rename 后替换为 attacker symlink，旧实现确实在 attacker
下留下 `artifact/manifest.json` 和 `summary.json`。修复后：

- 从根目录起逐级 `O_DIRECTORY|O_NOFOLLOW` + `dir_fd` 打开祖先并保留稳定 parent fd；
- staging、两个文件和最终 rename 都只使用相对稳定 fd 的操作；
- 文件使用 `O_CREAT|O_EXCL|O_NOFOLLOW` 完整循环写入并 fsync；
- 发布前后重开原 parent 路径并核对 dev/ino；
- 失败和漂移仅通过稳定 fd 相对清理；平台缺少安全 dir_fd 能力时 fail closed。

更新后的竞态测试通过 `os.mkdir` hook 确认攻击实际发生，writer 正确拒绝，attacker 与
moved parent 均零残留，不是空转。SQLite enrollment 28 + lifecycle 56 为 `84/84 OK`；
隔离 PostgreSQL 最新复跑仍为 `6/6 OK`。下一轮继续复用同一 reviewer session。

## 12. 第三轮限定复审 finding 与修复

同一 reviewer 第三轮限定复审仍为 `REVISE`，剩余 1 项直接 P2：staging 名称未与已打开的
`staging_fd` 绑定；攻击者可移走原 staging，再以 replacement 占用同名，导致发布替身。

真实 RED 证明旧实现会发布包含 `attacker.marker` 的 replacement，并在被盗 staging 留下
manifest/summary。修复后：

- 记录 staging fd 的 dev/ino；
- rename 前 no-follow stat staging name，rename 后 no-follow stat output name，均必须匹配；
- 未知 replacement 只通过稳定 parent fd 移入随机 quarantine，绝不删除不属于本进程的内容；
- 已拥有 staging 通过 fd 删除两个文件，再扫描 parent fd，按 inode 找到真实名称并只 rmdir
  匹配目录，不按未经验证的名称删除。

更新后的攻击测试确认实际完成名称交换，writer fail closed，公开 output 不含攻击者内容，
被盗 staging 不残留 manifest/summary。SQLite enrollment 29 + lifecycle 56 为
`85/85 OK`；PostgreSQL 最近一次真实证据保持 `6/6 OK`。下一轮仍复用同一 reviewer。

## 13. 第四轮限定复审 findings 与修复

同一 reviewer 第四轮限定复审仍为 `REVISE`：

1. P2：cleanup 扫描匹配 inode 后再 `rmdir(name)` 仍可被换绑并误删未知空目录；
2. P2：staging-swap 测试未证明 unknown replacement 的 marker 在 quarantine 中完整保留。

修复策略收窄失败清理权限：不再扫描 parent、不再按名称 stat/rmdir，只通过已持有的
staging fd 删除本进程创建的 manifest/summary 并 fsync；允许留下空 owned staging，
避免为“清理干净”扩大删除权限。测试同步锁定空 staging 可残留但必须递归为空。

quarantine 测试现强断言唯一 quarantine 仅含完整 `attacker.marker` 字节，不含
manifest/summary；公开 output 与 stolen staging 无业务 artifact。三项竞态测试
`3/3 OK`，SQLite enrollment 30 + lifecycle 56 为 `86/86 OK`。下一轮继续复用同一
reviewer session。

## 14. 第五轮限定复审 finding 与修复

同一 reviewer 第五轮限定复审仍为 `REVISE`，剩余 1 项直接 P2：staging 已 rename
为公开 output 后，如果最终 parent path 身份复核失败，异常清理虽然会通过 owned fd
清空两个文件，却会把公开 output 目录名留在原位，使失败批次占住目标路径并阻断安全重试。

真实 RED 通过只让 rename 后第二次 `_verify_parent_path()` 失败，证明旧实现拒绝了批次，
但公开 output 仍存在且同路径重试失败。修复后：

- 记录发布 rename 是否已经尝试；
- 此后任何 `EnrollmentError` 或 `OSError` 都先通过稳定 parent fd 把当前公开名称移入随机
  quarantine，再通过 owned staging fd 删除本进程生成的 manifest/summary 并 fsync；
- 不按名称删除 quarantine，避免误删并发替换者；成功隔离后公开名称释放，同路径可重试；
- 如果隔离本身失败，错误同时报告原始失败和隔离失败并保留原始异常链，不猜测清理成功。

新增回归断言失败时第二次校验确实发生、公开名称消失、parent 下不残留 manifest/summary，
且随后同路径发布成功。主线程复验 SQLite enrollment 31 + lifecycle 56 为 `87/87 OK`；
Django check、migration drift 与 `git diff --check` 通过。下一轮继续复用同一 reviewer
session，只复核本节及其直接触及路径。

## 15. 第六轮限定复审 finding 与修复

同一 reviewer 第六轮限定复审仍为 `REVISE`，剩余 1 项直接 P2：
`publish_rename_attempted=True` 在 `os.rename()` 成功前置位。若发布前 absence 检查后
并发者创建非空 output，rename 自身失败，旧异常路径仍会移动竞争者目录。

新增 load-bearing 测试在 rename hook 中创建含 marker 的竞争者 output，并使 rename
真实失败。旧实现的 RED 证据为：攻击发生且 writer 拒绝、业务 payload 未泄漏，但竞争者
inode/marker 从公开路径消失，并出现一个 quarantine。

实现把状态收窄为 `publish_rename_succeeded`，只在 `os.rename()` 成功返回后置位。因此：

- rename 自身失败只清理 owned staging fd，绝不隔离、移动或删除竞争者 output；
- rename 成功后的最终校验失败仍会隔离公开名称并释放同路径；
- 两个相反分支由 conflict 与 post-rename verification 两项测试共同锁定。

主线程复验 SQLite enrollment 32 + lifecycle 56 为 `88/88 OK`；Django check、
migration drift 与 `git diff --check` 通过。下一轮继续复用同一 reviewer session，
严格复核本节直接触及路径。

## 16. 第七轮限定复审 finding 与修复

同一 reviewer 第七轮限定复审仍为 `REVISE`，剩余 1 项直接 P2：普通 POSIX
`os.rename()` 可原子覆盖并发创建的空目标目录；上一轮非空 marker 测试只会让 rename
报错，未覆盖这个成功覆盖分支。

新增 load-bearing 测试在最终发布调用前创建空 output 并记录 inode。旧实现真实 RED：
攻击发生但 writer 未拒绝，竞争者 inode 被覆盖，公开 output 出现 manifest/summary。

修复后公开发布不再使用普通 rename：

- Linux 使用 libc `renameat2(..., RENAME_NOREPLACE)`；
- macOS 使用 libc `renameatx_np(..., RENAME_EXCL)`；
- 两者均设置明确 `ctypes` argtypes/restype 并按 errno 处理；
- 目标已存在时拒绝且保持原位；平台、libc symbol 或 ABI 能力缺失时在写 artifact 前
  fail closed，绝不回退普通 rename 或 check-then-rename；
- 普通 stable-dirfd rename 只保留给失败后的隔离路径。

staging swap、非空竞争者、空竞争者三项 hook 均已迁移至 no-replace primitive 前，
断言未降级。主线程复验 SQLite enrollment 33 + lifecycle 56 为 `89/89 OK`；
Django check、migration drift 与 `git diff --check` 通过。下一轮继续复用同一 reviewer
session，严格复核本节直接触及路径。

## 17. 第八轮限定复审 finding 与修复

同一 reviewer 第八轮限定复审仍为 `REVISE`，剩余 1 项直接 P2：预检只加载 libc
symbol，没有在业务 artifact 写入前证明当前 kernel、flag 和 output parent 文件系统
支持原子 no-replace；`ENOSYS/EINVAL/EOPNOTSUPP` 等直到 staging 写入后才暴露。

测试先取得两项真实 RED：

1. primitive 在真实调用时返回 `ENOSYS`：最终虽拒绝，但 `_write_relative_file`
   已调用两次；
2. 错误 overwrite primitive：没有语义预探针，writer 未拒绝且业务写入已发生两次。

实现现于稳定 parent fd 所在同一文件系统、任何 manifest/summary 写入前执行无业务数据
探针：创建两个随机 48 位 token、mode 0700 的空目录，调用同一 primitive，必须观察到
目标已存在冲突，且源/目标 inode 均保持。运行时不支持、错误成功覆盖或身份漂移均 fail
closed，业务写入次数为 0。

由于没有跨 Linux/macOS 的 identity-addressed directory unlink，按名称 rmdir 会重引入
第四轮已禁止的换绑删除竞态；因此探针空目录作为无业务数据的 owned residue 保留。测试
只允许 source/target 各一个严格命名的普通非 symlink 空目录，并强制递归为空、无
manifest/summary/marker；其他攻击者、公开 output 与 moved staging 断言不降级。

主线程复验 SQLite enrollment 35 + lifecycle 56 为 `91/91 OK`；Django check、
migration drift 与 `git diff --check` 通过。下一轮继续复用同一 reviewer session，
严格复核本节直接触及路径。

## 18. 第九轮限定复审结论

同一独立 reviewer 原生 session `019fb637-a018-7f43-a119-4f54f55cba00` 在
`sandbox_policy=read-only`、`approval_policy=never`、网络受限下完成第九轮限定复审，
命令退出码 0。

本轮确认第八轮 P2 关闭，无新的 P0/P1/P2/P3 finding，最终
`VERDICT: APPROVED`。reviewer 逐项确认：

- 探针先于 staging 和任何业务 payload 写入；
- 使用同一稳定 parent fd，且只接受冲突与双 inode 不变；
- unsupported、错误覆盖和身份漂移均在零业务写入时 fail closed；
- 最多两个空 inode residue 在一次性受控命令边界内不构成现实 P0–P3 DoS；
- staging swap、空/非空竞争者、rename 后校验/隔离路径均未回归。

审核前后 fingerprint 均为
`3932d1fdcc9efc4aff8b3c605058fea466d2ff46a1d7adeb4a7001df74c749ef`，
content manifest 均为
`d00c33163153d2bbc90813dd96ea09135c2f41aa07d4831cb566fa10d6d507e0`，
HEAD 为 `43b81fd3288a1e7b997ffad78d03565327e3d990`。reviewer 全程未修改文件、
未运行容器、未联网或连接生产。

本节及状态文档只追加 review evidence，不改变应用、测试、迁移或配置行为；追加后需冻结
新的 evidence fingerprint，并做一次 evidence-only 一致性复核。

## 19. 最新 main 基线迁移与发布准备

用户于 2026-08-01 明确授权在完成最新主线整合、复验和复审后直接 commit、push、创建 PR
并合并；该授权不包含部署、迁移、生产写入、control apply 或打开 lifecycle。

`origin/main` 从原审核基线 `43b81fd3` 前进三跳至 `1cdd066b`：

- `d70971c2 Fix historical race calendar integrity`；
- `a0ec60a1 Fix workflow review command records`；
- `1cdd066b Merge PR #55: Fix historical race calendar integrity`。

本 change 先完整 stash，分支快进到 `origin/main@1cdd066b` 后恢复。应用/测试文件无冲突；
`docs/current_state.md`、`docs/decisions.md`、`docs/project_status.md` 三处冲突采用保留主线
历史赛历事实、随后追加 lifecycle 事实的方式解决，`docs/deploy_runbook.md` 自动合并。

最新基线验证：

- lifecycle enrollment + 既有 lifecycle SQLite：`91/91 OK`；
- 新主线赛事年份/当前赛事描述符：`20/20 OK`；
- 隔离 PostgreSQL enrollment + 既有 lifecycle 并发/事务：`6/6 OK`；
- Django check、migration drift、`git diff --check`：通过；
- 原相邻套件 190 项为 `187 passed / 3 errors`；相同 3 个
  `public_year/local_date` fixture error 已在独立干净 `origin/main@1cdd066b` worktree
  逐条复现，属于 PR #55 引入的主线既有测试问题，不在本 change 顺带修改。

临时干净 main worktree 和无卷 PostgreSQL 测试容器均已删除。最新基线迁移使此前
`5f8e35b8…f7072` fingerprint 失效；必须由同一独立 reviewer 复核主线增量、文档合并和
直接模型交互路径，通过后再冻结发布 fingerprint。
