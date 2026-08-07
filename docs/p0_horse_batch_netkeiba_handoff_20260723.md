# P0 马滚动补全（netkeiba 路径）专项交接文档

更新日期：2026-07-23（交接时状态快照）

## 1. 文档目的

本文供后续模型直接接手「P0 马滚动补全 + 公开展示」工作链。汇总项目背景、需求链、
已完成事项、当前断点、下一步操作和全部必要环境信息。

开始任何操作前，依次阅读：

1. `AGENTS.md`
2. `docs/current_state.md`（状态主文档，与本文冲突时以它和生产实时核验为准）
3. `docs/p0_horse_information_completion_handoff.md`（P0 专项总交接）
4. `docs/deploy_runbook.md`（生产操作手册，含本专项两节）
5. `docs/decisions.md`
6. 本文件

## 2. 项目整体背景

UmaNews 是面向中文用户的日本及全球赛马资讯平台：Django + PostgreSQL + Celery +
Redis + Docker Compose + Nginx，具备新闻采集翻译、术语保护、后台审核、网页发布、
赛事总账/详情、马匹详情等能力。

生产环境：

- 服务器：`root@47.239.167.86`（仅此一台，不要用其他服务器）
- 项目目录：`/opt/umanewsbot`，Compose：`docker-compose.prod.lowcost.yml`
- 公开健康检查：`http://umafans.run/healthz/`
- 生产当前 HEAD：`3d573583`（main 分支，代码镜像内置，改代码必须重建镜像）
- 主机资源紧张：2 vCPU / 4 GiB / no swap。历史 OOM 先例：禁止无地区全量单事务
  P0 sync；批处理一律按地区分批、单事务 ≤500 profile、串行窗口。

P0 马定义：active 且有中文译名的 horse 术语 ∪ 五地区（日本/中国香港/英国/法国/
美国）G1-G3、J-G1-G3、JpnⅠ-Ⅲ 重点赛事全部参赛马。当前 46,318 匹 profile、
56,745 条来源。**最终目标：46,318 匹全部在前台 `/horses/` 展示。**

## 3. 需求链全景（五个 旧规格流程 change）

| change | 状态 | 内容 |
| --- | --- | --- |
| `complete-p0-horse-profile-data` | 已归档 | 马匹资料底座、50 匹严格完整资料生产写入 |
| `productize-p0-horse-batch-completion` | 已归档 | 滚动批次流水线（select→approve→prepare→bundle→commit） |
| `enrich-p0-horse-external-identity` | 完成（含生产） | 离线身份回填：日本 2,462 netkeiba key、香港 327 hkjc key、法国 1,773 zeturf 证据 |
| `publish-p0-horses-basic-tier` | tasks 7.2/7.4 未完 | BASIC 发布门禁 + 批次自动首发 + 存量发布命令 |
| `add-netkeiba-horse-client` | tasks 5.1-5.2 未完 | netkeiba ID 直取客户端（解开 JBIS 同名歧义） |

关键产品决策（用户 2026-07-22 确认）：

1. 公开门槛 = BASIC 层：名称 + 五地区 +（`horse_identity_verified_keys` 认可
   namespace（netkeiba/nar/hkjc/sporting_life）或 父/母/出生日期三字段齐全）。
   **verified 身份只由身份回填 commit 或人工批准批次 commit 写入；sync 名称归属的
   扁平 `horse_identity_keys` 不产生公开信任。**
2. 滚动批次地区 commit 通过幂等复验后**自动首次发布**（published_by=批次审核人）。
3. 日本先行滚动补全，其他地区后复制。

## 4. 已经完成的工作

### 4.1 身份回填（生产已执行，2026-07-22）

- 生产写入：日本 2,462 netkeiba key（队列覆盖率 0%→21.1%）、香港 327 hkjc key、
  法国 1,773 条 zeturf 证据（4,097 条来源）。artifact：
  `/opt/umanewsbot/runtime/horse_profile_completion/identity-enrichment-20260722/`
- 生产 ExternalHorse 12,405 条 netkeiba 记录父母/出生日期全空 —— 四字段只能靠
  滚动批次从页面抓。

### 4.2 存量发布（生产已执行，2026-07-22）

- provenance 回填：重跑三个已批准回填 manifest 的 commit（幂等），verified keys
  日本 2,462 + 香港 327。
- `publish_p0_horse_profiles` commit：日本 2,459 + 香港 326 = **2,785 匹已公开
  发布**（全库 published 2,797），manifest SHA `fe3002ac…`，OperationLog 逐匹留痕。
  前台 `/horses/` 103 页，未完整马显示「资料补全中」徽章。

### 4.3 netkeiba 客户端（代码已合并 main 并部署）

- `_NetkeibaClient`（`db.netkeiba.com` 马匹页 + 战绩页 + 血统页 3 页直取，
  provider-bound 身份）；`_JapanDispatcherClient`（netkeiba key 候选走 netkeiba、
  其余保持 JBIS）；select 日本候选 netkeiba 偏好；日本每候选预算 3→4。
- 首轮生产 prepare 发现并修复两个缺陷（提交 `3d573583`）：
  - **netkeiba 响应无 charset 实为 EUC-JP**，requests 默认 ISO-8859-1 乱码 →
    `_netkeiba_page_text` 显式解码（61/100 曾因此阻断）。
  - **JBIS 时代陈旧缓存**（候选级缓存不分来源）→ 日本地区缓存命中前校验
    `source.name` 与候选来源一致（39/100 曾因此阻断；美国跨来源互补流不变）。
- 验证：专项 28/28、补全套件 270/270、完整回归与基线一致（14F+70E 零新增）。

### 4.4 代码位置

- 工作树：`/Users/mentianlu/Code/umanews/.worktrees/p0-horse-batch-completion`，
  分支 `claude/p0-horse-batch-completion`（已推送，已全部合并 main）
- main 最新：`3d573583`（含 netkeiba 修复）

## 5. 当前断点（交接时正在做什么）

**正在重跑首个日本滚动批次（netkeiba 路径）**：

1. 旧批次 `p0batch-37fad126d645`（JBIS 同名歧义 100/100）与
   `p0batch-4635b087fbbd`（EUC-JP + 陈旧缓存 100/100）均已 abandon 留证。
2. 新批次 **`p0batch-e5cee174ba05`**（日本 100 匹，全部 netkeiba namespace）：
   select → approve（reviewer mentianlu，SHA `f5404081e5d6d0db…`）→ validate
   已完成，prepare 触网执行中（`--allow-network`）。
3. **断点：prepare 进程在 7/100 后无声死亡**——state.json 无 errors、无 OOM
   （dmesg 无新记录）、7 个 staging 文件已写、主机内存正常（1.6Gi available）。
   怀疑第 8 个候选触发未捕获异常（detached exec 吞掉了 traceback）。
   **交接前正要在前台重跑 prepare 以捕获 traceback（该操作被用户叫停交接）。**

生产运维状态（重要）：

- `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=true`（.env，已改）
- **beat / worker / race_live_worker 处于停止状态**（批次窗口期），web/db/redis/
  nginx 运行中，公网 healthz 200
- 备份：`backups/db/pre-netkeiba-client-20260722T145110Z.sql.gz`（SHA `3bbccf95…`）

## 6. 下一步操作（按顺序）

1. **诊断 prepare 无声死亡**：前台重跑（会断点续跑并在同一候选处复现）：
   ```bash
   ssh root@47.239.167.86 'docker exec umanewsbot-web-1 python manage.py \
     p0_horse_completion_batch --prepare \
     runtime/horse_profile_completion/batches/p0batch-e5cee174ba05/batch_manifest.json \
     --expected-sha256 f5404081e5d6d0db4745e48bef39e1876cb22dbfa15a2f1c4ec9d42876e947d0 \
     --allow-network --json'
   ```
   怀疑方向：`_netkeiba_page_text` 对异常响应形状、缓存守卫对畸形缓存 payload、
   第 8 个候选页面的特殊结构。修复须走「本地复现 → 测试 → 合并 main → 部署」
   全流程，不得在生产直接改代码。
2. prepare 完成后：人工复审 xlsx（`/app/runtime/horse_profile_completion/review/
   p0batch-e5cee174ba05.xlsx`）→ bundle → commit
   `--confirm-reviewed-artifact` → **核验自动首发**（`auto_first_publish` 计数、
   OperationLog、`/horses/?region=japan` 新马与徽章）。这是
   `publish-p0-horses-basic-tier` tasks 7.2 的闭环点。
3. 发布失败恢复：只用 `--retry-publish`（全量重 commit 会被快照漂移 fail closed）。
4. 恢复运维：`ALLOW_NETWORK` 改回 false，重启 web，start beat/worker/
   race_live_worker，healthz 与 `/horses/` 200。
5. 文档与归档：更新 `docs/current_state.md`、`project_status.md`、
   `deploy_runbook.md`、（如有新决策）`decisions.md`；同步主规格；评估归档
   `publish-p0-horses-basic-tier` 与 `add-netkeiba-horse-client`。
6. 后续规模化：日本队列 ~11.6k ÷ 100/批 ≈ 116 批；前 5 批零失败后
   `--limit-per-region` 可提 250（总上限 500 不变）；不跨地区并行。其余地区
   （香港/英国/法国/美国）在日本链路稳定后复制。15,446 组身份冲突的管理员治理、
   美国来源授权（HRN 仅 slug）为后续独立议题。

## 7. 环境与协作注意事项

### 7.1 权限与授权模式

- 本机有权限分类器：SSH 只读需用户授权主机；部署（重建镜像/重启容器）、停
  worker、生产写库各需用户明确授权。**首次调用常报 "stage 2 classifier error
  (transient)"，原样重试一次通常放行**；不要换花样绕过。
- 生产写库门禁：一律 dry-run artifact → 用户审核批准 → commit（manifest SHA
  绑定）。不得把 AI 生成结果伪装成人工已审核，不得猜值。

### 7.2 测试基线

- 该分支完整 `stable` 套件有**基线失败**（14 failures + 70 errors，来自赛事
  历史/实时赛果等其他在途专项）。评估回归必须先做 stash 基线对照，看「新增
  失败数」而非绝对数。
- 测试命令：
  `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test stable --noinput`
  （codex runtime python 无 django，用主工作区 `.venv`）
- 旧规格流程 CLI 必须在对应 worktree 目录下运行。

### 7.3 关键代码入口

| 能力 | 文件 |
| --- | --- |
| netkeiba 客户端 / 日本 dispatcher | `server/stable/services/p0_horse_completion_source_clients.py`（`_NetkeibaClient`、`_JapanDispatcherClient`） |
| 批次流水线 | `server/stable/services/p0_horse_completion_{batch,prepare,commit,research}.py` |
| 发布门禁与存量通道 | `server/stable/services/horse_profile_publish.py` |
| 身份回填 | `server/stable/services/p0_horse_identity_enrichment.py` |
| 缓存守卫 | `server/stable/services/p0_horse_completion_adapters.py`（`run_p0_horse_completion_adapter` 的日本跨源检查） |
| 批次/发布命令 | `server/stable/management/commands/p0_horse_completion_batch.py`、`publish_p0_horse_profiles.py`、`enrich_p0_horse_identities.py` |
| 测试 | `server/stable/test_p0_horse_netkeiba_client.py`、`test_p0_horse_completion_batch.py`、`test_horse_profile_publish.py` |

### 7.4 关键运维知识

- 部署流程：备份 .env + DB（用 .env 的 `POSTGRES_USER=horse_news` +
  `PGPASSWORD`；裸 `pg_dump -U postgres` 会产空 dump）→ `git pull --ff-only
  origin main` → `chmod +x deploy_lowcost.sh deploy/*.sh deploy/docker/*.sh`
  （ff 检出会重置执行位）→ `docker compose -f docker-compose.prod.lowcost.yml
  build web worker beat race_live_worker` → `up -d` → 重启 nginx（web 重建后
  upstream 会短暂 502，属正常，稍候自复）。
- 触网批次前置：备份 → 停 beat/worker/race_live_worker →
  `ALLOW_NETWORK=true` 并重启执行进程；结束后恢复。
- 监视 detached prepare：`docker top umanewsbot-web-1 | grep prepare`（容器内
  无 ps）；状态文件 `runtime/horse_profile_completion/batches/<batch_id>/state.json`。
- **断点续跑语义**：checkpoint 的 `succeeded` 只代表 staging 落盘，被阻断候选
  也记 succeeded → resume 会 `skipped_unchanged`。要重跑被整批阻断的批次，
  正确做法是 abandon + 重新 select（不要手改 state.json）。
- 同 artifact 全量重 commit 会被快照漂移 fail closed（既有设计）；发布失败
  恢复只走 `--retry-publish`。
- netkeiba 限速 8s/请求，每候选预算 4（3 页 + 1 redirect）；JBIS 不做中途回退。
- 生产 artifact 根：`/opt/umanewsbot/runtime/horse_profile_completion/`
  （batches/、identity-enrichment-20260722/、publish-20260722/、review/）。

### 7.5 禁忌

- 不得猜测父母、出生年份、异常赛果、距离单位、Groupe 等等级信息。
- 不得为了普通比赛强行创建 `RaceEvent`；不得用地区或马名做唯一身份。
- 不得绕过 Equibase 防护；不得绕过 netkeiba 限速。
- 不得在 4 GiB 主机跑无地区单事务 P0 sync。
- 不得覆盖主工作区 `/Users/mentianlu/Code/umanews` 或其他 worktree 的未提交改动。
- 前台公开页只读本地数据库，禁止用户访问页面时实时请求第三方。

## 8. 一句话当前状态

存量 2,785 匹马已公开展示，netkeiba 客户端及其两处生产修复已上线；首个日本
滚动批次（`p0batch-e5cee174ba05`）prepare 在 7/100 后无声死亡，下一步在前台
重跑 prepare 捕获 traceback 并修复，随后 bundle → commit 完成首批自动首发闭环。
