# Codex 原生执行流程

## 定位

本文件只描述 Umanews 的执行方法，不定义人工确认门禁。所有任务、代理和 worktree 的人工确认
边界唯一以仓库根 `AGENTS.md` 的 G1/G2/G3 为准；本文件与其冲突时，以根文件为准。

## 1. 定位与隔离

1. 读取根 `AGENTS.md` 和 `docs/session_bootstrap.md`，按任务关键词读取当前状态、决策和运维文档。
2. 运行 `git status --short --branch`、`git worktree list --porcelain`，确认当前 worktree、分支、脏改动和并行资源。
3. 主工作区有无关改动时，从最新 `origin/main` 创建独立 `codex/<slug>` worktree；不在共享目录切分支或清理文件。
4. 只读检查先行。可从仓库和运行态直接确认的事实，不向用户反问。

## 2. 按风险规划

- 小型修复：记录目标、非目标、受影响文件、验证和回滚即可。
- 大功能、跨模块、架构、迁移或高风险生产工作：在 `docs/changes/<slug>/` 按需维护：
  - `spec.md`：范围、非目标、用户行为和验收标准；
  - `design.md`：架构、数据流、状态、并发、迁移、性能和回滚；
  - `test_cases.md`：正常、边界、失败、回归和生产形状验证；
  - `tasks.md`：使用 `(application)`、`(integration)`、`(operations)` 前缀，按测试、实现、验证排列；
  - `rollout.md`：worktree/运行任务影响、上线顺序、恢复点和交接状态。
- 不为了满足模板而制造无内容文档；需要持久化的关键边界必须写入仓库，而不是只留在对话中。

## 3. 测试与实现

- 行为变化优先新增最小测试并确认有效 RED；失败必须来自目标能力缺失，而不是环境、fixture 或语法错误。
- 完成最小 GREEN 后运行受影响回归，再做不扩大范围的 REFACTOR。
- 数据库变化覆盖迁移图、约束、旧数据兼容、PostgreSQL 语义和回滚。
- Celery 变化覆盖幂等、重复投递、retry、锁/lease、队列路由、worker 崩溃和部分成功。
- 外部集成自动测试使用 fixture/mock，不访问真实网络或生产服务。
- 纯文档和治理整理可不制造自动化 RED，但必须运行 Markdown/脚本解析、引用扫描、契约测试和 `git diff --check`。
- 技术 review finding 默认直接修复、补测试并复验；产品或范围变化按根 `AGENTS.md` 处理。

## 4. 独立 review

- reviewer 必须未参与本轮实现且保持只读。
- 未提交改动使用 `codex review -c 'sandbox_mode="read-only"' --uncommitted`。
- committed/base 范围先解析为不可变 OID；工作树不 clean 时不使用 committed/base review。
- review 前后使用 `.codex/scripts/review_fingerprint.py` 对相同 scope 取指纹；内容变化时重新审核变化及直接回归路径。
- actionable findings 返回原 reviewer 上下文复审；无法恢复时记录 findings 和范围后再交接。
- review 结论、CI、测试和指纹是自动技术检查，不自行定义人工确认点。

## 5. Git 与并行协作

- 每个线程只修改自己的分支/worktree；分支前缀统一为 `codex/`。
- 长脚本使用固定 SHA/镜像，禁止从会被合并更新的共享目录运行。
- commit 只包含当前任务文件，不夹带用户或其他线程改动。
- PR 优先远端合并；本地集成使用临时分支，不直接 checkout/修改 `main`。
- integration lock 只覆盖短时整合；production release lock 覆盖部署、迁移、配置、重启和冲突生产任务。
- 资源锁与 release coordinator 的具体约束见根 `AGENTS.md`，不得在任务文档中另写一套。

## 6. 发布包与生产验证

准备发布时形成单一发布包，至少包含：

- PR/commit SHA 与受影响服务；
- 迁移计划、配置/开关变化、数据动作和兼容顺序；
- 当前 production HEAD、镜像、队列、锁、active/reserved task、磁盘/内存和健康状态；
- 备份/恢复点、回滚命令、验收入口和停止条件。

生产动作按根 `AGENTS.md` 的 G2/G3 执行。获准包内的 prepare、backup、deploy、migrate、
restart 和 smoke 连续推进；实际 SHA、manifest、环境、资源或影响范围漂移时 fail closed。

验证必须区分：

- 仓库预期；
- 本地/CI 结果；
- 生产服务器真实状态；
- 公网用户可见结果。

容器运行、TCP 可达、HTTP health、业务发布和外部送达互不替代，不得猜测成功。

## 7. 文档收尾

按根 `AGENTS.md` 的“文档回写”条件更新真正受影响的文档。历史记录只写事实、版本、证据、
失败和回滚，不复制通用门禁。完成前运行：

```bash
python3 .codex/scripts/check_workflow_contract.py
python3 .codex/scripts/test_workflow_contract.py
git diff --check
```
