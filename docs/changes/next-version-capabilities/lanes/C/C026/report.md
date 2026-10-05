# C026 ORM loader/detail 实施断点

任务 `C026-O03-ORM-LOADER-DETAIL-IMPLEMENT-001`，按 C024 `aa1b0bd060d71463cfc0f94d452ef53b1f0aad18` 与原 R `f3199e5fa049768ea6505caf6c2a5c3d01426e63` 的已审局部方案继续。当前为测试准备完成、等待 ROOT 共享 PG 资源；未实现读取行为，未取得 RED/GREEN，不能视为交付通过。

- 新 managed worktree：`/Users/mentianlu/.codex/worktrees/c026-orm-loader-detail/umanews`。
- 独立分支：`codex/c026-orm-loader-detail`。managed 工具初始 detached 状态已在本 worktree 纠偏，保存既有提交，无旧 worktree 切换。
- stacked 基线：`78c65869166d3f56b0f8fc8469e8415dd78be121`，依赖 PR238 尚未合并；没有修改其候选。
- 冻结测试 source：`c6205d4fa02d5440e0b7a25b303bcb25ba473801`，tree `cc69f1d171d0f957ffe239216abf3e373f7eaa5c`；14 个 canonical test methods。
- owned paths：新 `public_probe_orm_loader.py`、新 `test_public_probe_orm_loader.py`、独立 `public_probe_orm_fixture.py` 及本 C026 文档。未改 views/templates/adapter/models/settings/shared mapping。
- loader 只有显式无行为 TDD 桩 `return None`；合法 fixture 先通过真实 read gate/Client 后，其 snapshot 非空断言才可成为实际行为 RED。当前没有运行，不能用导入/fixture/setup 错误代替 RED。
- fixture 从现有 provisional policy 结构独立建立，无全允许 gate mock。同名 participant 有不同显式 source identity；另有 multisource 已发表 fetch 到期不撤销、identity revoke 拒绝样本。
- 静态检查通过：三个新增 Python 文件 py_compile、git diff --check。核对 RaceEvent.save 自动创建 canonical registry 后移除 fixture 重复 create。静态检查不证明 PG/Client fixture 可运行。

完整预先测试设计见同目录 `test_cases.md`；涉及顶层只读 RR、事务恢复、外层拒绝、快照期间 writer 真正提交/退出后新查询、projection 身份/字段、匿名 Client、缺件与白名单。无 source/execution/F01 完整证据则保持 unverified，无 public_verified/O03/SLA 成功。

最小待运行两方法：`PublicProbeOrmPostgresTests.test_fixture_passes_existing_read_gate` 与 `test_loaded_rows_match_real_anonymous_detail_without_public_proof`。计划文件及 14 项 ID 列表在 `/Users/mentianlu/.codex/runtime/c026-orm-loader-detail-001/`。使用既有未改标准 runner，最小 RED 预计 <1分钟，获资源后再实现同例 GREEN 和完整新模块必要回归；shared mapping 交 ROOT 依据实际 IDs 登记。

起点 2026-10-05 14:14:14 Asia/Shanghai、额度 used71%。本轮停止条件为30分钟或used73%先到；截至冻结仍used71%。未启动容器/PG/VM、网络抓取、下载依赖、付费/reset/换模或 proof 基础设施；等待资源为 ROOT 调度，不是新增人工门禁。原 C025/旧 C023 worktree 保留。原G1覆盖局部实施，交付门禁统一引用根 AGENTS.md。
