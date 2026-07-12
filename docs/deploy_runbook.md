# 部署运行手册

## 2026-07-10 英文术语门禁上下文判定上线

- 本地 change：`classify-english-term-gate-context`。
- 工作树：`/Users/mentianlu/.codex/worktrees/audit-overseas-candidate-pool/umanews`。
- 范围：英文来源文章的术语保留门禁、旧 `core_term_missing` 候选完整重校验命令。
- 行为边界：
  - 普通英文词种子默认按普通词降级为 warning，不生成 `core_term_missing` blocker。
  - 只有 `wins / returns / runs / targets / entered` 等强动作上下文才把普通词种子保守维持为 blocker。
  - `race / jockey / trainer`、真实赛事结构词和未进入普通词种子的 horse term 继续按真实专名或保守缺失处理。
  - `reprocess_term_gate_blocked_articles --commit` 只对完整门禁通过文章调用 `apply_validation_outcome()` 并写 `ranked_revived_at`，不会直接公开发布文章。
- 本地上线前验证：
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true ... manage.py test stable.tests.AutomationFlowTests...`：11 项目标测试通过。
  - `DB_ENGINE=sqlite ... manage.py check`：通过。
  - `openspec validate classify-english-term-gate-context --strict`：通过。
  - `git diff --check`：通过。
- 生产上线后第一步必须只读 dry-run，人工确认前不得执行 `--commit`。若在 `2026-07-10` 执行，`--hours 240` 足以覆盖北京时间 `2026-07-01 00:00` 以来数据；若推迟执行，需要增大 `--hours` 覆盖完整窗口。

```bash
cd /opt/umanewsbot
TS=$(date +%Y%m%d_%H%M%S)
OUT_DIR="runtime/multiregion_candidate_audit/reprocess_full_dryrun_${TS}"
mkdir -p "${OUT_DIR}"

for REGION in hong_kong united_kingdom united_states france; do
  docker compose -f docker-compose.prod.lowcost.yml exec -T web \
    python manage.py reprocess_term_gate_blocked_articles \
      --region "${REGION}" \
      --hours 240 \
      --dry-run \
      --json \
    > "${OUT_DIR}/${REGION}.json"
done
```

- dry-run 审核口径：检查四个 JSON 的 `summary.revalidated_to_publish_ready_count`、`summary.common_word_downgraded_count`、`summary.proper_term_blocker_count`、`outcomes[].english_term_classifications` 和 `outcomes[].proper_term_blockers`；对照本批人工审计投影，重点确认普通词旧 blocker 被清除、真实赛事/马名专名没有被普通词规则误放行。

### 生产执行记录

- 部署前生产 HEAD：`65988b0`。该提交含服务器侧已上线但尚未回主线的移动端马匹导航修复；上线前已在本地把 `production/main` 合并回 `origin/main`，避免部署时覆盖线上修复。
- 部署提交：`43898ff`。
- `.env` 备份：`.env.backup.english-term-context-20260710_030705`。
- 数据库备份：`backups/db/pre-english-term-context-20260710_030705.sql.gz`，已通过 `gzip -t`。
- 部署方式：`git pull --ff-only origin main` 从 `65988b0` 快进到 `43898ff`，随后执行 `bash ./deploy_lowcost.sh`。
- 迁移：无新增迁移，`migrate` 输出 `No migrations to apply`。
- 部署后状态：`web / worker / beat / db / redis / nginx` 正常，`web`、`db`、`redis` healthy，生产 `manage.py check` 通过，本地和公网 `/healthz/` 返回 `{"status": "ok"}`，首页返回 `200`，后台登录入口返回 `200`。
- 完整只读 dry-run 产物：`runtime/multiregion_candidate_audit/reprocess_full_dryrun_20260710_030944/`。
  - 香港：候选 `17`，可恢复候选 `3`，仍阻断 `14`，普通词降级 `9` 次，真实专名 blocker `33` 次。
  - 英国：候选 `37`，可恢复候选 `5`，仍阻断 `32`，普通词降级 `119` 次，真实专名 blocker `140` 次。
  - 美国：候选 `79`，可恢复候选 `22`，仍阻断 `57`，普通词降级 `1` 次，真实专名 blocker `366` 次。
  - 法国：候选 `13`，可恢复候选 `7`，仍阻断 `6`，普通词降级 `13` 次，真实专名 blocker `10` 次。
  - 合计：候选 `146`，可恢复候选 `37`，仍阻断 `109`，普通词降级 `142` 次，真实专名 blocker `549` 次。
- 本次仅执行 `--dry-run`，未执行 `--commit`，未恢复候选，未公开发布文章。后续 commit 前必须先人工抽检 dry-run JSON 中的 `english_term_classifications` 和 `proper_term_blockers`。

## 2026-07-08 马匹详情页 MVP 生产部署

- 本地 change：`horse-profile-page-mvp`。
- 部署提交：`2b28755 Add horse profile page MVP`。
- 工作树：`/Users/mentianlu/.codex/worktrees/race-detail-page/umanews`。
- 新增迁移：`stable.0022_horseprofile_horsefollow_articlehorselink_and_more`。
- 新增公开入口：`/horses/`、`/horses/<id>/`、`/horses/follows/`。
- 新增后台入口：`/admin/horse-profiles/`。
- 新增管理命令：
  - `generate_horse_profiles`：从 active horse `TermEntry` 生成草稿 `HorseProfile`。
  - `complete_horse_profiles`：生成全地区 P0 马资料补全 dry-run artifact，或应用已审核 artifact。
  - `scan_article_horse_links`：历史已发布文章马匹关联 dry-run / commit 回填。

### 生产执行记录

- 生产服务器：`/opt/umanewsbot`。
- 部署前 HEAD：`01c0b9b`。
- 部署后 HEAD：`2b28755`。
- 部署前检查：`docker compose -f docker-compose.prod.lowcost.yml ps` 正常，`manage.py check` 通过，本地 `/healthz/` 与公网 `/healthz/` 返回 `200`，`ExternalDataImportRun(status="started")=0` 且 `ExternalDataImportLock.locked_by_run_id` 为空。
- `.env` 备份：`.env.backup.horse-profile-page-mvp-20260708_040446`。
- 数据库备份：`backups/db/pre-horse-profile-page-mvp-20260708_040503.sql.gz`，约 `85M`，已执行 `gzip -t`。
- 生产 `.env` 已显式补入保守默认：
  - `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false`
  - `HORSE_PROFILE_COMPLETION_REQUEST_INTERVAL_SECONDS=8`
  - `HORSE_PROFILE_COMPLETION_CACHE_DIR=runtime/horse_profile_completion/cache`
  - `HORSE_PROFILE_COMPLETION_BATCH_LIMIT=10`
  - `HORSE_PROFILE_COMPLETION_REQUIRE_SOURCE_URL=true`
  - `HORSE_PROFILE_ACTIVE_RECORD_FRESHNESS_DAYS=1`
- 部署方式：`git pull --ff-only origin main` 从 `01c0b9b` 快进到 `2b28755`，随后执行 `bash ./deploy_lowcost.sh`。
- 迁移：`stable.0022_horseprofile_horsefollow_articlehorselink_and_more` 已应用。
- 部署后状态：`web / worker / beat / db / redis / nginx` 正常，`web` 与 `db / redis` healthy，`manage.py check` 通过。
- P0 草稿生成：`generate_horse_profiles` 创建 `21596` 个 `HorseProfile`，全部为 `draft`，`published=0`。
- 上线 smoke：
  - 本地 `/healthz/`、`/horses/`、`/horses/follows/`、`/admin/login/`、`/news/5738/` 均返回 `200`。
  - 草稿样例 `/horses/1/` 返回 `404`。
  - 未登录 `/admin/horse-profiles/` 返回 `302`。
  - Host `umafans.run` 的 `/horses/` 返回 `200`，公网 `http://umafans.run/healthz/` 与 `http://umafans.run/horses/` 返回 `200`。
- 历史新闻马匹关联 dry-run：`scan_article_horse_links --dry-run --limit 500` 返回 `created=0 updated=0 candidate=0 skipped_removed=0 skipped_manual=0`，原因是当前所有马匹仍为草稿，前台关联面无公开马匹可展示。
- 全地区补全 dry-run：artifact 已复制到宿主机 `runtime/horse_profile_completion/dry-run-20260708_041343/`，包含 `horse_profile_completion_plan.json`、`horse_profile_completion_review.csv` 和 `summary.json`。
  - 覆盖 P0 马 `21596` 匹。
  - `complete_pedigree_2gen=0`，`not_complete=21596`，`complete_ratio=0.0`，`not_complete_ratio=1.0`。
  - 失败原因：`no_external_match=15293`、`source_unavailable=6301`、`profile_only=2`。
  - 按地区 `france / hong_kong / japan / other / united_kingdom / united_states` 的 `not_complete_ratio` 均为 `1.0`。
  - 本次未执行 `--commit`；后续必须先人工审核 `horse_profile_completion_review.csv`，再使用 `--artifact --confirm-reviewed-artifact` 应用。

### 线上浏览器验收记录

- 时间：`2026-07-08`。
- 方式：先尝试 Codex 内置浏览器访问生产页，两次打开 `http://umafans.run/horses/` 超时；随后使用系统 Chrome headless 生成桌面 / 移动截图和 CDP 布局指标。
- 本地验收产物：`/tmp/umanews-horse-acceptance/`。
  - `horses-desktop.png`
  - `horses-mobile.png`
  - `home-desktop.png`
  - `home-mobile.png`
  - `follows-desktop.png`
  - `follows-mobile.png`
  - `horses.html`
  - `horses-search-region.html`
  - `home.html`
  - `news-5738.html`
- 公网 HTTP 复核：
  - `http://umafans.run/healthz/` 返回 `200`。
  - `http://umafans.run/horses/` 返回 `200`。
  - `http://umafans.run/horses/follows/` 返回 `200`。
  - `http://umafans.run/horses/1/` 返回 `404`，符合草稿不公开策略。
  - `http://umafans.run/admin/horse-profiles/` 返回 `302` 到 `/admin/login/?next=/admin/horse-profiles/`。
- Chrome 布局复核：
  - 桌面 `/horses/` 标题为“马匹资料”，包含搜索框、地区筛选和空状态；页面 `clientWidth=1440`、`scrollWidth=1440`，无页面级横向溢出。
  - 移动 `/horses/` 标题为“马匹资料”，导航 DOM 包含“首页 / 赛事日历 / 马匹 / 我的关注”，搜索框存在；页面 `clientWidth=390`、`scrollWidth=390`，无页面级横向溢出。
  - 移动首页导航 DOM 包含“马匹”和“我的关注”，页面 `clientWidth=390`、`scrollWidth=390`。
  - 移动 `/horses/1/` 显示 404 页，页面 `clientWidth=390`、`scrollWidth=390`。
  - `/horses/?q=test&region=japan` 保留搜索词 `test`，并正确激活“日本”地区筛选。
- 当前体验问题：
  - `/horses/` 空状态文案为“目前还没有已发布文章。”，语义应改为马匹资料。
  - 移动端顶部导航和地区筛选依赖横向滑动，功能可用但“马匹 / 我的关注”和最右侧“美国”入口不够显眼。
- 未覆盖项：
  - 生产当前没有已发布马匹，未在生产发布测试数据；因此未完整验收已发布马匹详情、关注按钮 POST、新闻详情马匹 tag 和关注新闻流。
  - 未持有 staff 登录态，后台审核列表 / 详情只验收到未登录跳转。
  - UmaNews 生产 SSH 只以 `root@47.239.167.86` 为准；其他项目服务器不属于本项目验收范围。

### 样本发布与最终前台验收记录

- 时间：`2026-07-10`。
- 服务器：`root@47.239.167.86:/opt/umanewsbot`，最终 `HEAD=65988b0`。
- 代码部署：
  - `34143ce`：修复 `/horses/` 空状态文案，并调整移动导航 / 地区筛选初版布局。
  - `d21d6ab`：继续收敛移动端导航和地区筛选裁切问题。
  - `65988b0`：移动一级导航改为两列 grid，确保“首页 / 赛事日历 / 马匹 / 我的关注”全部在屏内。
- 备份：
  - `.env.backup.horse-public-polish-20260710_010639`
  - `backups/db/pre-horse-public-polish-20260710_010639.sql.gz`
  - `backups/db/pre-horse-sample-profiles-20260710_011038.sql.gz`
  - `.env.backup.horse-mobile-polish-20260710_011811`
  - `backups/db/pre-horse-mobile-polish-20260710_011811.sql.gz`
  - 上述数据库备份均已执行 `gzip -t`。
- 样本数据：
  - `春秋分`：`/horses/13113/`，netkeiba 来源 `https://db.netkeiba.com/horse/2019105219/`，参赛履历 `10` 条，相关新闻人工关联 `5` 篇。
  - `北十字星`：`/horses/3873/`，netkeiba 来源 `https://db.netkeiba.com/horse/2022105102/`，参赛履历 `11` 条，相关新闻人工关联 `5` 篇。
  - 两匹马均为 `review_status=published`、`completeness_status=complete_pedigree_2gen`。
- 前台验收：
  - `http://umafans.run/horses/13113/` 显示春秋分基础资料、完整二代血统、主胜鞍、参赛履历和相关新闻。
  - `http://umafans.run/horses/3873/` 显示北十字星基础资料、完整二代血统、主胜鞍、参赛履历和相关新闻。
  - `http://umafans.run/news/7248/` 显示马匹 tag `春秋分`，点击进入 `/horses/13113/`。
  - 匿名关注 / 取消关注链路通过；关注后 `/horses/follows/` 显示春秋分及其关联新闻，验收后已取消关注，样本 `HorseFollow` 计数为 `0`。
  - `/horses/?q=croix&region=japan` 可命中北十字星，`/horses/?q=EQUINOX&region=japan` 可命中春秋分，英文大小写搜索正常。
  - Codex 浏览器移动 viewport `390x844` 复核 `scrollWidth=390`，四个一级导航入口和六个地区按钮坐标均在屏内。
- 生产健康：
  - `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check` 通过。
  - 本地容器和公网 `http://umafans.run/healthz/` 均返回 `200` / `{"status": "ok"}`。

### 生产部署前检查

1. 记录生产 `HEAD`：`git rev-parse --short HEAD`。
2. 检查容器：`docker compose -f docker-compose.prod.lowcost.yml ps`。
3. 执行 Django check：`docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check`。
4. 检查本地和公网健康：`curl -fsS http://127.0.0.1/healthz/`、`curl -fsS http://umafans.run/healthz/`。
5. 确认外部导入没有运行：`ExternalDataImportRun(status="started")=0`，`ExternalDataImportLock.locked_by_run_id` 为空。
6. 备份数据库并执行 `gzip -t`。
7. 备份 `.env`，确认新增配置默认保守：
   - `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=false`
   - `HORSE_PROFILE_COMPLETION_REQUEST_INTERVAL_SECONDS=8`
   - `HORSE_PROFILE_COMPLETION_CACHE_DIR=runtime/horse_profile_completion/cache`
   - `HORSE_PROFILE_COMPLETION_BATCH_LIMIT=10`
   - `HORSE_PROFILE_COMPLETION_REQUIRE_SOURCE_URL=true`
   - `HORSE_PROFILE_ACTIVE_RECORD_FRESHNESS_DAYS=1`

### 部署与迁移

P0 马资料补全专项上线前额外确认：

- `stable.0027_p0_horse_profile_completion` 会为自然键唯一的既有 `HorseRaceRecord` 回填幂等键；已有重复组保持空键，需先在 dry-run 报告中人工处理。
- 已审核 artifact 必须同时具备顶层 `reviewed`、行级 `reviewed=true`、有效 `reviewer_id`，以及 `profile/pedigree/race_record/major_wins` 四模块 `approved`；缺少来源 URL、低置信、未审核或冲突模块不得写主表。
- `p0_horse_profiles --sync-sources --commit` 只新增、刷新或恢复来源，不撤销历史来源；可配合 `--region` 做单地区同步。
- `p0_horse_profiles --sync-sources --commit --full-reconcile` 才是全地区完整来源对账，会把本轮不再成立的受管来源标记为 `revoked`；只应在重点赛事/出赛表/赛果导入完成且本地结构化数据为完整快照时执行，不能与 `--region` 同时使用。
- 队列排查可用 `--queue --profile-id <id>` 精确选择一匹或重复指定多匹；`--limit-per-region` 必须大于 0。
- 马匹自身 `racing_region` 不因海外参赛而修改；抽检跨地区样本时同时核对 `HorseProfile.racing_region` 和 `HorseP0Source.racing_region`。
- 抽检同场同名马时必须核对 `HorseP0Source.participant_key`：不同马号应为不同 `number:<horse_number>`，每个参赛键最多一条 active 来源；身份纠正应留下 revoked 旧行和 active 新行。
- 参赛记录后补马号时，普通增量同步后应确认旧 identity 键已迁移为 number 键且仍只有一条 active 来源；runner/result 两边马号冲突时应只产生 pending `HorseIdentityConflict`，不得生成 active P0 来源。
- 抽检同来源 identity 的同类型重复输入：两条 runner 或两条 result 使用不同马号时，应汇总为一条 pending 身份冲突，证据包含全部记录 ID 和马号，active P0 来源计数为 0。
- 解决马号冲突时必须同时填写 `resolved_profile` 和 evidence 候选内的 `resolved_horse_number`；下一次同步只允许选中马号产生 active 来源。抽检冲突成员 URL 完整保留，完全无 URL 的冲突仍在 pending 列表中。
- 跨来源自动归并数据库已有马时，必须完整且唯一命中经术语库归一的马名、父名、母名和出生年份；来源 ID 只能在自身命名空间内作为直接证据。
- 身份不确定时应生成 `HorseIdentityConflict(status=pending)`，即使尚无 `HorseProfile` 也必须关联候选术语和原始证据，不得写入马匹主表；全量对账不得撤销仍在输入中的待处理来源或仅临时缺少 URL 的来源。
- Celery Beat 每天 `09:20` 运行 `stable.tasks.notify_p0_horse_identity_conflicts_task`，复用 `MULTIREGION_OPS_NOTIFICATIONS_*` 通知配置。部署后应抽查任务日志、pending 冲突数和 `${DJANGO_ADMIN_URL}stable/horseidentityconflict/?status__exact=pending`。
- Django Admin 处理身份冲突时应填写 `resolved_profile` 与 `resolution_notes`，并将状态改为 `resolved` 或 `ignored`；系统自动记录 `resolved_by/resolved_at`。
- 人工执行完整资料 ready 前必须设置明确的 `HorseProfile.source_refs.p0_completion` 整匹马资料 URL；不能仅以单场赛果 URL 作为基础资料和血统来源。
- P0 artifact 和后台人工候选写入赛绩后，抽检 `HorseRaceRecord.idempotency_key` 非空；同一赛绩重复审核不得增加记录数，缺少 `source_name` 或 `source_url` 的候选必须保持 pending/冲突且不落主表。
- 后台手工新增/编辑赛绩也应抽检幂等键：重复提交不增加记录数，修改比赛名/日期/来源后键随之更新，若命中另一既有记录则页面提示冲突并保留原记录。
- 编辑 importer 生成的赛绩后，必须确认原 `source_refs/raw_payload` 未变化，操作日志包含字段 before/after；后台“在役待刷新”筛选应与 `HORSE_PROFILE_ACTIVE_RECORD_FRESHNESS_DAYS` 一致。
- 对含 external result/race ID 的赛绩执行人工改名后重跑相同 importer，确认幂等键仍为 external-ID 语义且记录数不增加。

```bash
git pull --ff-only origin main
bash ./deploy_lowcost.sh
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py showmigrations stable | grep 0027
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check
```

期望：`stable.0027_p0_horse_profile_completion` 已应用，`manage.py check` 通过。

### P0 草稿生成

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py generate_horse_profiles
```

验收：

- 新增 `HorseProfile` 均为 `review_status=draft`。
- 公开 `/horses/` 不展示草稿。
- 任意草稿 `/horses/<id>/` 返回 404。

### 全地区资料补全 dry-run

先只生成 artifact，不写主表：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py complete_horse_profiles \
  --dry-run \
  --output-dir runtime/horse_profile_completion/dry-run-YYYYMMDD_HHMMSS
```

不传 `--limit` 时必须覆盖所有地区全部 P0 马；`--limit` 仅用于显式采样或拆批演练，不能用于最终全量验收。

必须复核输出：

- `horse_profile_completion_plan.json`
- `horse_profile_completion_review.csv`
- `summary.json`
- 全局和按地区完整二代成功率。
- 未补全占比和逐马失败原因。
- source URL、候选 diff、歧义和不可用来源原因。

人工审核 artifact 后，才允许 commit：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py complete_horse_profiles \
  --commit \
  --artifact runtime/horse_profile_completion/dry-run-YYYYMMDD_HHMMSS/horse_profile_completion_plan.json \
  --confirm-reviewed-artifact
```

### 历史新闻马匹关联回填

先 dry-run：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py scan_article_horse_links \
  --dry-run \
  --limit 500
```

确认候选和人工移除保护后再 commit：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py scan_article_horse_links \
  --commit \
  --limit 500
```

可按范围拆批：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py scan_article_horse_links \
  --commit \
  --article-from-id <START_ID> \
  --article-to-id <END_ID> \
  --limit 500
```

### 上线 smoke

- `/healthz/`：本地和公网均 `200`。
- 首页 `/`：返回 `200`，有关注 cookie 时展示“我的关注”模块。
- `/horses/`：返回 `200`，只展示已发布马匹。
- 样例 `/horses/<published_id>/`：返回 `200`，展示基础资料、二代血统、主胜鞍、相关新闻、相关赛事和关注按钮。
- 样例 `/horses/<draft_id>/`：返回 `404`。
- `/admin/horse-profiles/`：未登录跳转登录；staff 登录后可访问列表和详情。
- 新闻详情 `/news/<article_id>/`：只展示已发布且 `auto/manual` 状态的马匹 tag；候选、移除和未公开马匹不展示。
- 关注 POST 后 cookie 应为 `HttpOnly`、`SameSite=Lax`，数据库只出现 `token_hash`。

### 回滚

- 代码异常：回滚到部署前 git ref 后执行 `bash ./deploy_lowcost.sh`。
- 迁移异常：优先使用数据库备份恢复；如必须迁回，先确认没有新写入 `HorseProfile` / `HorseFollow` / `ArticleHorseLink` 数据。
- 补全误写：优先按 artifact 的 diff 和 `HorseProfileDataCandidate` 审计恢复字段；大范围异常使用部署前数据库备份。
- 公开入口异常：先将受影响 `HorseProfile.review_status` 批量改回 `hidden` 或 `draft`，再修代码。
## 2026-07-10 RaceEvent 赛事信息编排工具运行边界

本工具对应 OpenSpec change `orchestrate-race-event-data-crawls`，第一版只服务 `RaceEvent*` 产品层赛事详情回填，不写 `ExternalRace*` / `ExternalHorse*`，不创建新闻文章，不触发翻译、自动发布或 QQ 推送。长期历史抓取必须手动分批或一次性容器执行，不加入 Celery Beat。

本地/生产通用阶段：

1. 校验并创建运行目录：
   - `python server/manage.py orchestrate_race_event_crawl --plan <plan.json> --stage plan`
   - 该阶段会在任何网络请求前生成不可随抓取结果缩减的 `<run_dir>/expected_targets.json`，并生成 `<run_dir>/review/expected_targets_review.csv`。快照绑定 plan SHA-256；清单为空、目标重复、正式 `RaceEvent` 缺失或恢复时 plan 已变化都会停止后续真实抓取。
   - 第一批真实抓取前必须人工查看 review CSV，逐行确认赛事中英文名、年份、地区、slug 和 `preflight_status=ready`。发现缺漏或错配时修改 plan / `RaceEvent` 后创建新 run，不得用实际抓到的候选反推或缩减应到范围。
2. 准备候选来源与 adapter 产物：
   - `python server/manage.py orchestrate_race_event_crawl --plan <plan.json> --stage prepare`
   - plan 未设置 `allow_network=true` 时，声明需要网络的 adapter 会被阻止。
   - `batch_size` 会限制单地区目标赛事年份数量；`rate_limit.max_requests` 与 `request_interval_seconds` 会由该 run 的全部网络 adapter 共同执行。累计状态保存在 `<run_dir>/request_budget.json`，失败请求也计数；artifact 损坏时停止请求，不重置额度。
   - 全部 adapter 成功后会生成 `<run_dir>/candidates/combined_candidates.jsonl`，同时保留每个 adapter 的原始、review 和归一化产物。
3. 覆盖审计：
   - `python server/manage.py orchestrate_race_event_crawl --plan <plan.json> --stage audit --series-mapping <series_mapping.json> --run-dir <run_dir>`
   - 未显式传 `--candidate-jsonl` 时默认审计 run state 中的 combined candidate；只有调试单独文件时才覆盖该参数。
   - blocker 包括 `missing_event_candidate`、`unexpected_candidate`、`missing_race_event`、缺模块、未审核 mapping、重复候选、source URL 一对多、manual lock、候选更不完整等。即使实际候选为零，也必须按独立应到清单逐项报缺，不能空跑通过。
4. Django dry-run：
   - `python server/manage.py orchestrate_race_event_crawl --plan <plan.json> --stage dry-run --run-dir <run_dir>`
   - 未显式传 `--candidate-jsonl` 时同样默认使用 combined candidate。
   - dry-run 仍会按 `year + slug` 查询 `RaceEvent`，因此深历史目标行缺失时必须先处理 seed review artifact。
   - 成功后固定生成结构化 `<run_dir>/dry_run.json`，其中 `status=passed`，并记录候选 JSONL 的绝对路径、大小和 SHA-256；`dry_run.txt` 只保留 importer 原始输出，不可单独作为 apply 证据。
5. apply-check：
   - `python server/manage.py orchestrate_race_event_crawl --plan <plan.json> --stage apply-check --coverage-audit <coverage_audit.json> --dry-run-artifact <run_dir>/dry_run.json --confirmations <confirmations.json> --production-evidence <production_evidence.json> --apply-scope <apply_scope.json> --candidate-jsonl <candidates.jsonl> --run-dir <run_dir>`
   - 只生成显式 apply 命令，不自动执行正式写入。
   - `coverage_audit.json`、`dry_run.json` 和待 apply JSONL 的 SHA-256 必须完全一致；候选在审计后有任何修改，都必须重新执行 audit 和 dry-run。旧审计产物缺少候选身份时会被阻止，不能通过显式传入另一份 `--candidate-jsonl` 绕过。
   - coverage 发现同一赛事不同模块使用不同来源或 source authority 时，会输出 `mixed_source_strategies[].strategy_sha256`；对应人工确认必须在 `mixed_source_strategy_sha256s` 中逐项列出这些哈希。
   - coverage 会输出 `actual_apply_scopes`。单一组合可继续使用顶层 `region/source/modules`；多组合必须在 `apply_scope.json` 中使用 `{"scopes": [...]}`，且每个实际组合都要有对应 confirmation。范围不完全一致时返回 `apply_scope_mismatch`，不会生成命令。
   - 全绿后生成 `<run_dir>/approved/candidates-<sha256>.jsonl`。显式命令只引用该绝对路径，并带 `--expected-sha256 <sha256>`；不得去掉哈希参数或改回普通 combined candidate 路径。
6. 中断恢复：
   - `python server/manage.py orchestrate_race_event_crawl --stage resume --state <run_dir>/state.json`
   - state 会记录每个 adapter 的输入指纹、必需输出路径/大小/SHA-256、成功/失败结果和恢复历史；只有输入未变化且全部必需输出仍存在、哈希一致时才会跳过。输出缺失、变化或旧 state 没有输出哈希时会重新执行 adapter。
   - audit 被 blocker 阻止后，可修正候选 JSONL 或 series mapping，再执行同一 resume 命令重跑 coverage audit；dry-run 和 apply-check 的成功/失败也会写入同一 state，resume 会使用保存的阶段输入依次重跑必要门禁。

生产 apply 前必须具备：

- coverage audit 无 blocker。
- `import_race_event_detail_candidates --dry-run` 证据通过。
- 首批“地区 + 来源 + 模块组合”人工确认记录。
- 候选记录均有合法 `source_authority`；adapter 候选中的 `adapter_key`、`source_provider`、地区、模块和权威等级与 manifest 一致；混合来源策略已按 coverage 输出的策略哈希人工确认。
- `actual_apply_scopes` 中每个“地区 + 来源 + 模块组合”均被 apply scope 和 confirmation 覆盖。
- approved candidate 文件存在，最终 importer 命令携带匹配的 `--expected-sha256`；执行时哈希不一致必须零写入失败。
- `ExternalDataImportRun(status="started")=0` 且 `ExternalDataImportLock.locked_by_run_id` 非空并指向 started run 的计数为 `0`；持久化但 `locked_by_run_id=None` 的空闲锁行不算活跃锁。
- `/healthz/` 本地与 Host 健康。
- 数据库备份路径和 `gzip -t` 结果。
- 数据库备份路径必须指向实际可读取的备份文件；仅填写字符串或伪造 `gzip` 状态无法通过 apply-check。
- 已有正式数据 diff/review 必须显式记录 `status=approved`，特别是会按模块整体替换的 `runners/results/history_winners`。

第一验收 fixture 位于 `server/stable/fixtures/race_event_crawl/first_acceptance_plan.json`，必须覆盖日本、香港、英国、法国、美国五地区少数核心赛事系列，并同时包含 `runners`、`results`、`history_winners` 三模块。来源权威等级矩阵位于 `server/stable/fixtures/race_event_crawl/source_authority_matrix.json`。

用户在第一批真实抓取前只需协助一次应到清单审核：Codex 提供实际 CSV 路径后，确认每行赛事中英文名、年份、地区和 slug 正确，并指出缺少或多出的赛事。请求上限、间隔、adapter 选择、候选哈希、coverage 和 apply 证据等技术项由工程侧负责；若用户未确认清单，第一批真实网络抓取不应开始。

## 2026-07-10 英法赛事详情生产复核与 Grand Prix de Saint-Cloud 历史冠军修复

- 生产服务器：`/opt/umanewsbot`。
- 生产预检：
  - `HEAD=65988b0`。
  - `web / db / redis` healthy，`worker / beat / nginx` 运行。
  - `python manage.py check` 通过。
  - `http://127.0.0.1/healthz/` 与 Host `umafans.run` `/healthz/` 均返回 `{"status": "ok"}`。
  - `ExternalDataImportRun(status="started")=0`，HKJC / netkeiba 导入锁为空。
- 复核结论：
  - 生产英法赛事详情已经正式导入，不需要重复 apply 整批规范 JSONL。
  - 英国：`sporting_life` runners/results applied `116 + 116`，`sporting_life_gap` runners/results applied `6 + 6`；`Jane Seymour Nov. Hurdle` 在线状态为 `cancelled`。
  - 法国：`zeturf` runners/results 已 applied；`GRAND PRIX DE SAINT-CLOUD` 当前正式出走表 / 赛果均来自正确 `R1C5` 页面，冠军为 `CALANDAGAN`。
  - 发现遗留污染：该赛事 `RaceEventHistoryWinner` 中 `2026` 年冠军仍来自早先误配 `R1C4` 的 `ZELMAN`。
- 修复流程：
  - 生成单场 JSONL：`grand_prix_saint_cloud_history_repair_20260710.jsonl`，只包含 `fr-france-galop-2026-0705-044` 的 `history_winners` 7 条。
  - 生产 dry-run：`events=1 modules=1 items={"history_winners": 7}`。
  - 写入前备份：`backups/db/pre-race-detail-gpsc-history-repair-20260710_025949.sql.gz`，约 `96M`，`gzip -t` 通过。
  - 正式 apply：`events=1 candidates=1 applied=1 items={"history_winners": 7}`，新增 applied candidate `2914`。
- 验收：
  - `RaceEventRunner=5096`、`RaceEventResult=4572`、`RaceEventHistoryWinner=5731`、`RaceEventDataCandidate=2914`。
  - `RaceEventDataCandidate(status="pending")=0`、`failed=2`。
  - `GRAND PRIX DE SAINT-CLOUD` 历史冠军 `2026` 已为 `CALANDAGAN`，source 指向 ZEturf `R1C5`。
  - 公网 `/races/2026/fr-france-galop-2026-0705-044/` 返回页面包含 `CALANDAGAN`，未再显示 `ZELMAN`。
  - 本地和 Host `/healthz/` 均返回 `{"status": "ok"}`。

## 2026-07-07 法国新闻源扩展与英文术语门禁地区过滤上线

- 本地 changes：`expand-france-news-sources`、`fix-english-term-gate-region-filter`。
- 部署提交：`bfc3445 Prepare France source expansion and English term gate fix`。
- 生产服务器：`/opt/umanewsbot`。
- 部署前状态：生产 `HEAD=538011e`，外部导入运行数 `0`、导入锁 `0`。
- 部署前备份：
  - 数据库：`backups/db/pre-france-source-term-gate-20260707_200124.sql.gz`，已执行 `gzip -t`。
  - `.env`：补法国来源发布白名单前分别备份为 `.env.backup.france-tdn-access-<timestamp>` 与 `.env.backup.france-tdn-canonical-access-<timestamp>`。
- 部署方式：
  - 生产机访问 GitHub HTTPS 超时，未能直接 `git fetch origin main`。
  - 本地生成 `/tmp/umanews-bfc3445.bundle` 并 `scp` 到生产机。
  - 生产机执行 `git fetch /tmp/umanews-bfc3445.bundle HEAD:refs/remotes/origin/main`、`git merge --ff-only refs/remotes/origin/main`，从 `538011e` 快进到 `bfc3445`。
  - 执行 `bash ./deploy_lowcost.sh`，镜像重建成功，迁移显示 `No migrations to apply`，`web / worker / beat` 已重建。
- 基础验证：
  - `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check`：通过。
  - `http://127.0.0.1/healthz/`、Host `umafans.run` `/healthz/` 和公网 `http://umafans.run/healthz/`：均返回 `{"status": "ok"}`。
- 法国新来源验证：
  - 已执行 `sync_builtin_sources()`，生产内置来源数 `21`。
  - `tdn_france_broad` 只读探测 accepted：HTTP `200`、列表 `20`、详情样本 `5`、详情错误 `0`、重复 `0`。
  - 已启用 `NewsSource#21 TDN 法国宽关键词英文新闻`：`enabled=true`、`production_approved=true`、`effective_crawl_interval_minutes=15`。
  - 生产 `.env` 中 `MULTIREGION_AUTO_PUBLISH_ALLOWED_SOURCES` 已加入 `tdn_france:access` 与 canonical 入库后的 `tdn:access`；`NEWS_SOURCE_POLL_ALLOWED_SOURCES=` 为空，表示抓取不额外限源。
  - 手动真实抓取验证入库 `4` 篇法国新来源文章，article IDs 为 `7250-7253`。为补生产配置而重启时中断了该人工抓取，`CrawlJob#9330` 已标记为 `failed`，`success_count=4`，错误说明为部署配置重启中断；这不是来源访问失败。
  - 文章 `7250-7253` 已完成补翻译和自动化重评，当前均为 `manual_review_required / pending_review`；`7250-7252` 因真实 `core_term_missing` blocker 转人工，`7253` 因总分 `69` 转人工。
- 英文门禁验证：
  - `reprocess_term_gate_blocked_articles --dry-run --json`：
    - `hong_kong`：最近 3 小时无可释放候选。
    - `united_states`：最近 3 小时无可释放候选。
    - `france`：最近 3 小时无可释放候选。
    - `united_kingdom`：有 `1` 篇候选，但重校验后仍被真实核心术语缺失阻断。
  - 本次未执行 `--commit`，因为没有因地区过滤修复可释放的近期误挡文章。
- 最终审计：
  - 容器内审计文件：`runtime/multiregion_audit/post-france-source-term-gate-final-20260707_202851.json`。
  - 法国来源：总数 `4`、启用 `3`、生产批准 `3`、paused/backoff 均为 `0`。
  - 法国文章：今日新入库 `4`、最近 24 小时 `4`、公开 `0`；workflow 为 `pending_review=29`，automation 为 `manual_review_required=29`，当前公开 0 的原因是正常门禁转人工，不是抓取或白名单失败。

### 21:00 线上回归复核

- 生产仓库：`HEAD=dcb9b90`。
- 容器：`web / worker / beat / db / redis / nginx` 均运行，`web` 与 `db / redis` healthy。
- 健康检查：`manage.py check` 通过；`http://127.0.0.1/healthz/`、`http://umafans.run/healthz/`、首页和 `/admin/login/` 均返回 `200`。
- 配置：`MULTIREGION_PRODUCTION_WINDOWS_ENABLED`、抓取 / 发布 / QQ 子开关和 `NEWS_SOURCE_POLL_ENABLED` 均为 `true`；`MULTIREGION_AUTO_PUBLISH_ALLOWED_SOURCES` 已包含 `tdn_france:access` 与 `tdn:access`。
- `tdn_france_broad` 只读探测：accepted，HTTP `200`、列表 `20`、详情样本 `2`、详情错误 `0`；重复率 `0.5`，原因是自然窗口已入库同批文章。
- 自然抓取窗口：`CrawlJob#9355` 已由生产窗口派发并仍在运行中，已通过 `source_config=21` 入库 `10` 篇法国文章，其中 `9` 篇已翻译、`1` 篇翻译中。Celery active 显示该 task 正在 worker 内运行，worker 日志持续出现 SiliconFlow `200 OK`，判断为单轮处理耗时偏长但仍在推进。
- 最近 90 分钟窗口：五地区发布和 QQ 窗口均为 `succeeded`；0 发布 / 0 推送原因均有记录，主要为 `no_ready_candidates`、`no_eligible_articles` 或 `already_sent`。
- 英文门禁重处理 dry-run：香港、美国无可释放候选；英国 `7242` 仍为真实 blocker；法国 `7250/7251/7252` 仍为真实 blocker。本次回归未执行 `--commit`。

### TDN broad 历史旧文事故与临时止血

- 发现问题：`tdn_france_broad` 抓入 2020、2022、2023、2024 年历史旧文，并因 `published_at` 被错误写为当前时间进入自动发布流程。
- 根因：TDN WordPress `search` API 返回相关性搜索结果，search item 不带 `date/date_gmt`；当前 adapter 在缺失日期时兜底为 `timezone.now()`，详情页解析也没有拿到真实发布时间。
- 已执行止血：生产 `NewsSource#21` 已设置 `enabled=false`、`production_approved=false`，并写入 `manual_pause_reason`，保留其他法国来源继续运行。
- 已确认受影响的已公开旧文：
  - `7255`：真实日期 `2022-03-21`。
  - `7263`：真实日期 `2020-04-07`。
  - `7264`：真实日期 `2020-03-16`。
  - `7265`：真实日期 `2020-03-13`。
  - `7271`：真实日期 `2024-11-08`。
- 修复方向：`tdn_france_broad` 必须用 search item 的 `id` 或 `_links.self` 二次读取 post API 获取真实 `date_gmt`，并丢弃超过生产新鲜度窗口的文章；修复和回归前不得重新启用 `NewsSource#21`。

### TDN broad 历史旧文修复上线

- 本地 change：`fix-tdn-france-search-date-freshness`。
- 部署提交：`ad587ce Fix TDN France search result freshness`。
- 生产服务器：`/opt/umanewsbot`。
- 部署前状态：
  - 生产 `HEAD=96fde81`。
  - `web / worker / beat / db / redis / nginx` 运行正常，`web` healthy。
  - `manage.py check` 通过，本地与公网 `/healthz/` 均返回 `{"status": "ok"}`。
  - `ExternalDataImportRun(status=started)=0`，外部导入锁 `0`。
- 部署前备份：
  - 数据库：`backups/db/pre-tdn-france-freshness-20260707_223913.sql.gz`，已执行 `gzip -t`。
- 部署方式：
  - 本地生成 `/tmp/umanews-ad587ce.bundle` 并 `scp` 到生产机。
  - 生产机执行 `git fetch /tmp/umanews-ad587ce.bundle HEAD:refs/remotes/origin/main`、`git merge --ff-only refs/remotes/origin/main`，从 `96fde81` 快进到 `ad587ce`。
  - 执行 `bash ./deploy_lowcost.sh`，镜像重建成功，迁移显示 `No migrations to apply`，`web / worker / beat` 已重建。
- 修复内容：
  - `TDNFranceKeywordAdapter` / `TDNFranceBroadKeywordAdapter` 对 search item 缺失日期时，使用 `id` 或 `_links.self` 二次读取 post API 的真实 `date_gmt/date`。
  - 缺失真实日期的 search item 跳过，不再兜底为当前时间。
  - 法国 TDN search 来源只接受真实发布时间在 3 天新鲜度窗口内的文章，历史旧文写入跳过摘要。
  - 国际来源抓取任务会把 listing 阶段跳过写入 `CrawlJob` / `NewsSource.last_crawl_message`；纯旧文过滤不标记为来源失败。
- 生产清理：
  - 已将误发布旧文 `7255/7263/7264/7265/7271` 标记为 `workflow_status=withdrawn`、`automation_status=manual_review_required`，清空 `published_to_web_at`，写入 `withdrawn_at`、`decision_reason.tdn_france_stale_cleanup` 与 `editor_notes`。
  - 公网 `/news/7255/`、`/news/7263/`、`/news/7264/`、`/news/7265/`、`/news/7271/` 均返回 `404`。
- 重新启用：
  - `NewsSource#21 TDN 法国宽关键词英文新闻` 已恢复 `enabled=true`、`production_approved=true`，并清空 `manual_pause_reason`。
- 上线后验证：
  - 生产 `HEAD=ad587ce`，`manage.py check` 通过，容器正常，本地与公网 `/healthz/` 均返回 `{"status": "ok"}`。
  - 只读探测 `probe_international_news_sources --source tdn_france_broad --json` 返回 HTTP `200`，但当前 `status=deferred`、`deferred_reason=empty_sample`、`list_count=0`，原因是搜索结果经新鲜度过滤后没有可采样的新鲜文章。
  - 手动真实抓取 `CrawlJob#9445` 成功：`new_count=0`、`seen_count=0`、`skipped_count=80`，首条跳过原因包含 `stale_published_at`，`NEW_ARTICLES=[]`。
  - 结论：来源已重新打开，旧文不再入库；当前没有新稿是 TDN 搜索结果全部被新鲜度过滤后的正常结果。

## 2026-07-07 HKJC 日语 alias 合并与已发布文章术语回填工具

- 本地 change：`hkjc-ja-alias-article-backfill`。
- 新增服务层：`server/stable/services/term_maintenance.py`。
- 新增管理命令：
  - `merge_hkjc_ja_aliases`：生成/应用 HKJC horse 日语 alias 概念合并计划。
  - `backfill_article_terms`：生成/应用已发布文章字段级术语回填 diff。
- 数据库迁移：无。
- artifact 默认目录：`runtime/term_backfills/<operation>-<timestamp>/`。

### 生产执行记录

- 生产服务器：`/opt/umanewsbot`。
- 部署提交：先从 `b1ddb54` 快进到 `4bffbe6`，随后因文章回填 dry-run 性能问题补丁再次快进到 `a65c1ed` 并重建 `web / worker / beat`。
- 部署前备份：
  - `.env.backup.hkjc-ja-alias-backfill-20260707_184118`
  - `backups/db/pre-hkjc-ja-alias-backfill-20260707_184118.sql.gz`，已执行 `gzip -t`。
- 生产部署：
  - `git merge --ff-only origin/main` 后执行 `bash ./deploy_lowcost.sh`。
  - 无新增迁移，`web` healthy，`worker / beat / db / redis / nginx` 正常。
  - 生产保留既有 tracked 热补丁 `server/stable/templates/stable/public/race_detail.html` 中取消/延期状态展示；本次镜像重建前已恢复该热补丁，避免回退线上现有赛事详情表现。
- 验证：
  - `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check`：通过。
  - `http://127.0.0.1/healthz/`：`200`。
  - `http://umafans.run/healthz/`：`200`。
  - 生产 HEAD：`a65c1ed`。
- HKJC alias 合并：
  - 首次 dry-run：`runtime/term_backfills/hkjc-ja-alias-merge-20260707_185042/`，容器内 artifact；summary 为 `candidate=112 skipped=0 scanned=112`，全部 `same_target_primary_owner`。
  - 正式 apply：`runtime/term_backfills/hkjc-ja-alias-merge-apply-20260707_185254/`，容器内 artifact；summary 为 `applied=112 skipped=0 unchanged=0`。
  - 重建后 post-apply smoke 已复制到宿主机：`runtime/term_backfills/hkjc-ja-alias-merge-postapply-smoke-20260707_192810/`，summary 为 `candidate=0 skipped=0 scanned=0`。
  - 数据库验收：`TermEntry(notes__contains="hkjc_ja_alias_merged_into_term_id=")=112`，HKJC active 日语 alias 数为 `268`。
- 文章字段回填：
  - 首次未优化 dry-run 在生产扫描中过慢，已终止；随后补丁 `a65c1ed` 预加载 alias map，避免文章字段循环内重复查 alias。
  - dry-run artifact 已复制到宿主机：`runtime/term_backfills/hkjc-ja-article-backfill-20260707_192910/`。
  - dry-run summary：`scanned_articles=713`、`matched_articles=7`、`planned_fields=29`、`skipped_fields=2`、`replacement_count=37`，耗时约 `4.8s`。
  - apply artifact 已复制到宿主机：`runtime/term_backfills/hkjc-ja-article-backfill-apply-20260707_192931/`。
  - apply summary：`updated_fields=29`、`skipped_fields=2`、`stale_fields=0`。
- `Kalamatianos / カラマティアノス` 抽检：
  - 生产 term `6443`：`Kalamatianos -> 欢快舞步`，`racing_region=japan`。
  - active alias：`Kalamatianos` (`en`, primary) 与 `カラマティアノス` (`ja`, alias)。
  - 文章 `7117` dry-run artifact 已复制到宿主机：`runtime/term_backfills/kalamatianos-article-7117-20260707_192945/`，summary 为 `planned=0 scanned=1`，因为文章字段已无残留原文。
  - `http://127.0.0.1/news/7117/` 返回 `200`，页面包含 `欢快舞步`。

### 生产执行前检查

1. 记录生产当前 commit、`docker compose ps`、`web / worker / beat / db / redis / nginx` 状态。
2. 执行 `python manage.py check`。
3. 检查 `http://127.0.0.1/healthz/` 和公网 `/healthz/`。
4. 确认 `ExternalDataImportRun(status="started")=0` 且外部导入锁为空。
5. 执行数据库备份并用 `gzip -t` 校验备份。

### HKJC 日语 alias 概念合并

dry-run 示例：

```bash
python manage.py merge_hkjc_ja_aliases \
  --racing-region japan \
  --output-dir runtime/term_backfills/hkjc-ja-alias-merge-YYYYMMDD_HHMMSS
```

如果使用人工准备的候选文件，候选 CSV/JSON 至少应包含 `target_term_id` 和 `source_text`：

```bash
python manage.py merge_hkjc_ja_aliases \
  --candidate-file imports/hkjc-ja-alias-candidates.csv \
  --output-dir runtime/term_backfills/hkjc-ja-alias-merge-YYYYMMDD_HHMMSS
```

复核 `merge_plan.json`、`merge_plan_review.csv` 和 `summary.json` 后，正式 apply 必须指定已审核 plan：

```bash
python manage.py merge_hkjc_ja_aliases \
  --apply \
  --plan-file runtime/term_backfills/hkjc-ja-alias-merge-YYYYMMDD_HHMMSS/merge_plan.json \
  --output-dir runtime/term_backfills/hkjc-ja-alias-merge-apply-YYYYMMDD_HHMMSS
```

apply 安全边界：

- 只自动处理 active 英文目标概念 + active 日语主术语 + 同 `term_type` + 同规范化 `target_zh` 的安全项。
- apply 前会重新检查当前 term/alias 状态。
- 若日语 source text 被其它 active 概念主原文或 active alias 占用，则写入 skipped，不在目标概念上创建重复 alias。
- 合并成功后，目标概念新增日语 alias，冗余日语主术语会停用，notes 写入 `hkjc_ja_alias_merged_into_term_id=<target>`。

### 已发布文章术语回填

推荐先使用 merge apply artifact 或明确 term id 生成 dry-run diff：

```bash
python manage.py backfill_article_terms \
  --merge-plan-file runtime/term_backfills/hkjc-ja-alias-merge-apply-YYYYMMDD_HHMMSS/merge_apply.json \
  --source-language ja \
  --limit 50 \
  --output-dir runtime/term_backfills/article-term-backfill-YYYYMMDD_HHMMSS
```

也可以明确指定 term/article 范围：

```bash
python manage.py backfill_article_terms \
  --term-id <TERM_ID> \
  --article-id <ARTICLE_ID> \
  --output-dir runtime/term_backfills/article-term-backfill-YYYYMMDD_HHMMSS
```

复核 `article_backfill_diff.json`、`article_backfill_diff_review.csv` 和 `summary.json` 后，正式 apply 推荐读取已审核 diff：

```bash
python manage.py backfill_article_terms \
  --apply \
  --diff-file runtime/term_backfills/article-term-backfill-YYYYMMDD_HHMMSS/article_backfill_diff.json \
  --output-dir runtime/term_backfills/article-term-backfill-apply-YYYYMMDD_HHMMSS
```

文章回填安全边界：

- 默认只扫描 `workflow_status=published` 且 `published_to_web_at` 非空的已发布文章。
- JSON artifact 保存完整 before/after 字段值，可用于字段级回滚；CSV 仅用于人工快速复核。
- 默认跳过 `manually_edited_fields` 中记录的发布字段。
- 不重新抓取、不重新翻译、不调用 AI 改写、不改变发布状态、审核状态、workflow 状态或 QQ 推送状态。
- `--apply` 若没有 `--diff-file`，必须显式提供 term 范围和 article/date/source/limit 过滤之一；无范围写入会被拒绝。

### 验收与回滚

- 合并后抽查后台术语搜索：英文名和日文名都应命中目标 HKJC 概念；被合并的日语主术语应为 inactive 且 notes 记录合并目标。
- 回填后抽查受影响文章前台页面和后台字段，确认只发生术语替换。
- 复查 `/healthz/`、summary 计数和 skipped/review 项。
- 如 alias 合并错误，按 apply artifact 删除目标 alias，并恢复源 term `is_active=true` 和必要 notes。
- 如文章字段替换错误，优先使用 `article_backfill_diff.json` 中的完整 `before` 值恢复；大范围异常时使用生产数据库备份。

## 2026-07-07 法国新闻源扩展与英文术语门禁修复待上线

- 本次待上线 OpenSpec changes：
  - `expand-france-news-sources`
  - `fix-english-term-gate-region-filter`
- 代码范围：
  - 法国新增 `tdn_france_broad` 英文补充来源，默认 `enabled=false`、`production_approved=false`。
  - `probe_international_news_sources` 增加 `status/deferred_reason/http_status/final_url/parse_quality/query_errors/sample_errors`。
  - 国际来源抓取支持单篇详情解析失败跳过继续，全部详情失败时来源 / CrawlJob 标记为 failed。
  - 来源同步新增 `MULTIREGION_SUPPORTED_PRODUCTION_SOURCE_LANGUAGES=ja,en,zh-hant`，法语源不会被误批准生产。
  - 英文发布校验按文章地区 + 全局术语过滤，并对配置化高歧义英文词降级为 warning。
  - 新增 `reprocess_term_gate_blocked_articles` 受控重处理命令，不直接公开发布文章。
- 本地上线前验证：
  - `DB_ENGINE=sqlite .venv/bin/python server/manage.py test stable.tests.FranceNewsSourceExpansionTests ...`
  - `DB_ENGINE=sqlite .venv/bin/python server/manage.py test stable.tests.TermRegionFilterTests ...`
  - `DB_ENGINE=sqlite .venv/bin/python server/manage.py check`
  - `openspec validate expand-france-news-sources --strict`
  - `openspec validate fix-english-term-gate-region-filter --strict`
  - `openspec validate --all`
  - `git diff --check`
- 生产部署前检查：
  - `git rev-parse --short HEAD`
  - `docker compose -f docker-compose.prod.lowcost.yml ps`
  - `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check`
  - `curl -fsS http://127.0.0.1/healthz/`
  - 确认 `ExternalDataImportRun(status="started")=0` 且外部导入锁为空。
  - 执行生产数据库备份，并用 `gzip -t` 校验。
- 生产部署：
  - `/opt/umanewsbot` 执行 `git pull --ff-only origin main`。
  - 执行 `bash ./deploy_lowcost.sh` 重建 `web / worker / beat`。
  - 执行 `python manage.py sync_builtin_sources`，确认 `TDN 法国宽关键词英文新闻` 已写入 `NewsSource` 且默认未批准生产。
- 上线后验证：
  - `python manage.py probe_international_news_sources --source tdn_france_broad --json` 应返回 `accepted` 或明确 `deferred_reason`；若 `query_errors` 非空，记录部分关键词失败但不直接误判整体不可用。
  - `python manage.py reprocess_term_gate_blocked_articles --region hong_kong --dry-run --json`、`--region united_kingdom`、`--region united_states` 应输出候选、跳过和预计重校验结果，不直接发布。
  - `python manage.py audit_multiregion_news_production --json` 应能展示 `gate_issues`、`gate_blockers`、法国来源 parse failed/source no-new 等摘要。
  - `http://127.0.0.1/healthz/`、`http://umafans.run/healthz/`、首页、后台登录入口均应正常。
- 回滚：
  - 代码异常：回滚到部署前 git ref 后执行 `bash ./deploy_lowcost.sh`。
  - 法国新增来源异常：在后台或 shell 将 `tdn_france_broad` 对应 `NewsSource.production_approved=false` 或 `enabled=false`。
  - 英文门禁误放宽：临时清空或收紧 `MULTIREGION_TERM_GATE_AMBIGUOUS_ENGLISH_TERMS`，必要时回滚代码。

## 2026-07-06/07 HKJC / WP Stud 术语库最终清洗与生产导入

- 生产服务器：`/opt/umanewsbot`，导入时 `HEAD=b1ddb54`。
- 本地产物：`runtime/termbase_seed/final-reviewed-import-20260706/`。
  - `seed_candidates_final.csv`：最终导入主表，共 `11257` 行。
  - `hkjc_japan_ja_aliases.csv`：HKJC 日本地区英文马名对应日文 alias，共 `907` 行，其中马名 `883` 行。
  - `japan_aliases_missing.csv`：仍缺日文 alias 的日本地区非马名条目，共 `123` 行，包含骑师 `93`、赛事 `30`。
  - `wpstud_horse_skipped_hkjc_alias_overlap.csv`：WP Stud HorseList 中因 HKJC 官方词条已覆盖而跳过的马名 `10` 行。
  - `repair_report.json`：清洗和导入统计。
- 输入来源：
  - HKJC overseas / QIDS 既有审核候选 `7691` 条。
  - WP Stud race / jockey / racecourse 既有审核候选 `1891` 条。
  - WP Stud HorseList 全量马名 `1866` 条，来源 `https://www.wpstud.com/Translation/Horse/HorseList.html`。
- 清洗规则：
  - 马名尾部国别后缀如 `(JPN)`、`(IRE)`、`(GB)` 不进入正式 `source_ja`，原始写法保留在证据中。
  - 带年份或替代名称的复合赛事名拆为独立术语，例如 `International Stakes` 与 `Benson & Hedges Gold Cup Stakes`。
  - `target_zh` 统一简体中文。
  - HKJC 官方主译名优先；WP Stud 作为社区来源、别名或佐证，不覆盖 HKJC 官方主译名。
- 清洗统计：
  - 去除马名国别后缀 `6481` 次。
  - 拆分年份赛事标记 `59` 次。
  - 去重 `254` 行。
  - 最终马名分布包括 `horse|en|japan=880`、`horse|ja|japan=531`，并覆盖英、法、美、香港和 other 地区。
- 本地验证：
  - 最终 CSV 质量检查：马名国别后缀 `0`、赛事年份标记 `0`、HTML entity 残留 `0`、空值 `0`。
  - 临时 SQLite `import_terms --dry-run`：总计 `11257`、新增 `11254`、更新 `3`、错误 `0`。
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true .venv/bin/python server/manage.py test stable.tests.TermbaseSeedDataPreparationTests --noinput`：通过，`21` 项。
- 生产导入前检查：
  - `web` healthy，`db/redis` healthy，`worker/beat/nginx` 正常运行。
  - `manage.py check` 通过。
  - `http://127.0.0.1/healthz/` 返回 `{"status":"ok"}`。
  - 导入前 `TermEntry=15321`、`TermAlias=15537`。
  - `ExternalDataImportRun(status="started")=0`，`ExternalDataImportLock.locked_by_run_id` 非空计数为 `0`。
- 备份：
  - `backups/db/pre-final-termbase-review-20260706_234427.sql.gz`，约 `75M`，`gzip -t` 通过。
- 生产文件：
  - Host 路径：`/opt/umanewsbot/imports/final-termbase-review-20260706/`。
  - Web 容器路径：`/tmp/final-termbase-review-20260706/`。
- 生产 dry-run：
  - `preview_summary`: 总计 `11257`、新增 `1169`、更新 `10088`、错误 `0`。
  - `import_result`: 新增 `1169`、更新 `10088`、跳过 `0`。
  - `repair_stats`: `horse_suffix_cleaned=6282`、`horse_suffix_deactivated_duplicates=94`、`race_year_cleaned_primary=119`、`race_year_deactivated_duplicates=9`、`race_year_split_created=68`、`race_year_split_existing=5`。
  - `alias_stats`: `alias_upserted=874`、`alias_deactivated_duplicate_ja_entries=27`、`alias_skipped_existing_alias_owner=27`、`alias_skipped_existing_same_language_entry=5`、`alias_skipped_conflicting_same_language_entry=1`。
  - `quality`: active 马名国别后缀 `0`、active 赛事年份标记 `0`。
- 正式导入：
  - 使用 `apply_final_termbase_repair.py` 在事务中先清理既有 active 脏词，再调用 `preview_term_import / commit_term_import`，最后应用跨语言 alias。
  - 正式导入结果与 dry-run 一致：新增 `1169`、更新 `10088`、错误/跳过 `0`。
- 导入后生产计数：
  - `TermEntry=16558`。
  - `TermAlias=19293`。
  - active `TermEntry=16428`。
  - `source_language=en/racing_region=japan/term_type=horse` 为 `880` 条。
  - WP Stud 日文马名 active 词条 `3235` 条。
  - active 马名国别后缀术语 `0`。
  - active 赛事年份标记术语 `0`。
  - `ExternalDataImportRun(status="started")=0`，导入锁为空。
- 抽样验收：
  - `A Bit Of Spirit` 为 active，中文 `点燃斗志`，别名含英文原文；`A Bit Of Spirit (IRE)` 无 active 词条。
  - `International Stakes -> 国际锦标` 与 `Benson & Hedges Gold Cup Stakes -> 宾臣暨赫捷仕金杯` 均为 active 独立赛事术语。
  - `A Shin Resume -> 荣进重启` 挂日文 alias `エイシンレジューム`。
  - `Dragon -> 腾龙` 挂日文 alias `ドラゴン`。
  - `Dynamic -> 鲜明新曲` 挂日文 alias `ダイナマイク`。
  - `Sophia -> 才情苏菲` 挂日文 alias `ソフィア`。
  - `ハーパー` 不保留 active 独立 WP Stud 词条，因为对应概念已由 HKJC 官方 row / alias 覆盖。
- alias 占用说明：
  - `26` 个 HKJC 日本马英文词条未直接新增日文 alias，是因为对应日文名已被生产中 existing `TermAlias` 或日文主词占用；其中大多数中文目标一致。
  - `Raijin / ライジン` 当前生产已有日文词 `ライジン -> 雷神`，本次 HKJC 英文主词为 `Raijin -> 霹雳雷公`，按冲突处理跳过 alias 合并。
  - `Scintillation / シンチレーション` 当前生产已有香港地区占用 `シンチレーション -> 灿惑`，本次 HKJC 英文主词为 `Scintillation -> 烁亮丽`，按 alias owner 占用跳过。
- 导入后验证：
  - `manage.py check` 通过。
  - `http://127.0.0.1/healthz/` 与 Host `umafans.run` 健康检查均返回 `{"status":"ok"}`。

## 2026-07-06/07 香港 HKJC 与美国 HRN 2026 出走表 / 赛果导入

- 生产服务器：`/opt/umanewsbot`，导入时 JRA 同着展示修复仍为 `web` 容器热补丁状态；后续容器重建前仍需通过 git 镜像部署固化。
- 香港官方来源：
  - HKJC 繁中日汇总页：`https://racing.hkjc.com/zh-hk/local/information/resultsall?Racecourse=<ST/HV>&racedate=YYYY/MM/DD`。
  - HKJC 繁中单场完整赛果页：`https://racing.hkjc.com/zh-hk/local/information/localresults?...&RaceNo=N`。
- 香港本地产物：`runtime/race_event_detail_imports/2026/hong-kong-hkjc-details-20260706/`。
  - `hkjc_detail_candidates_2026.jsonl`：生产导入用候选包。
  - `hkjc_detail_review_2026.csv`：人工快速核对用摘要。
  - `summary.json`：生成统计。
  - `sources/`：HKJC `resultsall` 与 `localresults` 页面缓存。
- 香港生成结果：
  - `19` 场 HKJC 当前已公开 2026 本地 G1/G2/G3。
  - `182` 条出走表。
  - `181` 条数字名次赛果。
  - `WV` 写入 `RaceEventRunner.running_status=withdrawn`，不进入 `RaceEventResult`。
  - 展示字段繁转简，原始繁中马名、骑师、练马师保存在 `source_refs`。
- 香港生产导入前备份：
  - `backups/db/pre-race-event-details-hk-2026-20260706_234317.sql.gz`，约 `75M`，`gzip -t` 通过。
- 香港生产 dry-run：
  - `{"dry_run": true, "events": 19, "items": {"runners": 182, "results": 181}}`。
- 香港正式导入：
  - `applied=38`、`candidates=38`、`events=19`、`runners=182`、`results=181`。
- 香港页面验收：
  - `/races/2026/hkjc-2026-0125-05/` 返回 `200`，显示董事杯冠军 `浪漫勇士`、完整出走表和赛果；`祝愿 / 阳光勇士` 同为官方第 `4` 名，完成时间均为 `1:33.18`。
  - `/races/2026/hkjc-2026-0621-19/` 返回 `200`，显示精英碟出走表中 `非惟侥幸` 为取消出走，赛果保留 `11` 条已确认名次。
- 美国范围来源：
  - TOBA 官方 2026 American Graded Stakes 表确定 Grade 1/2/3 已完赛范围和 `chart_url` / RaceNo。
  - Horse Racing Nation track-day 页面提供公开可访问出走表和可见结果顺序。
  - Equibase chart HTML/PDF 当前仍返回 `Pardon Our Interruption` 防护页，不能作为批量抓取来源。
- 美国本地产物：`runtime/race_event_detail_imports/2026/united-states-hrn-details-20260706/`。
  - `us_hrn_detail_candidates_2026.jsonl`：生产导入用候选包。
  - `us_hrn_detail_review_2026.csv`：人工快速核对用摘要。
  - `summary.json`：生成统计。
  - `sources/`：HRN date / track-day 页面缓存。
- 美国生成结果：
  - `195` 场 TOBA 已完赛 Grade 1/2/3。
  - `1710` 条出走表。
  - `1448` 条可确认赛果。
  - 马名展示字段剥离 `(IRE)/(GB)/(SAF)` 等国籍后缀，原始写法保存在 `source_refs.horse_name_raw`。
  - HRN 对 Kentucky Derby / Oaks 等少量页面只公开出走表、不公开 payout / also-rans 结果块；本批不使用 TOBA `winner` 字段猜完整名次，因此这些场次暂不显示赛果。
  - 初次 apply 因 HRN HTML 重复渲染同一出走马导致 `(event, horse_number)` 唯一约束冲突；旧 pending 候选已标为 failed，生成器改为按 `horse_number + horse_name + horse_url` 去重后重跑。
- 美国生产导入前备份：
  - `backups/db/pre-race-event-details-us-hrn-2026-20260707_000230.sql.gz`，约 `75M`，`gzip -t` 通过。
- 美国生产 dry-run：
  - 修正版：`{"dry_run": true, "events": 195, "items": {"runners": 1710, "results": 1448}}`。
- 美国正式导入：
  - 修正版 apply 成功：`applied=390`、`candidates=390`、`events=195`、`runners=1710`、`results=1448`。
- 导入后生产详情总计：
  - `RaceEventRunner=3260`。
  - `RaceEventResult=2977`。
  - `RaceEventHistoryWinner=0`。
  - `RaceEventDataCandidate=992`、`AppliedCandidates=990`、`FailedCandidates=2`、`PendingCandidates=0`。
  - 美国详情行：`Runner=1710`、`Result=1448`。
- 美国页面验收：
  - `/races/2026/us-toba-2026-0108-001/` 返回 `200`，显示 Robert J. Frankel S. 冠军 `Paradise Lake`、出走表和赛果。
  - `/races/2026/us-toba-2026-0502-119/` 返回 `200`，显示 Kentucky Derby 出走表；因 HRN 未公开结果块，暂不显示赛果。
  - `http://umafans.run/healthz/` 返回 `{"status": "ok"}`。

## 2026-07-06 NAR 2026 地方/交流重赏出走表 / 赛果导入

- 生产服务器：`/opt/umanewsbot`，导入时 `HEAD=b1ddb54`，且 JRA 同着展示修复仍为 `web` 容器热补丁状态。
- 官方来源：
  - NAR ダートグレード特设赛事页：`https://www.keiba.go.jp/dirtgraderace/2026/<race>/racecard.html` 或 `introduction.html`。
  - 出馬表：`https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/DebaTable?...`。
  - 競走成績：`https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/RaceMarkTable?...`。
- 本地产物：`runtime/race_event_detail_imports/2026/japan-nar-details-20260706/`。
  - `nar_detail_candidates_2026.jsonl`：生产导入用候选包。
  - `nar_detail_review_2026.csv`：人工快速核对用摘要。
  - `summary.json`：生成统计和未公布出走表缺口。
  - `sources/`：NAR 特设页、出馬表页和競走成績页缓存。
- 生成结果：
  - `21` 场当前官方可用赛事。
  - `256` 条出走表。
  - `242` 条数字名次赛果。
  - `20` 场已完赛写出走表和赛果。
  - `2026-07-08` スパーキングレディーカップ仅官方已公布出走表，未有赛果。
  - `25` 场未来赛事仍停留在 `introduction.html`，未公布出走表，记录为 `racecard_not_published`。
- 状态处理：
  - `除外` 写入 `RaceEventRunner.running_status=scratched`。
  - `取消` 写入 `withdrawn`。
  - 空白着顺写入 `unknown`。
  - 只有数字着顺进入 `RaceEventResult`。
- 生产导入前备份：
  - `backups/db/pre-race-event-details-nar-2026-20260706_232856.sql.gz`，约 `75M`，`gzip -t` 通过。
- 生产 dry-run：
  - 结果：`{"dry_run": true, "events": 21, "items": {"runners": 256, "results": 242}}`。
- 正式导入：
  - `applied=41`、`candidates=41`、`events=21`、`runners=256`、`results=242`。
- 导入后计数：
  - `RaceEventRunner=1368`。
  - `RaceEventResult=1348`。
  - `RaceEventHistoryWinner=0`。
  - `RaceEventDataCandidate=233`、`AppliedCandidates=232`、`FailedCandidates=1`。
  - 当前详情表行仍全部属于日本地区。
- 页面验收：
  - `/races/2026/nar-dirt-2026-0701-20/` 返回 `200`，显示帝王賞冠军 `ミッキーファイト`、出走表、赛果和 `2:02.8`。
  - `/races/2026/nar-dirt-2026-0708-21/` 返回 `200`，显示スパーキングレディーカップ出走表，包含 `レクランスリール` 与 `アピーリングルック`，未显示赛果区块。
  - `http://umafans.run/healthz/` 返回 `{"status": "ok"}`。
  - `manage.py check` 通过。
- 剩余日本详情缺口：
  - JRA 未来 `66` 场未公布出走表 / 赛果。
  - NAR 未来 `25` 场仍为 `introduction.html`，未公布出走表 / 赛果。
  - 后续应按官方发布节奏刷新，不猜测名单。

## 2026-07-06 JRA 2026 已完赛重赏出走表 / 赛果导入

- 生产服务器：`/opt/umanewsbot`，导入时 `HEAD=b1ddb54`。
- 官方来源：
  - JRA 2026 重赏列表：`https://www.jra.go.jp/datafile/seiseki/replay/2026/jyusyo.html`。
  - JRA 普通重赏结果页：`/datafile/seiseki/replay/2026/<id>.html`。
  - JRA G1 结果页：`/datafile/seiseki/g1/<race>/result/<race>2026.html`。
- 本地产物：`runtime/race_event_detail_imports/2026/japan-jra-details-20260706/`。
  - `jra_detail_candidates_2026.jsonl`：生产导入用候选包。
  - `jra_detail_review_2026.csv`：人工快速核对用摘要。
  - `summary.json`：生成统计。
  - `sources/`：JRA 结果页缓存。
- 生成结果：
  - `74` 场 JRA 已完赛中央重赏。
  - `1112` 条出走表。
  - `1106` 条数字名次赛果。
  - `取消=2`、`除外=2`、`中止=2` 不进入 `RaceEventResult`，但保留在 `RaceEventRunner.running_status`。
- 同着处理：
  - `RaceEventResult.finish_position` 当前有唯一约束，因此用于前台排序和数据库唯一位。
  - JRA 官方名次保存在 `source_refs.official_finish_position` 和 `source_refs.jra_finish_position_text`。
  - 前台详情页和日历页优先展示 `official_finish_position`，因此安田記念同着第 2 名会显示两匹第 `2` 名。
- 本地验证：
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true .venv/bin/python server/manage.py test stable.tests.RaceEventPageMVPTests --noinput`：通过，`17` 项。
  - `DB_ENGINE=sqlite .venv/bin/python server/manage.py check`：通过。
  - `git diff --check`：通过。
- 生产导入前检查：
  - `web` healthy，`db/redis` healthy，`worker/beat/nginx` 正常运行。
  - 导入前详情表均为空：`RaceEventRunner=0`、`RaceEventResult=0`、`RaceEventHistoryWinner=0`、`RaceEventDataCandidate=0`。
- 备份：
  - `backups/db/pre-race-event-details-jra-2026-20260706_224953.sql.gz`，约 `75M`，`gzip -t` 通过。
- 生产 dry-run：
  - 通过临时脚本 `imports/race-event-details-jra-2026-20260706/apply_race_event_detail_jsonl.py` 在 `web` 容器内执行。
  - 结果：`{"dry_run": true, "events": 74, "items": {"runners": 1112, "results": 1106}}`。
- 首次正式 apply：
  - 在 `オーシャンS` 遇到 JRA 同着，触发 `uq_race_result_event_pos` 唯一约束冲突后停止。
  - 停止时已有 `Runner=332`、`Result=316`、`Candidate=44`、`AppliedCandidates=43`、`PendingCandidates=1`。
  - 修正候选包后重新从头 apply，旧 pending 候选标记为 `failed`，错误说明为 `superseded by rerun after duplicate finish-position normalization`。
- 正式导入结果：
  - 第二次 apply 成功：`applied=148`、`candidates=148`、`events=74`、`runners=1112`、`results=1106`。
  - 导入后生产：`RaceEventRunner=1112`、`RaceEventResult=1106`、`RaceEventDataCandidate=192`、`AppliedCandidates=191`、`FailedCandidates=1`。
  - 宝塚記念：`runners=18`、`results=17`，冠军为 `メイショウタバル`。
  - 安田記念：`ワールズエンド` 与 `ガイアフォース` 均保留 `official_finish_position=2`。
- 前台展示热补丁：
  - 为立即正确展示同着名次，已将本地 `server/stable/views.py`、`server/stable/templates/stable/public/race_detail.html`、`server/stable/templates/stable/public/race_calendar.html` 复制到 `umanewsbot-web-1` 容器并重启同一容器。
  - 容器重建会丢失该热补丁；后续正式部署前必须先将这三处改动通过 git 提交/部署固化。
- 验收：
  - `http://umafans.run/healthz/` 返回 `{"status": "ok"}`。
  - `/races/2026/takarazuka-kinen/` 返回 `200`，显示 `メイショウタバル`、出马表、赛果和 `2:12.1`。
  - `/races/2026/jra-2026-0607-01/` 返回 `200`，`ワールズエンド` 与 `ガイアフォース` 在头部摘要和赛果表中均显示第 `2` 名，`ガイアフォース` 显示 `同着`。
  - `web` healthy，`worker / beat / db / redis / nginx` 正常运行。
- 剩余工作：
  - 继续补 JRA 未完赛场次的赛前出走表。
  - 继续补 NAR、HKJC、美国、英国、法国的出走表和赛果。
  - 在出走表和赛果稳定后，再开始导入历届冠军。

## 2026-07-06 英国 BHA Flat 2026 Group 赛事 OCR 导入

- 生产服务器：`/opt/umanewsbot`，导入时 `HEAD=87319b4`。
- 官方来源：`https://media.britishhorseracing.com/bha/Publications/Pattern_Listed_Books/British_Flat_Pattern_Listed_2026.pdf`。
- 本地产物：`runtime/race_event_imports/2026/united-kingdom-bha-pattern-20260706/`。
- 解析方式：
  - BHA Flat 官方 PDF 正文页无可用文本层，普通 PDF 文本抽取为空。
  - 本次使用 `pdftoppm` 渲染详情页，再通过 macOS Vision OCR 生成 `flat_detail_ocr.jsonl`。
  - 赛事名、日期、场地和等级来自官方详情页 OCR；距离字段来自 OCR，明显残缺项已清空或人工清理，并统一保留 `data_quality_status=partial`。
  - 场地规则：Kempton Park / Lingfield Park / Newcastle / Southwell / Wolverhampton / Chelmsford City 或 OCR 含 `AWT` 时记为 `synthetic`，其他 Flat 赛事记为 `turf`。
- 范围：
  - British Flat Pattern and Listed Races 2026 中 `Group 1 / Group 2 / Group 3`。
  - 排除 Listed。
- 生成结果：
  - `138` 场；`G1=33`、`G2=42`、`G3=63`。
  - `finished=59`、`scheduled=79`。
  - `synthetic=6`、`turf=132`。
- 本地验证：
  - `DB_ENGINE=sqlite .venv/bin/python server/manage.py import_race_events --csv runtime/race_event_imports/2026/united-kingdom-bha-pattern-20260706/race_events_united_kingdom_bha_flat_2026.csv --dry-run` 通过。
- 生产导入前检查：
  - `web` healthy，`db/redis` healthy，`worker/beat/nginx` 正常运行。
  - `RaceEvent=857`、`RaceEventAlias=2863`、`UK2026=65`、`UKFlatExisting=0`。
  - `TaskExecutionLog(task_name="import_race_events", status="started")=0`。
- 备份：
  - `backups/db/pre-race-events-uk-bha-flat-2026-20260706_222151.sql.gz`，约 `74M`，`gzip -t` 通过。
- 生产文件：
  - Host 路径：`/opt/umanewsbot/imports/race-events-uk-bha-flat-2026-20260706/race_events_united_kingdom_bha_flat_2026.csv`。
  - 注意：`imports/` 未挂载到 `web` 容器；已使用 `docker cp` 复制到 `web:/tmp/race_events_united_kingdom_bha_flat_2026.csv` 后执行管理命令。
- 生产 dry-run：
  - `docker compose exec -T web python manage.py import_race_events --csv /tmp/race_events_united_kingdom_bha_flat_2026.csv --dry-run` 通过。
- 正式导入：
  - `created=138 updated=0 aliases=414`。
- 导入后计数：
  - `RaceEvent=995`、`RaceEventAlias=3277`。
  - `UK2026=203`、`UKFlat2026=138`、`UKFlatVisible=138`、`UKFlatSynthetic=6`。
- 页面验收：
  - `/races/?tab=all&region=united_kingdom` 返回 `200`，可命中 `CORAL-ECLIPSE` 与“复合赛道”。
  - `/races/2026/uk-bha-flat-2026-0704-058/` 返回 `200`，显示 `CORAL-ECLIPSE`。
  - `/races/2026/uk-bha-flat-2026-0905-102/` 返回 `200`，显示 `UNIBET SEPTEMBER STAKES` 与“复合赛道”。
- 剩余缺口：
  - HKJC 尚未公开 2026/27 马季年末香港本地 G1/G2/G3 日期明细。
  - 英国 Jump 2026 年 10-12 月需要 2026/27 官方书或其他官方结构化来源。

## 2026-07-06 赛事日历 2026 NAR / 美国 / 英国 Jump / 法国正式导入

- 生产服务器：`/opt/umanewsbot`。
- 日本 NAR/交流ダートグレード批次：
  - 官方来源：`https://www.keiba.go.jp/dirtgraderace/2026/racelist/index.html`、`https://www.keiba.go.jp/pdf/uploads/20251110_01_01.pdf`。
  - 本地产物：`runtime/race_event_imports/2026/japan-nar-dirt-graded-20260706/`。
  - 范围：地方竞马场 JpnⅠ/JpnⅡ/JpnⅢ 与大井东京大赏典 GⅠ，共 `46` 场；排除已在 JRA 中央批次导入的中央场 G/J-G 赛事。
  - 生成结果：`JPN3=21`、`JPN2=12`、`JPN1=12`、`G1=1`；`finished=20`、`scheduled=26`；官方网页给出发走时刻 `22` 场，另 `24` 场时刻待定。
  - 备份：`backups/db/pre-race-events-japan-nar-2026-20260706_133705.sql.gz`，约 `73M`，`gzip -t` 通过。
  - 生产 dry-run：`python manage.py import_race_events --csv /tmp/race_events_japan_nar_dirt_graded_2026.csv --dry-run` 通过。
  - 正式导入：`created=46 updated=0 aliases=105`。
  - 验收：生产计数 `Japan2026=186`、`NAR2026=46`、`NARWithTime=22`、`NARPendingTime=24`；公网 `/races/2026/nar-dirt-2026-0701-20/` 显示帝王赏与 `20:05`，`/races/2026/nar-dirt-2026-1229-46/` 显示东京大赏典与“待定”。
- 复合赛道支持上线：
  - 本地提交并推送 `9dc9b4d Support synthetic race event surface`。
  - 新增 `RaceEventSurface.SYNTHETIC=synthetic/复合赛道` 与迁移 `stable.0021_alter_raceevent_surface`。
  - 本地验证：`RaceEventPageMVPTests` 14 项、`manage.py check`、`makemigrations --check --dry-run` 和 `git diff --check` 通过。
  - 生产部署：从 `40133ec` 快进到 `9dc9b4d`，`.env` 已备份为 `.env.backup.synthetic-surface-<timestamp>`，Docker build context 约 `878.5kB`；部署后 `web/worker/beat` 重建，`manage.py check` 通过，`showmigrations stable` 显示 `[X] 0021_alter_raceevent_surface`，生产 shell 确认 `synthetic 复合赛道`。
- 美国 TOBA Grade 批次：
  - 官方来源：`https://toba.org/graded-stakes/2026-races/`。
  - 本地产物：`runtime/race_event_imports/2026/united-states-toba-graded-20260706/`。
  - 范围：当前 TOBA 表内 Grade 1/2/3，共 `411` 条；排除 Listed `200` 条与其他非分级黑体 `12` 条。当前 TOBA 表解析为 `411` 条 Grade，而页面公告口径写 `410`，本次以当前官方表格行为准并在 `summary.json` 记录差异。
  - 生成结果：`G1=92`、`G2=136`、`G3=183`；`370` 条有日期并公开展示，`41` 条空日期或 `not run` 作为 draft 底表记录保留；surface 为 `dirt=222`、`turf=186`、`synthetic=3`。
  - 备份：`backups/db/pre-race-events-us-toba-graded-2026-20260706_134731.sql.gz`，约 `73M`，`gzip -t` 通过。
  - 正式导入：dry-run 通过后 `created=411 updated=0 aliases=1550`。
  - 验收：`USTOBA2026=411`、`USTOBAVisible=370`、`USTOBADraft=41`、`Synthetic=3`；`/races/2026/us-toba-2026-0321-068/` 返回 `200` 并显示 `JEFF RUBY STEAKS` 与“复合赛道”，undated draft 详情返回 `404`。
- 英国 BHA Jump 批次：
  - 官方来源：`https://media.britishhorseracing.com/bha/Publications/Pattern_Listed_Books/British_Jump_Pattern_Listed_2526.pdf`。
  - 本地产物：`runtime/race_event_imports/2026/united-kingdom-bha-pattern-20260706/`。
  - 范围：BHA 2025/2026 Jump Pattern and Listed 书中日期落在 2026 年 1-4 月的 Grade 1/2/3；排除 Listed、Premier Handicap 和 2025 年赛季内赛事。本官方书当前只能覆盖 2026 年 1-4 月，2026 年 10-12 月需等待 2026/27 官方书或其他官方结构化来源。
  - 生成结果：`64` 场，`G1=28`、`G2=36`、`G3=0`。
  - 备份：`backups/db/pre-race-events-uk-bha-jump-2026-20260706_214916.sql.gz`，约 `74M`，`gzip -t` 通过。
  - 正式导入：dry-run 通过后 `created=64 updated=0 aliases=192`。
  - 验收：`UKJump2026=64`、`UKJumpVisible=64`；`/races/2026/uk-bha-jump-2026-0313-042/` 返回 `200` 并显示 `Boodles Cheltenham Gold Cup Chase`、`Cheltenham` 与“障碍”。
- 法国 France Galop Groupe 批次：
  - 官方来源：`https://www.france-galop.com/sites/default/files/2026-02/groupes_listed_plat_2026_v7.pdf`、`https://www.france-galop.com/sites/default/files/2026-01/groupes_listed_obstacles_2026_v4.pdf`。
  - 本地产物：`runtime/race_event_imports/2026/france-france-galop-group-20260706/`。
  - 范围：逐赛条件页中 `Groupe I / Groupe II / Groupe III`；排除 Listed。因 PDF 文字层存在 `CHANTILL Y`、`Prix Saint` 等抽取伪影，本批已做马场名修正并在 `source_refs.racecourse_parser_fix` 记录。
  - 生成结果：`173` 条，Flat `113`、障碍 `60`；`G1=37`、`G2=38`、`G3=98`。
  - 备份：`backups/db/pre-race-events-france-galop-group-2026-20260706_215904.sql.gz`，约 `74M`，`gzip -t` 通过。
  - 正式导入：dry-run 通过后 `created=173 updated=0 aliases=519`。
  - 验收：`FranceGalop2026=173`、`FranceFlat=113`、`FranceJumps=60`；`/races/2026/fr-france-galop-2026-0426-014/` 返回 `200` 并显示 `PRIX GANAY`、`ParisLongchamp` 与“草地”，`/races/2026/fr-france-galop-2026-0517-138/` 返回 `200` 并显示 `GRAND STEEPLE-CHASE DE PARIS`、`Auteuil` 与“障碍”。
- 导入后总计：
  - 生产 `RaceEvent=857`、`RaceEventAlias=2863`。
  - 2026 五地区计数：日本 `186`、香港 `20`、美国 `412`、英国 `65`、法国 `174`。
- 剩余缺口：
  - HKJC 尚未公开 2026/27 马季年末香港国际赛等日期明细。
  - BHA Flat 2026 官方 PDF 正文页文字层为空，需要 OCR 或找到另一官方结构化源后再补英国 Flat Group 1/2/3。
  - 英国 Jump 2026 年 10-12 月需要 2026/27 官方书或其他官方结构化源。

## 2026-07-06 赛事日历 2026 日本与香港正式导入

- 生产服务器：`/opt/umanewsbot`，当前导入时 `HEAD=c996621`。
- 导入前检查：
  - `web` healthy，`worker / beat / db / redis / nginx` 正常运行。
  - `ExternalDataImportRun(status="started")=0`。
  - `ExternalDataImportLock.locked_by_run_id` 为空。
- 日本 2026 JRA 中央重赏批次：
  - 官方来源：`https://www.jra.go.jp/datafile/seiseki/replay/2026/jyusyo.html`。
  - 本地产物：`runtime/race_event_imports/2026/japan-jra-central-graded-20260706/`。
  - 范围：JRA 中央 `G1/G2/G3/J-G1/J-G2/J-G3`，不含 Listed/Open 和地方交流重赏。
  - 生成结果：`140` 场，`G1=24`、`G2=38`、`G3=68`、`JG1=2`、`JG2=3`、`JG3=5`；`finished=74`、`scheduled=66`。
  - 备份：首次 `pg_dump -U postgres` 因生产库角色不是 `postgres` 失败且未写库；有效备份改用运行中的 `db` 容器执行 `pg_dump -U horse_news -d horse_news`，文件为 `backups/db/pre-race-events-jra-2026-20260706_113855.sql.gz`，大小约 `72M`，`gzip -t` 通过。
  - 生产 dry-run：`python manage.py import_race_events --csv /tmp/race_events_japan_jra_2026.csv --dry-run` 通过。
  - 正式导入：`created=139 updated=1 aliases=413`；`宝塚記念` 更新既有样例 `takarazuka-kinen`。
  - 导入后计数：`RaceEvent=144`、`RaceEventAlias=423`、`japan/year=2026` 为 `140` 场。
  - 前台验收：`/races/?region=japan`、`/races/2026/takarazuka-kinen/`、`/races/2026/jra-2026-1227-01/` 和 `/races/2026/jra-2026-0104-01/` 均返回 `200` 并显示基础资料。
- 香港 2026 HKJC 分级赛批次：
  - 官方来源：`https://racing.hkjc.com/zh-hk/international-racing/g2-g3-races/index`、`https://campaigns.hkjc.com/racing-event-hub/ch/`，并用 HKJC 本地赛果页补马场、距离和场地。
  - 本地产物：`runtime/race_event_imports/2026/hong-kong-hkjc-pattern-20260706/`。
  - 范围：HKJC 当前公开 2025/26 马季内、比赛日期落在 2026 年的香港本地 `G1/G2/G3`，共 `19` 场；不包含四岁马经典赛、Listed/Open、地区重赏，也不猜测尚未由 HKJC 公开 2026/27 日期的 2026 年末香港国际赛。
  - 生成结果：`19` 场，`G1=8`、`G2=2`、`G3=9`；全部为 `finished`；已过滤非单场赛事卡片 `沙田煞科日`。
  - 备份：`backups/db/pre-race-events-hk-2026-20260706_115242.sql.gz`，大小约 `72M`，`gzip -t` 通过。
  - 生产 dry-run：`python manage.py import_race_events --csv /tmp/race_events_hong_kong_hkjc_2026.csv --dry-run` 通过。
  - 正式导入：`created=19 updated=0 aliases=74`。
  - 导入后计数：`RaceEvent=163`、`RaceEventAlias=497`、`hong_kong/year=2026` 为 `20` 条，其中 `19` 条为本批 HKJC 官方源，另 `1` 条为既有香港杯样例。
  - 前台验收：`/races/?tab=all&region=hong_kong`、`/races/?tab=key&region=hong_kong&direction=past&cursor=2026-07-06`、`/races/2026/hkjc-2026-0125-05/`、`/races/2026/hkjc-2026-0426-13/`、`/races/2026/hkjc-2026-0114-03/` 均返回 `200` 并显示简体中文名、繁体原名、马场、距离、基础资料和出马表占位。
- 操作注意：
  - 生产主机 `imports/` 目录没有挂载到 `web` 容器；CSV 上传到 `/opt/umanewsbot/imports/...` 后，需要再 `docker cp` 到 `umanewsbot-web-1:/tmp/...` 执行导入命令。
  - HKJC 官方页当前未公开 2026/27 马季年底香港国际赛日期明细；后续应等官方赛期公开后再补 2026 年末香港 G1，而不是沿用样例日期。

## 2026-07-06 赛事马名后缀清洗与 Docker build context 修复上线

- 本地提交：
  - `3a25233`：记录日本/香港赛事导入，并在赛事候选资料应用层清洗马名末尾国籍后缀。
  - `b6cbe7c`：新增 `.dockerignore`，排除 `.git / .venv / runtime / imports / backups / napcat / logs / server/staticfiles / server/media` 等运行产物。
- 上线前本地验证：
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true .venv/bin/python server/manage.py test stable.tests.RaceEventPageMVPTests --noinput`：通过，13 项。
  - `DB_ENGINE=sqlite .venv/bin/python server/manage.py check`：通过。
  - `git diff --check`：通过。
- 生产操作：
  - 首次部署 `3a25233` 前确认 `ExternalDataImportRun(status="started")=0`、导入锁为空，并备份 `.env` 为 `.env.backup.race-event-horse-suffix-20260706_115804`。
  - 首次构建因仓库没有 `.dockerignore`，Docker build context 持续增长到 `3GB+` 仍未进入构建；中断后确认旧容器仍正常、`web` healthy、`manage.py check` 通过。
  - 推送 `b6cbe7c` 后，生产从 `3a25233` 快进到 `b6cbe7c`，并备份 `.env` 为 `.env.backup.race-event-dockerignore-20260706_120450`。
  - 重新部署时 build context 降至约 `877.5kB`，镜像构建、容器重建、迁移检查和 collectstatic 均完成；`web / worker / beat` 已重建，`db / redis / nginx` 正常。
- 部署后验证：
  - 生产 `HEAD=b6cbe7c`。
  - `manage.py check` 通过。
  - 容器内 `_clean_race_horse_name("Calandagan (IRE)") == "Calandagan"`，`_clean_race_horse_name("Masquerade Ball（JPN）") == "Masquerade Ball"`。
  - 生产计数保持 `RaceEvent=163`、`RaceEventAlias=497`、`Japan2026=140`、`HK2026=20`。
  - 通过公网 Host 验收：`/healthz/`、`/races/`、`/races/2026/takarazuka-kinen/`、`/races/2026/hkjc-2026-0125-05/`、`/races/?tab=all&region=hong_kong` 均返回 `200`。

## 2026-07-06 赛事日历线上验收与示例审核包

- 生产服务器：`/opt/umanewsbot` 当前 `HEAD=c996621`。
- 线上验收：
  - 公网 `http://umafans.run/healthz/` 返回 `200`，内容为 `{"status": "ok"}`。
  - 公网 `/races/` 返回 `200`。
  - 公网 `/admin/login/` 返回 `200`。
  - `web` 为 healthy，`worker / beat / db / redis / nginx` 正常运行。
  - `manage.py check` 通过。
  - `showmigrations stable` 确认 `[X] 0020_raceevent_articleracelink_raceeventalias_and_more`。
  - `ExternalDataImportRun(status="started")=0`，导入锁为空。
- 生产赛事模块当前计数：
  - `RaceEvent=5`、`RaceEventAlias=10`。
  - `RaceEventRunner=0`、`RaceEventResult=0`、`RaceEventDataCandidate=0`、`ArticleRaceLink=0`。
  - 五地区各 1 条样例赛事。
- 示例审核包：
  - 路径：`runtime/race_event_review_samples/japan-cup-2025-20260706/`。
  - 官方来源：`https://japanracing.jp/en/japancup/news_results/news2025/251130-02.html`。
  - 文件：`race_events_sample.csv`、`race_event_candidate_payload.json`、`source_official.html`、`README.md`。
  - 样例为 `2025 Japan Cup`，日本 `G1`，非 listed，非地区重赏；解析出基础资料 1 组、出走表 17 匹、正式完赛赛果 16 条。
  - `DB_ENGINE=sqlite .venv/bin/python server/manage.py import_race_events --csv runtime/race_event_review_samples/japan-cup-2025-20260706/race_events_sample.csv --dry-run` 通过。
  - `race_event_candidate_payload.json` 已通过 JSON 格式校验。
  - 本次不写生产库；CSV 中 `visibility_status=draft`，等待人工审核后再进入小流量多次正式爬取。

## 2026-07-06 HKJC 术语种子抽取返修上线

- 本地上线提交：`4b6e840`（`Harden HKJC termbase seed extraction`），已推送 `origin/main`。
- 生产服务器：`/opt/umanewsbot` 从 `9b3bb86` 快进到 `4b6e840`。
- 上线前本地验证：
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true .venv/bin/python server/manage.py test stable.tests.TermbaseSeedDataPreparationTests --noinput`：通过，21 项。
  - `DB_ENGINE=sqlite .venv/bin/python server/manage.py check`：通过。
  - `openspec validate --all`：通过，17 项。
  - `git diff --check`：通过。
- 上线前生产检查：
  - `ExternalDataImportRun(status="started")=0`。
  - `ExternalDataImportLock.locked_by_run_id` 当前为空。
  - `web / worker / beat / db / redis / nginx` 上线前均在运行，`web` 为 healthy。
- 备份：
  - `.env`：`.env.backup.harden-hkjc-termbase-20260706_043557`。
  - 数据库：`backups/db/pre-harden-hkjc-termbase-20260706_043557.sql.gz`，大小约 `71M`，已执行 `gzip -t` 校验。
- 部署命令：
  - `git fetch origin main && git pull --ff-only origin main`
  - `./deploy_lowcost.sh`
- 部署结果：
  - `web / worker / beat` 已重建并启动，`db / redis / nginx` 正常。
  - 服务器内 `/healthz/` 返回 `200`，内容为 `{"status": "ok"}`。
  - `manage.py check`：通过。
  - `showmigrations stable` 确认 `[X] 0020_raceevent_articleracelink_raceeventalias_and_more`。
  - 服务器内 `Host: umafans.run`：`/`、`/races/`、`/admin/login/` 均返回 `200`。
  - 本机经 `--resolve umafans.run:80:47.239.167.86` 访问公网 `/healthz/` 返回 `200`。
- 术语种子 smoke：
  - 命令：`python manage.py prepare_termbase_seed_data --source hkjc_overseas --input-dir stable/fixtures/termbase_seed --output-dir runtime/termbase_seed/harden-hkjc-termbase-smoke-20260706_045028`
  - 结果：`candidate_count=9`、`conflict_count=0`、`request_count=0`、`dry_run_error_count=0`、`incomplete=false`。
  - 生产 shell smoke 已验证 HKJC/QIDS 同英文名、不同 `QIDSCode` 的加拿大马不会误合并：两个候选分别生成 `hkjc_overseas:horse:can001` 与 `hkjc_overseas:horse:can002`，地区均落为 `other`。
  - 本次未导入正式术语，生产计数保持 `TermEntry=15321`、`TermAlias=15537`。
- 后续注意：
  - 本次生产 Docker build 上下文已超过 `1.6GB`，主要来自服务器工作区运行产物；后续应补 `.dockerignore` 或隔离 `runtime / imports / backups / napcat` 等目录，降低构建时间与断线风险。

## 2026-07-04 赛事日历 MVP 与 HKJC overseas 术语种子 smoke 上线

- 本地上线提交：`f3c4c46`（`Add race calendar and HKJC overseas termbase seeds`），已推送 `origin/main`。
- 生产服务器：`/opt/umanewsbot` 从 `3aa22fb` 快进到 `f3c4c46`。
- 上线前本地验证：
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true .venv/bin/python server/manage.py test stable --noinput`：通过，442 项。
  - `openspec validate --all`：通过，17 项。
  - `git diff --check`：通过。
- 上线前生产检查：
  - `ExternalDataImportRun(status="started")=0`。
  - `ExternalDataImportLock.locked_by_run_id` 当前为空。
  - `web / worker / beat / db / redis / nginx` 上线前均在运行。
- 备份：
  - `.env`：`.env.backup.race-calendar-hkjc-overseas-20260704_182412`。
  - 数据库：`backups/db/rds_horse_news_race_calendar_manual_20260704_182458.sql.gz`，大小约 `63M`，已执行 `gzip -t` 校验。
  - 注意：首次尝试 `deploy/backup_db.sh` 时因脚本读取 `.env` 中 OSS 目标且临时 `postgres:16` 容器不在 Compose 网络内，产生 20 字节无效备份；该无效文件已删除。本次有效备份改用正在运行的 `db` 容器执行 `pg_dump`。
- 部署命令：
  - `git fetch origin main && git pull --ff-only origin main`
  - `./deploy_lowcost.sh`
- 部署结果：
  - `web / worker / beat` 已重建并启动，`db / redis / nginx` 正常。
  - `manage.py check`：通过。
  - `showmigrations stable` 确认 `[X] 0020_raceevent_articleracelink_raceeventalias_and_more`。
  - `collectstatic` 成功，公开 CSS 指纹更新。
- 赛事日历种子：
  - `python manage.py import_race_events --csv stable/data/race_events_seed_sample.csv --dry-run`：通过，将处理 5 条。
  - 正式导入结果：`created=5 updated=0 aliases=10`。
  - 生产计数：`RaceEvent=5`、`RaceEventAlias=10`、`ArticleRaceLink=0`、`P0/P1=5`。
- 线上路由验收：
  - 服务器内 `Host: umafans.run`：`/healthz/`、`/`、`/races/`、`/admin/login/` 均返回 `200`，未登录 `/admin/race-events/` 返回 `302`。
  - 赛事详情：`/races/2026/takarazuka-kinen/` 返回 `200`，包含“基础资料”和“出马表”区块。
  - 本机经公网 IP + `Host: umafans.run`：`/healthz/`、`/races/`、`/races/2026/takarazuka-kinen/` 均返回 `200`。
  - 本机环境中 `umafans.run` DNS 一度解析到 `198.18.0.181`，因此本次公网验收以 `47.239.167.86` + `Host` 头为准。
- HKJC overseas 术语种子 smoke：
  - 命令：`python manage.py prepare_termbase_seed_data --source hkjc_overseas --input-dir stable/fixtures/termbase_seed --output-dir runtime/termbase_seed/hkjc-overseas-deploy-smoke-20260704_183048`
  - 结果：`candidate_count=9`、`conflict_count=0`、`request_count=0`、`dry_run_error_count=0`、`incomplete=false`。
  - 本次只生成人工审核工件，不正式导入 `TermEntry` / `TermAlias`。
- 后续注意：
  - 生产 Docker build 上下文超过 `700MB`，主要来自服务器工作区未跟踪的 `runtime / imports / napcat / backups` 等运行产物；后续应单独补 `.dockerignore` 或调整部署目录，降低构建时间和传输成本。
  - `deploy/backup_db.sh` 在当前生产 `.env` 下会被 `BACKUP_TARGET=oss` 覆盖，并且临时容器访问 Compose 内部 `db` 主机名失败；后续应修正为显式接入 Compose 网络或提供 db 容器备份路径，避免产生误导性空备份。

## 服务器信息记录方式

不要把敏感信息硬编码进仓库，但应按如下方式记录：

- 服务器公网 IP：记录在运维文档或受控密码库中
- 域名：记录在仓库文档中
- DNS 提供商：记录在仓库文档中
- ECS 地域与实例规格：记录在仓库文档中
- `.env` 实际值：只保存在服务器与受控密钥管理位置，不写入仓库

敏感信息包括但不限于：

- root 密码
- API Key
- OSS AccessKey
- `.env` 完整内容

## 域名、DNS、ECS、Nginx、Docker Compose、.env 的关系

- 域名：用户可见入口，例如 `umafans.run`
- DNS：负责把域名解析到 ECS 公网 IP
- ECS：承载 Docker 容器的主机
- Docker Compose：编排 `web / worker / beat / db / redis / nginx`
- Nginx：处理入口请求、静态资源、反向代理
- `.env`：决定 Django 与部署链路运行方式，如 Host、CSRF、SITE_URL、安全策略等

## 本轮修复时验证过的关键检查命令

### 服务器代码版本

```bash
cd /opt/umanewsbot
git rev-parse --short HEAD
```

### 查看 `.env` 关键项

```bash
grep -E '^(ALLOWED_HOSTS|CSRF_TRUSTED_ORIGINS|SITE_URL|SECURE_SSL_REDIRECT|SESSION_COOKIE_SECURE|CSRF_COOKIE_SECURE|SECURE_HSTS_SECONDS|SECURE_HSTS_INCLUDE_SUBDOMAINS|DJANGO_ADMIN_URL)=' .env
```

### 查看容器状态

```bash
docker compose -f docker-compose.prod.lowcost.yml ps
```

### 查看 nginx 容器中的真实配置

```bash
docker exec umanewsbot-nginx-1 sh -c 'cat /etc/nginx/conf.d/default.conf'
```

### 查看 web 容器中的真实环境变量

```bash
docker exec umanewsbot-web-1 sh -c 'env | grep -E "^(ALLOWED_HOSTS|CSRF_TRUSTED_ORIGINS|SITE_URL|SECURE_SSL_REDIRECT|SESSION_COOKIE_SECURE|CSRF_COOKIE_SECURE|SECURE_HSTS_SECONDS|SECURE_HSTS_INCLUDE_SUBDOMAINS|DJANGO_ADMIN_URL)="'
```

### 查看日志

```bash
docker logs --tail=120 umanewsbot-web-1
docker logs --tail=120 umanewsbot-nginx-1
docker logs --tail=120 umanewsbot-worker-1
docker logs --tail=120 umanewsbot-beat-1
```

## 以后遇到“HTTP 301 / HTTPS 400 / 域名不通”时的排查顺序

### 1. 先确认 DNS

- 本地 `nslookup`
- 必要时查公共 DNS
- 确认是否已解析到目标 ECS 公网 IP

### 2. 再确认服务器代码版本

- `git rev-parse --short HEAD`
- 不要假设服务器已经是本地最新 commit

### 3. 确认 `.env`

- 是否仍是旧域名/旧 IP/旧安全配置
- 是否包含正确的 `ALLOWED_HOSTS`
- `SITE_URL` 是否与当前阶段一致

### 4. 确认 nginx 运行态

- 不只看仓库里的 `nginx.conf`
- 必须进入 `nginx` 容器读取真实 `default.conf`

### 5. 确认 Django 运行态

- 进入 `web` 容器检查真实环境变量
- 再看 `web` 日志里是否有 `DisallowedHost`、CSRF、重定向等问题

### 6. 最后再看浏览器现象

- 浏览器现象只能说明“外部表现”
- 不能替代对 `nginx`、`.env`、容器环境变量、日志的核对

## 标准流程

### 备份 `.env`

```bash
cd /opt/umanewsbot
cp .env .env.backup.$(date +%Y%m%d_%H%M%S)
```

### 检查 HEAD

```bash
git rev-parse --short HEAD
```

### 查看 nginx 容器配置

```bash
docker exec umanewsbot-nginx-1 sh -c 'cat /etc/nginx/conf.d/default.conf'
```

### 查看 web 环境变量

```bash
docker exec umanewsbot-web-1 sh -c 'env | grep -E "^(ALLOWED_HOSTS|CSRF_TRUSTED_ORIGINS|SITE_URL|SECURE_SSL_REDIRECT|SESSION_COOKIE_SECURE|CSRF_COOKIE_SECURE|SECURE_HSTS_SECONDS|SECURE_HSTS_INCLUDE_SUBDOMAINS|DJANGO_ADMIN_URL)="'
```

### 查看日志

```bash
docker logs --tail=120 umanewsbot-web-1
docker logs --tail=120 umanewsbot-nginx-1
```

## 新闻抓取健康排查

### 后台入口

日常先看业务后台：

- `/admin/` 工作台的“最近来源状态”
- `/admin/sources/` 来源管理列表

重点确认：

- 最近抓取时间
- 运行状态
- 最近结果摘要
- 是否显示“运行中”“运行超时”“成功无新增”“失败”或“长时间未运行”

“成功无新增”表示抓取任务正常执行，但本轮抓到的文章都已存在；这不等同于抓取失败。
“运行中”表示最新抓取记录已开始但尚未写入最终结果；如运行中记录超过 60 分钟仍未完成，后台会显示“运行超时”，需要检查 worker / beat 日志和对应 `CrawlJob`。
“长时间未运行”只用于仍启用的来源；停用来源不纳入该告警。

### 服务器查询

```bash
cd /opt/umanewsbot
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py shell -c "from stable.models import CrawlJob; from django.utils import timezone; [print(timezone.localtime(j.started_at).strftime('%F %T'), j.source.name if j.source_id else '-', j.status, j.success_count, j.fail_count, (j.error_message or '')[:120]) for j in CrawlJob.objects.select_related('source').order_by('-started_at')[:20]]"
```

### 当前内置抓取频率

- netkeiba 新着顺：每小时 `00` 分抓取，周日重赏时段另有高频补抓。
- netkeiba 访问量榜：每小时 `16` 分抓取第一页。
- netkeiba 注目数榜：每小时 `26` 分抓取第一页。
- JRA 官方新闻：每 12 小时扫描当前月和上月。

部署涉及抓取调度变更后，必须重启 `beat / worker / web`，并在连续一个小时内确认 netkeiba 新着顺、访问量榜和注目数榜分别按 `00/16/26` 分生成错峰 `CrawlJob`；周日重赏高频补抓分钟不得与访问量榜 / 注目数榜重合。

### JRA 日期解析验收

如 JRA 曾出现 `time data '5月31日' does not match format '%Y年%m月%d日'`，部署后可以手动触发或等待下一次任务：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py crawl_news jra
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py shell -c "from stable.models import CrawlJob, NewsSource; source=NewsSource.objects.get(source_site='jra', source_mode='official'); print(source.last_crawl_status, source.last_crawl_message); print(CrawlJob.objects.filter(source=source).order_by('-started_at').values('status','success_count','fail_count','error_message').first())"
```

若单篇 JRA 详情页结构异常，预期行为是跳过该篇、继续处理同轮其他新闻，并在 `last_crawl_message` / `CrawlJob.error_message` 中留下“跳过 N 条”摘要；列表页、网络或数据库异常仍按整轮失败排查。

## 赛事日历 / 年度赛事页运维

### 后台入口

- 业务后台：`/admin/race-events/`
- Django Admin 兜底：`/django-admin/stable/raceevent/`
- 前台赛事日历：`/races/`
- 前台年度赛事详情：`/races/<year>/<slug>/`

### CSV 种子导入

样例文件：

```bash
server/stable/data/race_events_seed_sample.csv
```

本地或生产容器内导入：

```bash
python manage.py import_race_events --csv server/stable/data/race_events_seed_sample.csv --dry-run
python manage.py import_race_events --csv server/stable/data/race_events_seed_sample.csv
```

CSV 导入只创建或更新 `RaceEvent` 与 `RaceEventAlias`，不会创建新闻，不会触发 QQ 推送。

### 候选资料抓取

指定网站或人工缓存的候选资料应先写入 JSON，再进入候选池：

```bash
python manage.py fetch_race_event_candidates --event-id <race_event_id> --source json --payload-file /path/to/candidate.json
```

候选资料只写入 `RaceEventDataCandidate`，不会自动覆盖公开字段。运营人员需要在 `/admin/race-events/<id>/` 中按模块应用。

### 赛中字段只读调研

赛中字段调研只记录 URL、样例和失败原因，不写入公开赛事状态或赛果：

```bash
python manage.py research_live_race_fields --url https://example.com/race-page
```

### 停用 / 回滚边界

- 前台可通过从导航移除 `/races/` 入口或把赛事 `visibility_status` 改为 `hidden` 临时下线。
- 候选抓取命令不应配置为常驻调度；如来源异常，停止执行命令即可。
- `RaceEvent` 数据不影响新闻抓取、翻译、自动发布或 QQ 推送主链路。
- 人工移除的 `ArticleRaceLink(status=removed)` 是保护记录，不应批量删除，否则自动关联可能重新出现。

## 2026-06-25 三个运营改造 change 合并、部署与归档

### 合并范围

- `codex/fix-crawl-freshness-and-health`：抓取新鲜度、JRA 日期解析、来源健康摘要和 netkeiba `00/16/26` 分错峰调度。
- `codex/add-selection-term-quick-add`：后台候选详情页 / 文章编辑台原文选区快速加入术语库。
- `codex/add-selection-term-quick-add` 后续提交：新增术语成功后的 15 秒一次性浮层，可点击后仅将该术语应用到当前文章已有中文字段。
- 注意：`fix-crawl-health-running-and-schedule-stagger` 是抓取 change 的后续返修 OpenSpec 目录，随抓取 change 一并归档。

### 部署前检查

- 服务器部署前 HEAD：`268100d`。
- 服务器工作树：干净。
- 外部导入锁：`ExternalDataImportLock.locked_by_run_id=None`。
- 最近外部导入 run：`run_id=120` 等均为 `paused`，没有运行中的长导入。

### 部署步骤与结果

- 本地发布分支从 `origin/main` 合并两个代码分支后推送到 `main`，合并后提交为 `7f54f13`。
- 部署前备份 `.env`：`.env.backup.three-changes-20260625_003714`。
- 服务器 `/opt/umanewsbot` 执行 `git pull --ff-only origin main`，从 `268100d` 更新到 `7f54f13`。
- 执行 `bash ./deploy_lowcost.sh`，重建 `web / worker / beat`，`db / redis / nginx` 保持运行。
- 迁移结果：`No migrations to apply`。
- `collectstatic` 结果：`0 static files copied`，`360 post-processed`。
- 容器状态：`web` healthy，`db / redis` healthy，`worker / beat` running，`nginx` running。
- 验证：
  - `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check`：通过。
  - `http://127.0.0.1/healthz/`：`200`。
  - `http://127.0.0.1/`：`200`。
  - 运行态调度确认：`crawl-netkeiba-latest-hourly=00`，`crawl-netkeiba-access=16`，`crawl-netkeiba-attention=26`，三者 `crawl_interval_minutes=60`。

### 归档结果

- `openspec/changes/archive/2026-06-24-fix-crawl-freshness-and-jra-date-parse/`
- `openspec/changes/archive/2026-06-24-fix-crawl-health-running-and-schedule-stagger/`
- `openspec/changes/archive/2026-06-24-add-selection-term-quick-add/`
- `openspec/changes/archive/2026-06-24-reapply-terms-after-quick-add/`
- 正式规格已同步：
  - `openspec/specs/crawl-freshness-and-source-health/spec.md`
  - `openspec/specs/termbase-and-race-priority/spec.md`
- 归档后 `openspec validate --all` 通过。

### 后续观察

- 抓取错峰的“连续小时自然生成 `CrawlJob`”仍需等待调度运行后确认；本次已确认代码和运行时 Celery Beat 配置加载为 `00/16/26` 分。
- 如外部马名数据导入重新启动，继续遵守“导入期间不执行 `git pull / build / up / deploy_lowcost.sh`”的互斥规则。

## 2026-06-26 国际赛马资讯扩展部署

### 部署前检查

- 本地提交 `5865e58` 已推送到 `main`，分支 `codex/expand-international-racing-coverage` 保留远端备查。
- 本地验证通过：
  - `DB_ENGINE=sqlite ... server/manage.py check`
  - `DB_ENGINE=sqlite ... server/manage.py makemigrations --check --dry-run`
  - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true ... server/manage.py test stable --noinput`：241 项通过
  - `openspec validate expand-international-racing-coverage --strict`
  - `openspec validate --all`
  - `git diff --check`
- 生产部署前发现 `/opt/umanewsbot/imports/run_horse_import_202504_to_202406_20260626_083946.sh` 正在连续执行 netkeiba 外部马名导入。已等待当前批次完成并确认 `ExternalDataImportLock.locked_by_run_id=None` 后再部署；外层导入脚本已停止，避免继续自动开下一批。

### 部署步骤与结果

- 部署前服务器 HEAD：`2f0c35c`。
- 部署前备份 `.env`：`.env.backup.international-coverage-20260626_103923`。
- 服务器 `/opt/umanewsbot` 执行 `git pull --ff-only origin main`，从 `2f0c35c` 更新到 `5865e58`。
- 执行 `bash ./deploy_lowcost.sh`，重建 `web / worker / beat`，`db / redis / nginx` 保持运行。
- 迁移状态：`stable.0011_remove_termcandidate_uq_term_candidate_type_normalized_and_more`、`0012_termalias`、`0013_alter_newsarticle_source_site_and_more` 均已应用。
- `collectstatic` 结果：`0 static files copied`，`129 unmodified`，`360 post-processed`。
- 容器状态：`web` healthy，`db / redis` healthy，`worker / beat` running，`nginx` running。
- 验证：
  - `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check`：通过。
  - `http://127.0.0.1/healthz/`：`200`。
  - `http://127.0.0.1/`：`200`。

### 来源灰度与首轮观察

- 部署后手动执行 `sync_builtin_sources()`，生产已创建 20 个内置来源。
- 已启用第一版来源：`Sponichi latest/access`、`HKJC Racing News`、`SCMP Racing`、`Sporting Life Racing`、`Sky Sports Racing latest/access`、`France Galop English News`、`TDN France keyword`、`TDN`、`Horse Racing Nation latest/access`。
- 生产 `probe_international_news_sources` 验证中，除 `BHA official` 返回 `403` 外，其余第一版来源均能解析真实样本；`BHA` 已停用，后续再评估是否需要换请求策略或放弃。
- 测试 QQ 群 `1026525240` 已配置允许 `japan / hong_kong / united_kingdom / france / united_states` 五个地区，继续沿用全局 `QQ_PUSH_SCOPE` / `QQ_PUSH_IMPORTANCE_STRATEGY`。
- 已手动触发 12 个新增来源抓取任务；首轮观察中 `Sponichi latest` 已完成并入库 `13` 篇新稿、`7` 篇重复稿，`Sponichi access` 与 `HKJC Racing News` 已开始执行，其他国际来源仍在 worker 队列中等待。

### 后续观察

- 继续查看 `/admin/sources/` 和 `CrawlJob`，确认 `HKJC / SCMP / Sporting Life / Sky / France Galop / TDN / Horse Racing Nation` 依次完成首轮抓取。
- 抽检英文稿的翻译、术语别名命中、外部马名识别、自动发布门禁和公开地区 tab。
- 等自然公开/榜单提升后观察 QQ 测试群是否按地区配置推送；如刷屏或质量不稳，优先停用单个 `NewsSource` 或调整测试群 `allowed_regions`，不需要回滚代码。

## 自动化运营 MVP 部署与验证

### 关键环境变量

自动化能力通过 `.env` 控制，建议生产首次部署时先关闭：

```bash
AUTOMATION_ENABLED=false
AUTO_REVIEW_THRESHOLD=75
MANUAL_REVIEW_THRESHOLD=45
AUTO_REWRITE_ENABLED=false
AUTO_PUBLISH_CONTENT_SOURCE=base_translation
HIGH_VALUE_SOURCE_RULES=netkeiba:access,netkeiba:attention
HIGH_VALUE_WARNING_SCORE_THRESHOLD=90
AUTO_DUPLICATE_LOOKBACK_DAYS=7
AUTO_DUPLICATE_HIGH_THRESHOLD=0.86
AUTO_DUPLICATE_REVIEW_THRESHOLD=0.72
AUTO_PUBLISH_BATCH_LIMIT=4
AUTO_PUBLISH_PEAK_BATCH_LIMIT=10
AUTO_PUBLISH_PEAK_DAY_OF_WEEK=6
AUTO_PUBLISH_PEAK_START_HOUR=13
AUTO_PUBLISH_PEAK_END_HOUR=16
AUTO_PUBLISH_INTERVAL_MINUTES=15
REWRITE_CONFIDENCE_MIN=60
AUTO_PUBLISH_REQUIRE_COVER=false
REWRITE_PROVIDER=fallback
REWRITE_MODEL=deepseek-ai/DeepSeek-V3
REWRITE_MAX_TOKENS=2600
REWRITE_TIMEOUT_SECONDS=90
AUTOMATION_ENABLE_EMAIL=false
AUTOMATION_NOTIFY_EMAILS=
AUTOMATION_WARNING_EMAIL_ENABLED=true
AUTOMATION_WARNING_NOTIFY_EMAILS=754652181@qq.com
AUTOMATION_WARNING_EMAIL_DEDUP_HOURS=24
```

`refine-automation-publish-gates` 实施后，短期建议保持 `AUTO_REWRITE_ENABLED=false` 和 `AUTO_PUBLISH_CONTENT_SOURCE=base_translation`，先用基准翻译稿跑自动发布门禁。真实恢复 AI 改写时，按现有 OpenAI-compatible / SiliconFlow 配置补齐 Key，将 `AUTO_REWRITE_ENABLED=true`，并将 `AUTO_PUBLISH_CONTENT_SOURCE=rewrite`、`REWRITE_PROVIDER` 设置为对应 provider。

### 部署步骤

```bash
cd /opt/umanewsbot
cp .env .env.backup.$(date +%Y%m%d_%H%M%S)
git pull origin main
docker compose -f docker-compose.prod.lowcost.yml build web worker beat
docker compose -f docker-compose.prod.lowcost.yml up -d
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py migrate
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py check
```

如生产使用标准 RDS 方案，将 compose 文件替换为 `docker-compose.prod.yml`。

### 验证自动化字段与迁移

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.models import NewsArticle, AutomationLog, NotificationLog; print(NewsArticle.objects.count(), AutomationLog.objects.count(), NotificationLog.objects.count())"
```

验证门禁字段、重复状态和普通词种子：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.models import NewsArticle, TermEntry, WorkflowStatus; print(hasattr(WorkflowStatus, 'DUPLICATE'), NewsArticle.objects.exclude(gate_issues=[]).count(), TermEntry.objects.filter(notes__icontains='non_horse_common_word').count())"
```

### 灰度启用自动化

先把 `.env` 中 `AUTOMATION_ENABLED` 改为 `true`，再重启相关容器：

```bash
docker compose -f docker-compose.prod.lowcost.yml up -d web worker beat
docker logs --tail=120 umanewsbot-worker-1
docker logs --tail=120 umanewsbot-beat-1
```

### 手动触发单篇自动化验证

进入后台候选新闻详情页，点击“重新自动化处理”；或在服务器执行：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.tasks import process_article_automation_task; process_article_automation_task.delay(ARTICLE_ID)"
```

将 `ARTICLE_ID` 替换为已翻译文章 ID。

自动化门禁优化上线后，单篇验证重点查看：

- 后台候选详情页是否展示 blocker / warning / info。
- `warning` 是否仍允许文章进入 `automation_status=publish_ready`。
- 高度重复文章是否进入 `workflow_status=duplicate`。
- 中等相似文章是否转入 `workflow_status=pending_review`。
- 高价值来源文章是否在评分阶段放行，但不绕过 blocker。

### 自动发布批次验证

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.tasks import auto_publish_batch_task; print(auto_publish_batch_task.delay(limit=1))"
docker logs --tail=120 umanewsbot-worker-1
```

验证后台“已发布内容”列表、前台首页和文章详情页是否出现自动发布稿。

### 自动发布批量规则验证

生产默认规则：

- 常规时段：每 15 分钟最多自动发布 4 篇
- 每周日北京时间 13:00-16:00：每 15 分钟最多自动发布 10 篇

检查运行时配置：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web sh -c 'env | grep -E "^(AUTO_PUBLISH_BATCH_LIMIT|AUTO_PUBLISH_PEAK_BATCH_LIMIT|AUTO_PUBLISH_PEAK_DAY_OF_WEEK|AUTO_PUBLISH_PEAK_START_HOUR|AUTO_PUBLISH_PEAK_END_HOUR|AUTO_PUBLISH_INTERVAL_MINUTES)="'
```

检查任务按当前时间解析出的批量上限：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.tasks import _resolve_auto_publish_batch_limit; print(_resolve_auto_publish_batch_limit())"
```

### 异常通知验证

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.tasks import send_notification_task; send_notification_task.delay('rewrite_failed', {'title': '通知测试', 'article_id': 1})"
```

如果邮件未启用，后台日志中应出现 `NotificationLog(status=skipped, channel=email)`；如果邮件已启用，应出现 `sent` 或具体失败原因。

### 高价值 warning 邮件验证

`warning` 初期不阻断自动发布，但高价值文章出现 warning 时应发送或跳过并留痕：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.models import NotificationLog; print(NotificationLog.objects.filter(type='high_value_warning').order_by('-created_at').values('status','target','error_message')[:5])"
```

如果 `AUTOMATION_WARNING_EMAIL_ENABLED=true` 但没有配置 `AUTOMATION_WARNING_NOTIFY_EMAILS`，应看到 `status=skipped` 且自动发布不被阻断。同一文章同一 warning 组合 24 小时内重复触发时，也应记录 skipped 去重日志。

### 2026-06-24 自动发布门禁优化生产上线结果

- 部署 PR：#4 `[codex] refine automation publish gates`。
- 生产提交：`42a4622`。
- 部署前 `.env` 备份：`.env.backup.refine-automation-20260624_013323`。
- 生产灰度策略：`AUTO_REWRITE_ENABLED=false`，`AUTO_PUBLISH_CONTENT_SOURCE=base_translation`，高价值 warning 邮件发送到 `754652181@qq.com`。
- 迁移：`stable.0009_automation_publish_gates` 已应用。
- 健康检查：`http://umafans.run/healthz/` 与 `/` 均返回 `200`，`web` 容器 healthy。
- 验收查询：`WorkflowStatus.DUPLICATE=True`，首批非马名普通词种子数量 `14`，`python manage.py check` 通过。
- 部署日志曾出现一次字段已存在异常，原因为容器启动迁移与手工迁移并发；后续 `showmigrations`、`check` 和健康检查均正常。

### 自动化排障顺序

1. 先查 `.env` 中 `AUTOMATION_ENABLED`、`AUTO_REWRITE_ENABLED`、`AUTO_PUBLISH_CONTENT_SOURCE`、阈值、邮件配置和模型配置
2. 再查 `beat` 是否加载 `auto-publish-batch` 与 `detect-automation-anomalies`
3. 查看 `worker` 日志是否有评分、改写、校验、发布异常
4. 后台文章详情页查看 `AutomationLog`
5. 后台操作日志页查看 `NotificationLog`
6. 如果内容质量不稳，先关闭 `AUTOMATION_ENABLED`，不要急着回滚代码

## QQ 群自动推送部署与验证

### 关键环境变量

自动 QQ 推送默认关闭，生产首次部署建议保持：

```bash
QQ_PUSH_ENABLED=false
QQ_PUSH_SCOPE=high_value_only
QQ_PUSH_IMPORTANCE_STRATEGY=ranked
QQ_PUSH_MAX_ATTEMPTS=3
QQ_PUSH_URL_CHECK_TIMEOUT_SECONDS=5
QQ_PUSH_SENDING_STALE_SECONDS=600
QQ_PUSH_MIN_INTERVAL_SECONDS=60
ONEBOT_BASE_URL=http://onebot:3000
ONEBOT_ACCESS_TOKEN=
ONEBOT_TIMEOUT_SECONDS=30
```

`QQ_PUSH_SCOPE` 支持：

- `high_value_only`：默认，仅推重点新闻
- `all_public`：推所有公开 URL 可访问且无 blocker 的已发布文章

`QQ_PUSH_IMPORTANCE_STRATEGY=ranked` 是本期唯一支持的重点新闻口径：仅 `netkeiba:access` 与 `netkeiba:attention` 文章会被视为重点新闻。

### 部署步骤

```bash
cd /opt/umanewsbot
cp .env .env.backup.$(date +%Y%m%d_%H%M%S)
git pull origin main
docker compose -f docker-compose.prod.lowcost.yml build web worker beat
docker compose -f docker-compose.prod.lowcost.yml up -d
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py migrate
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py check
```

### 配置群目标

进入 Django Admin：

```text
/django-admin/stable/pushtarget/
```

配置 `name`、`group_id`，并将测试群设为 `is_active=true`。自动推送只看 `is_active`，`is_default` 仅用于手动推送默认群。

### OneBot 网关安全边界

OneBot API 不得公网裸露。推荐 Docker 内网访问：

```env
ONEBOT_BASE_URL=http://onebot:3000
```

如果临时映射到宿主机，只允许：

```yaml
ports:
  - "127.0.0.1:3000:3000"
```

不要使用公网 `0.0.0.0:3000:3000`。

### 灰度启用

确认测试群和 OneBot 网关可用后，把 `.env` 改为：

```bash
QQ_PUSH_ENABLED=true
QQ_PUSH_SCOPE=high_value_only
QQ_PUSH_IMPORTANCE_STRATEGY=ranked
```

重启 worker / beat：

```bash
docker compose -f docker-compose.prod.lowcost.yml up -d worker beat
```

### 验收命令

检查配置：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec worker sh -c 'env | grep -E "^(QQ_PUSH_ENABLED|QQ_PUSH_SCOPE|QQ_PUSH_IMPORTANCE_STRATEGY|QQ_PUSH_MAX_ATTEMPTS|QQ_PUSH_URL_CHECK_TIMEOUT_SECONDS|QQ_PUSH_SENDING_STALE_SECONDS|QQ_PUSH_MIN_INTERVAL_SECONDS|ONEBOT_BASE_URL|ONEBOT_TIMEOUT_SECONDS)="'
```

查看交付记录：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.models import QQPushDelivery; print(QQPushDelivery.objects.order_by('-created_at').values('id','article_id','target_id','status','attempt_count','last_error_type')[:10])"
```

检查 OneBot 登录状态：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py shell -c "from stable.services.onebot import BotPusher; print(BotPusher().is_online())"
```

预期返回 `(True, '')`。若返回 `onebot_offline` 或 `onebot_status_check_failed`，自动推送会暂停真实发送并记录错误摘要，不会调用 `/send_group_msg`，也不会增加 `QQPushDelivery.attempt_count`。

查看 worker 日志：

```bash
docker logs --tail=160 umanewsbot-worker-1
```

抽检公开文章 ID URL：

```bash
ARTICLE_ID=$(docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py shell -c "from stable.models import NewsArticle, WorkflowStatus; article = NewsArticle.objects.filter(workflow_status=WorkflowStatus.PUBLISHED, published_to_web_at__isnull=False).order_by('-published_to_web_at', '-id').first(); print(article.id if article else '')")
curl -I "http://127.0.0.1/news/${ARTICLE_ID}/"
```

预期 `/news/<article_id>/` 返回 `200`；非纯数字旧 `/news/<slug>/` 若能查到已发布文章，应返回 `302` 并跳转到对应 ID URL。QQ 自动推送消息中的 `阅读全文` 链接同样应为 `SITE_URL/news/<article_id>/`。

后台排查入口：

```text
/django-admin/stable/qqpushdelivery/
```

### 停用和回滚

最快停用方式：

```bash
QQ_PUSH_ENABLED=false
docker compose -f docker-compose.prod.lowcost.yml up -d worker beat
```

停用自动 QQ 推送不会影响公开网站、自动发布或后台手动推送。若 OneBot 网关异常，可先停掉 OneBot 容器或把目标群 `is_active=false`。

如果 NapCat 日志出现“登录态已失效，请重新登录”或 `/get_status` 返回 `online=false`，先按上面的停用方式暂停自动推送，再通过 NapCat WebUI 或新的登录二维码完成 QQ 重新登录。登录后必须重新执行 OneBot 在线检查、测试群短消息和 worker 环境变量检查，再恢复 `QQ_PUSH_ENABLED=true`。

## 专有术语候选发现灰度部署

## 正式术语库恢复与赛事等级修复部署

### 适用场景

用于修复正式术语库缺失、马名或比赛名翻译未命中、赛事等级识别不足导致自动评分偏低的问题。本流程覆盖：

- 正式术语 `race_grade` 字段迁移
- 术语候选池基础内容字段迁移
- 正式术语种子数据 dry-run 与导入
- 执行日 0:00 后候选新闻池批量验收

### 部署前备份

```bash
cd /opt/umanewsbot
cp .env .env.backup.$(date +%Y%m%d_%H%M%S)
mkdir -p backups
docker compose -f docker-compose.prod.lowcost.yml exec db pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" > backups/pre-termbase-race-grade-$(date +%Y%m%d_%H%M%S).sql
```

如生产使用标准 Compose 文件，将 `docker-compose.prod.lowcost.yml` 替换为 `docker-compose.prod.yml`。

### 部署与迁移

```bash
cd /opt/umanewsbot
git pull origin main
docker compose -f docker-compose.prod.lowcost.yml build web worker beat
docker compose -f docker-compose.prod.lowcost.yml up -d web worker beat
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py migrate
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py check
```

### 术语导入 dry-run

默认种子文件位于容器内 `server/stable/data/terms_seed.csv`。先执行预检：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py import_terms --dry-run
```

确认输出中的错误数量为 `0`。若生产已经存在部分术语，默认 `upsert` 会显示更新数量；如需严格新增模式，可显式执行：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py import_terms --dry-run --mode create
```

### 正式导入术语

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py import_terms
```

如需导入本地整理好的 CSV，先上传到服务器，再复制进 `web` 容器可见路径后执行 dry-run 与正式导入：

```bash
cd /opt/umanewsbot
mkdir -p imports/terms-<批次>
scp <本地CSV> root@<服务器IP>:/opt/umanewsbot/imports/terms-<批次>/
docker compose -f docker-compose.prod.lowcost.yml exec -T web mkdir -p /tmp/terms
docker cp imports/terms-<批次>/<文件名>.csv umanewsbot-web-1:/tmp/terms/
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_terms /tmp/terms/<文件名>.csv --dry-run
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_terms /tmp/terms/<文件名>.csv
```

## 术语种子数据准备部署与验证

### 适用场景

用于上线 `prepare_termbase_seed_data` 管理命令和 HKJC/WP Stud 术语种子候选生成能力。该能力只生成本地审核文件，不直接写入 `TermEntry`、`TermAlias`、`TermCandidate`、`ExternalHorse` 或 `ExternalHorseAlias`。

### 部署步骤

本能力新增 Python 依赖，生产部署必须重建 `web / worker / beat` 镜像：

```bash
cd /opt/umanewsbot
cp .env .env.backup.termbase-seed-$(date +%Y%m%d_%H%M%S)
git pull --ff-only origin main
docker compose -f docker-compose.prod.lowcost.yml build web worker beat
docker compose -f docker-compose.prod.lowcost.yml up -d web worker beat
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py migrate --noinput
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check
```

### 生产 smoke 验证

先使用内置 fixture 生成一批不触网的候选文件：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py prepare_termbase_seed_data \
  --source hkjc \
  --source wpstud \
  --output-dir /tmp/termbase_seed_smoke
```

预期结果：

- `seed_candidates.csv`、`seed_conflicts.csv`、`summary.json` 均生成。
- 内置 fixture smoke 应生成 `10` 条候选和 `1` 条冲突。
- 命令不修改正式术语库、候选池、外部马名索引，也不派发翻译、自动发布或 QQ 推送任务。

### 本次执行记录（2026-07-04）

- 服务器 `/opt/umanewsbot` 从 `4323d32` 快进到 `e81733f`。
- 部署前备份 `.env`：`.env.backup.termbase-seed-20260704_012005`。
- 本次新增依赖 `opencc-python-reimplemented==0.1.7`，已重建并重启 `web / worker / beat`。
- 迁移结果：`No migrations to apply`。
- `python manage.py check`：通过，`0` issues。
- 生产 smoke：`candidate_count=10`、`conflict_count=1`、`incomplete=false`、`dry_run_error_count=0`，首条候选 `BEAUTY GENERATION`，末条候选 `ディープインパクト`。
- 健康检查：`http://127.0.0.1/healthz/` 与 `http://umafans.run/healthz/` 均返回 `200`。
- 本次只上线种子准备命令和审核文件生成能力，未导入正式术语，未写 `TermEntry`、`TermAlias`、`TermCandidate` 或外部马名索引。

### 第一批正式术语导入记录（2026-07-04）

- 导入文件：`/opt/umanewsbot/imports/termbase-seed-fixture-review-20260704_024950/seed_candidates.csv`。
- 数据库备份：`backups/db/pre-termbase-seed-import-20260704_030722.sql.gz`，已通过 `gzip -t`。
- dry-run：总计 `10` 条，新增 `8` 条，更新 `2` 条，错误 `0` 条。
- 正式导入：总计 `10` 条，新增 `8` 条，更新 `2` 条，跳过 `0` 条。
- 导入后计数：`TermEntry=2062`、`TermAlias=2068`；按原文语言分布为 `en=8`、`ja=2054`。
- 新增英文术语：`BEAUTY GENERATION`、`KA YING RISING`、`ROMANTIC WARRIOR`、`Hong Kong Cup`、`Zac Purton`、`John Size`、`Sha Tin`、`Declared Starter`。
- 首次导入时本批地区证据只保留在 `notes` 的 `region=hk`，未写入 `TermEntry.racing_region`；随后已执行地区补写 upsert。
- 地区补写备份：`backups/db/pre-termbase-seed-region-upsert-20260704_031950.sql.gz`。
- 地区补写注意：`racing_region` 必须使用模型合法值，例如 `hong_kong`、`japan`，不能使用短码 `hk`、`jp`。短码版本 dry-run 会被“地区不合法”阻断且不会写库。
- 地区补写结果：改用 `hong_kong/japan` 后 dry-run 为总计 `10` 条、更新 `10` 条、错误 `0` 条；正式 upsert 为更新 `10` 条、跳过 `0` 条。补写后分布为 `en/hong_kong=8`、`ja/japan=2`、既有旧日文术语空地区 `2052`。
- 导入后 `http://umafans.run/healthz/` 返回 `200`。

### WP Stud 第一批全量审核候选记录（2026-07-04）

- 本地审核目录：`runtime/termbase_seed/wpstud-full-review-20260704/`。
- 审核文件：`seed_candidates.csv`、`seed_candidates_with_region.csv`、`seed_conflicts.csv`、`summary.json`。
- 生成结果：候选 `210` 条、冲突 `0` 条、`incomplete=false`；全部为 `term_type=horse`、`source_language=ja`、`source_tier=community`、`requires_review=true`，中文译名已简体化。
- 带地区导入候选：`seed_candidates_with_region.csv`，统一设置 `racing_region=hong_kong`，用于描述香港或海外来港赛马候选。
- 生产导入文件：`/opt/umanewsbot/imports/wpstud-full-review-20260704/seed_candidates_with_region.csv`。
- 生产 dry-run 结果：总计 `210` 条，新增 `210` 条，更新 `0` 条，错误 `0` 条。
- 数据库备份：`backups/db/pre-hkjc-wpstud-term-import-20260704_182155.sql.gz`，已通过 `gzip -t`。
- 正式导入结果：总计 `210` 条，新增 `210` 条，更新 `0` 条，跳过 `0` 条。
- 当前状态：已正式导入。本批是社区来源，后续若发现与 HKJC 官方译名冲突，应以 HKJC 作为主译名，WP Stud 作为别名或证据处理。
- HKJC 后续注意：真实 HKJC 页面当前可访问并返回 `200`；本地已补专用抽取路径，从 `selecthorse` 发现字母页、从字母页拿 `horseid + 英文名`，再抓繁中马匹详情页对齐中文名。小批命令应使用 `--limit-horses` 控制马匹详情页数量，并继续用 `--max-requests` 做硬上限。

### HKJC 真实页面术语种子小批 smoke（2026-07-04）

本地真实 smoke 命令：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true .venv/bin/python server/manage.py prepare_termbase_seed_data \
  --source hkjc \
  --allow-network \
  --limit-pages 1 \
  --limit-horses 3 \
  --max-requests 10 \
  --request-interval-seconds 0 \
  --timeout-seconds 20 \
  --output-dir runtime/termbase_seed/hkjc-live-smoke-20260704
```

结果：

- `candidate_count=3`、`conflict_count=0`、`request_count=5`、`incomplete=false`。
- 请求链路为 `selecthorse -> selecthorsebychar?ordertype=A -> 3` 个 `zh-hk/local/information/horse?horseid=...` 详情页，全部返回 `200`。
- 生成样例：`AERIS NOVA -> 风再起时`、`AERODYNAMICS -> 友莹光`、`AWESOME FLUKE -> 非惟侥幸`。
- 本次只生成本地审核文件，未写正式术语库。生产执行时仍应先低频、带 `--limit-horses`，并在审核 CSV 后再走 `import_terms --dry-run` 与正式导入。

### HKJC 第一批正式候选抓取记录（2026-07-04）

本地低频命令：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true .venv/bin/python server/manage.py prepare_termbase_seed_data \
  --source hkjc \
  --allow-network \
  --limit-pages 1 \
  --limit-horses 100 \
  --max-requests 130 \
  --request-interval-seconds 2 \
  --timeout-seconds 25 \
  --output-dir runtime/termbase_seed/hkjc-formal-review-20260704_100horses
```

结果：

- 审核目录：`runtime/termbase_seed/hkjc-formal-review-20260704_100horses/`。
- `seed_candidates.csv` 已直接包含 `racing_region` 列，HKJC 候选使用模型合法值 `hong_kong`。
- `candidate_count=100`、`conflict_count=0`、`request_count=103`、`incomplete=false`。
- 请求链路覆盖 `selecthorse`、`selecthorsebychar?ordertype=A/B` 和 `100` 个 `zh-hk/local/information/horse?horseid=...` 详情页，全部返回 `200`。
- 候选分布：`horse=100`、`source_language=en`、`racing_region=hong_kong`、`source_tier=official`、`requires_review=false`。
- 抽检样例：`A AMERIC TE SPECSO -> 有财有势`、`A TIME FOR US -> 开心孖宝`、`ABSOLUTE AWAKENED -> 活力精神`。
- 临时 SQLite 迁移库导入预检：`import_terms --dry-run` 显示总计 `100` 条、新增 `100` 条、更新 `0` 条、错误 `0` 条。
- 当前状态：本批尚未导入生产正式术语库，也尚未部署 HKJC 抽取代码到生产。

### HKJC 主审核候选扩展批次（2026-07-04）

用户要求“多来一些，一起审核”后，已生成更大的 HKJC 主审核文件；该文件覆盖前一份 `100` 条小批，审核时优先使用本批：

```bash
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true .venv/bin/python server/manage.py prepare_termbase_seed_data \
  --source hkjc \
  --allow-network \
  --limit-pages 1 \
  --limit-horses 500 \
  --max-requests 560 \
  --request-interval-seconds 1.5 \
  --timeout-seconds 25 \
  --output-dir runtime/termbase_seed/hkjc-formal-review-20260704_500horses
```

结果：

- 审核目录：`runtime/termbase_seed/hkjc-formal-review-20260704_500horses/`。
- `candidate_count=500`、`conflict_count=0`、`request_count=509`、`incomplete=false`。
- 所有请求均返回 `200`，无 `failures`。
- CSV 抽检：`500` 条唯一英文马名，全部为 `term_type=horse`、`source_language=en`、`racing_region=hong_kong`、`source_tier=official`、`requires_review=false`。
- 抽检样例：`A AMERIC TE SPECSO -> 有财有势`、`A TIME FOR US -> 开心孖宝`、`ABSOLUTE AWAKENED -> 活力精神`；末段覆盖到 `HYMNBOOK -> 北斗福星`。
- 生产 dry-run：总计 `500` 条，新增 `500` 条，更新 `0` 条，错误 `0` 条。
- 数据库备份：`backups/db/pre-hkjc-wpstud-term-import-20260704_182155.sql.gz`，已通过 `gzip -t`。
- 正式导入结果：总计 `500` 条，新增 `500` 条，更新 `0` 条，跳过 `0` 条。

### HKJC 本地马 A-Z 字母拆批导入记录（2026-07-04）

全量无 checkpoint 抓取运行过久后，已新增 `--hkjc-letter` 参数并改为按 A-Z 字母拆批。每个字母段均使用如下模式：

```bash
DB_ENGINE=sqlite SQLITE_DB_PATH=/tmp/umanews_hkjc_letter.sqlite3 CELERY_TASK_ALWAYS_EAGER=true \
  .venv/bin/python server/manage.py prepare_termbase_seed_data \
  --source hkjc \
  --allow-network \
  --limit-pages 1 \
  --hkjc-letter <A-Z> \
  --max-requests 600 \
  --request-interval-seconds 0.15 \
  --timeout-seconds 20 \
  --output-dir runtime/termbase_seed/hkjc-formal-review-20260704_letter_<A-Z>
```

字母段生成结果：

- `A=60`、`B=54`、`C=103`、`D=43`、`E=32`、`F=70`、`G=87`、`H=56`
- `I=28`、`J=23`
- `K=42`、`L=68`、`M=84`、`N=33`、`O=12`、`P=72`、`Q=7`、`R=52`、`S=162`、`T=70`、`U=5`、`V=32`、`W=44`、`X=0`、`Y=14`、`Z=4`
- 所有字母段均为 `incomplete=false`、`failures=0`。

生产导入：

- `I` 批：生产 dry-run 总计 `28`、新增 `28`、错误 `0`；备份 `backups/db/pre-hkjc-letter-I-term-import-20260704_185212.sql.gz`；正式导入新增 `28`。
- `J` 批：生产 dry-run 总计 `23`、新增 `23`、错误 `0`；备份 `backups/db/pre-hkjc-letter-J-term-import-20260704_185400.sql.gz`；正式导入新增 `23`。
- `K-Z` 合并批：生产 dry-run 总计 `701`、新增 `699`、更新 `2`、错误 `0`；备份 `backups/db/pre-hkjc-letters-K-Z-term-import-20260704_191425.sql.gz`；正式导入新增 `699`、更新 `2`。
- `A-H` 合并复跑批：生产 dry-run 总计 `505`、新增 `5`、更新 `500`、错误 `0`；备份 `backups/db/pre-hkjc-letters-A-H-term-import-20260704_192843.sql.gz`；正式导入新增 `5`、更新 `500`。

导入后生产计数：`TermEntry=3527`、`TermAlias=3743`；`source_language=en/racing_region=hong_kong` 合计 `1263` 条，其中 HKJC 当前本地马英文术语 `1258` 条。`http://umafans.run/healthz/` 返回 `200`。

### HKJC 本地赛果回溯术语导入记录（2026-07-04）

本轮新增 HKJC 本地赛果术语抽取参数，用于按日期范围抓取 `en-us` / `zh-hk` 赛果页并对齐输出 `horse`、`jockey` 和 `race` 候选：

```bash
.venv/bin/python server/manage.py prepare_termbase_seed_data \
  --source hkjc \
  --allow-network \
  --limit-pages 0 \
  --hkjc-skip-horse-details \
  --hkjc-local-results-start-date 2024-01-01 \
  --hkjc-local-results-end-date 2024-01-31 \
  --max-requests 260 \
  --request-interval-seconds 0.2 \
  --timeout-seconds 20 \
  --output-dir runtime/termbase_seed/hkjc-local-results-202401
```

实现细节：

- HKJC 赛日首页通常直接显示第 1 场，只给第 2 场之后的链接；生成器会根据同一赛日同一马场链接自动补抓 `RaceNo=1`。
- HKJC 下拉列表不会稳定覆盖 2024 年初旧赛日；生成器会把 landing 赛日与日期范围逐日探测合并去重，以支持 2024-01-01 起回溯。
- 补历史赛果时应使用 `--limit-pages 0 --hkjc-skip-horse-details`，避免每个月重复抓取当前本地马详情页。
- 单次网络异常会重试一次；最终失败才写入 `failures` 并标记 `incomplete=true`。
- 若 HKJC 双语页面都能访问但没有赛果主体表，生成器记录为 `skipped_races/local_result_not_available`，不导入空数据，也不单独阻断整月。

生产导入：

- `2024-01`：原始批次 `runtime/termbase_seed/hkjc-local-results-202401/` 因 `2024-01-24 ST Race 1` 繁中页一次超时而 `incomplete=true`；单日重跑 `runtime/termbase_seed/hkjc-local-results-20240124-retry/` 成功后，合并去重为 `runtime/termbase_seed/hkjc-local-results-202401-complete/seed_candidates.csv`。合并候选 `864` 条（`horse=761`、`race=79`、`jockey=24`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202401-complete/seed_candidates.csv`；dry-run 总计 `864`、新增 `710`、更新 `154`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202401-term-import-20260704_200627.sql.gz` 通过 `gzip -t`；正式导入新增 `710`、更新 `154`、跳过 `0`。
- `2024-02`：输出 `runtime/termbase_seed/hkjc-local-results-202402/seed_candidates.csv`，候选 `828` 条（`horse=736`、`race=68`、`jockey=24`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202402/seed_candidates.csv`；dry-run 总计 `828`、新增 `163`、更新 `665`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202402-term-import-20260704_201806.sql.gz` 通过 `gzip -t`；正式导入新增 `163`、更新 `665`、跳过 `0`。
- `2024-03`：输出 `runtime/termbase_seed/hkjc-local-results-202403/seed_candidates.csv`，候选 `883` 条（`horse=777`、`race=79`、`jockey=27`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202403/seed_candidates.csv`；dry-run 总计 `883`、新增 `137`、更新 `746`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202403-term-import-20260704_202942.sql.gz` 通过 `gzip -t`；正式导入新增 `137`、更新 `746`、跳过 `0`。
- `2024-04`：输出 `runtime/termbase_seed/hkjc-local-results-202404/seed_candidates.csv`，候选 `839` 条（`horse=740`、`race=68`、`jockey=31`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202404/seed_candidates.csv`；dry-run 总计 `839`、新增 `126`、更新 `713`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202404-term-import-20260704_204225.sql.gz` 通过 `gzip -t`；正式导入新增 `126`、更新 `713`、跳过 `0`。
- `2024-05`：输出 `runtime/termbase_seed/hkjc-local-results-202405/seed_candidates.csv`，候选 `842` 条（`horse=740`、`race=78`、`jockey=24`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202405/seed_candidates.csv`；dry-run 总计 `842`、新增 `113`、更新 `729`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202405-term-import-20260704_205324.sql.gz` 通过 `gzip -t`；正式导入新增 `113`、更新 `729`、跳过 `0`。
- `2024-06`：输出 `runtime/termbase_seed/hkjc-local-results-202406/seed_candidates.csv`，候选 `782` 条（`horse=697`、`race=62`、`jockey=23`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202406/seed_candidates.csv`；dry-run 总计 `782`、新增 `92`、更新 `690`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202406-term-import-20260704_210352.sql.gz` 通过 `gzip -t`；正式导入新增 `92`、更新 `690`、跳过 `0`。
- `2024-07`：输出 `runtime/termbase_seed/hkjc-local-results-202407/seed_candidates.csv`，候选 `647` 条（`horse=575`、`race=49`、`jockey=23`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202407/seed_candidates.csv`；dry-run 总计 `647`、新增 `74`、更新 `573`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202407-term-import-20260704_211425.sql.gz` 通过 `gzip -t`；正式导入新增 `74`、更新 `573`、跳过 `0`。
- `2024-08`：输出 `runtime/termbase_seed/hkjc-local-results-202408/`，逐日扫描 `32` 个请求，候选 `0`、冲突 `0`、失败 `0`、`incomplete=false`；本月无需生产导入。
- `2024-09`：输出 `runtime/termbase_seed/hkjc-local-results-202409/seed_candidates.csv`，候选 `626` 条（`horse=549`、`race=54`、`jockey=23`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202409/seed_candidates.csv`；dry-run 总计 `626`、新增 `62`、更新 `564`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202409-term-import-20260704_213327.sql.gz` 通过 `gzip -t`；正式导入新增 `62`、更新 `564`、跳过 `0`。
- `2024-10`：输出 `runtime/termbase_seed/hkjc-local-results-202410/seed_candidates.csv`，候选 `834` 条（`horse=735`、`race=75`、`jockey=24`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202410/seed_candidates.csv`；dry-run 总计 `834`、新增 `104`、更新 `730`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202410-term-import-20260704_214522.sql.gz` 通过 `gzip -t`；正式导入新增 `104`、更新 `730`、跳过 `0`。
- `2024-11`：输出 `runtime/termbase_seed/hkjc-local-results-202411/seed_candidates.csv`，候选 `850` 条（`horse=757`、`race=69`、`jockey=24`）。首次生成时 `2024-11-13 HV Race 7-9` 页面返回双语空壳赛果页，修复后重跑记录为 `skipped_races/local_result_not_available` 且 `incomplete=false`；生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202411/seed_candidates.csv`；dry-run 总计 `850`、新增 `97`、更新 `753`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202411-term-import-20260704_221006.sql.gz` 通过 `gzip -t`；正式导入新增 `97`、更新 `753`、跳过 `0`。
- `2024-12`：输出 `runtime/termbase_seed/hkjc-local-results-202412/seed_candidates.csv`，候选 `957` 条（`horse=832`、`race=78`、`jockey=47`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202412/seed_candidates.csv`；dry-run 总计 `957`、新增 `135`、更新 `822`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202412-term-import-20260704_222551.sql.gz` 通过 `gzip -t`；正式导入新增 `135`、更新 `822`、跳过 `0`。
- `2025-01`：输出 `runtime/termbase_seed/hkjc-local-results-202501/seed_candidates.csv`，候选 `913` 条（`horse=804`、`race=78`、`jockey=31`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202501/seed_candidates.csv`；dry-run 总计 `913`、新增 `73`、更新 `840`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202501-term-import-20260704_224151.sql.gz` 通过 `gzip -t`；正式导入新增 `73`、更新 `840`、跳过 `0`。
- `2025-02`：输出 `runtime/termbase_seed/hkjc-local-results-202502/seed_candidates.csv`，候选 `794` 条（`horse=703`、`race=60`、`jockey=31`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202502/seed_candidates.csv`；dry-run 总计 `794`、新增 `38`、更新 `756`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202502-term-import-20260704_225443.sql.gz` 通过 `gzip -t`；正式导入新增 `38`、更新 `756`、跳过 `0`。
- `2025-03`：输出 `runtime/termbase_seed/hkjc-local-results-202503/seed_candidates.csv`，候选 `914` 条（`horse=803`、`race=78`、`jockey=33`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202503/seed_candidates.csv`；dry-run 总计 `914`、新增 `30`、更新 `884`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202503-term-import-20260704_231134.sql.gz` 通过 `gzip -t`；正式导入新增 `30`、更新 `884`、跳过 `0`。
- `2025-04`：输出 `runtime/termbase_seed/hkjc-local-results-202504/seed_candidates.csv`，候选 `893` 条（`horse=782`、`race=78`、`jockey=33`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202504/seed_candidates.csv`；dry-run 总计 `893`、新增 `58`、更新 `835`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202504-term-import-20260704_232559.sql.gz` 通过 `gzip -t`；正式导入新增 `58`、更新 `835`、跳过 `0`。
- `2025-05`：输出 `runtime/termbase_seed/hkjc-local-results-202505/seed_candidates.csv`，候选 `920` 条（`horse=816`、`race=79`、`jockey=25`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202505/seed_candidates.csv`；dry-run 总计 `920`、新增 `38`、更新 `882`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202505-term-import-20260704_234206.sql.gz` 通过 `gzip -t`；正式导入新增 `38`、更新 `882`、跳过 `0`。
- `2025-06`：输出 `runtime/termbase_seed/hkjc-local-results-202506/seed_candidates.csv`，候选 `826` 条（`horse=741`、`race=63`、`jockey=22`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202506/seed_candidates.csv`；dry-run 总计 `826`、新增 `44`、更新 `782`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202506-term-import-20260704_235659.sql.gz` 通过 `gzip -t`；正式导入新增 `44`、更新 `782`、跳过 `0`。
- `2025-07`：输出 `runtime/termbase_seed/hkjc-local-results-202507/seed_candidates.csv`，候选 `675` 条（`horse=603`、`race=49`、`jockey=23`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202507/seed_candidates.csv`；dry-run 总计 `675`、新增 `19`、更新 `656`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202507-term-import-20260705_000915.sql.gz` 通过 `gzip -t`；正式导入新增 `19`、更新 `656`、跳过 `0`。

`2025-08`：输出 `runtime/termbase_seed/hkjc-local-results-202508/`，逐日扫描请求 `32` 次，候选 `0`、冲突 `0`、失败 `0`、`incomplete=false`，无需导入。
- `2025-09`：输出 `runtime/termbase_seed/hkjc-local-results-202509/seed_candidates.csv`，候选 `632` 条（`horse=560`、`race=49`、`jockey=23`）。`2025-09-21 ST Race 9-10` 页面返回双语空壳赛果页，记录为 `skipped_races/local_result_not_available` 且 `incomplete=false`；生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202509/seed_candidates.csv`；dry-run 总计 `632`、新增 `17`、更新 `615`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202509-term-import-20260705_002604.sql.gz` 通过 `gzip -t`；正式导入新增 `17`、更新 `615`、跳过 `0`。
- `2025-10`：输出 `runtime/termbase_seed/hkjc-local-results-202510/seed_candidates.csv`，候选 `882` 条（`horse=786`、`race=73`、`jockey=23`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202510/seed_candidates.csv`；dry-run 总计 `882`、新增 `41`、更新 `841`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202510-term-import-20260705_004245.sql.gz` 通过 `gzip -t`；正式导入新增 `41`、更新 `841`、跳过 `0`。
- `2025-11`：输出 `runtime/termbase_seed/hkjc-local-results-202511/seed_candidates.csv`，候选 `933` 条（`horse=826`、`race=81`、`jockey=26`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202511/seed_candidates.csv`；dry-run 总计 `933`、新增 `45`、更新 `888`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202511-term-import-20260705_010022.sql.gz` 通过 `gzip -t`；正式导入新增 `45`、更新 `888`、跳过 `0`。
- `2025-12`：输出 `runtime/termbase_seed/hkjc-local-results-202512/seed_candidates.csv`，候选 `912` 条（`horse=803`、`race=68`、`jockey=41`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202512/seed_candidates.csv`；dry-run 总计 `912`、新增 `42`、更新 `870`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202512-term-import-20260705_011812.sql.gz` 通过 `gzip -t`；正式导入新增 `42`、更新 `870`、跳过 `0`。
- `2026-01`：输出 `runtime/termbase_seed/hkjc-local-results-202601/seed_candidates.csv`，候选 `978` 条（`horse=875`、`race=78`、`jockey=25`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202601/seed_candidates.csv`；dry-run 总计 `978`、新增 `28`、更新 `950`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202601-term-import-20260705_013522.sql.gz` 通过 `gzip -t`；正式导入新增 `28`、更新 `950`、跳过 `0`。
- `2026-02`：输出 `runtime/termbase_seed/hkjc-local-results-202602/seed_candidates.csv`，候选 `930` 条（`horse=836`、`race=69`、`jockey=25`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202602/seed_candidates.csv`；dry-run 总计 `930`、新增 `18`、更新 `912`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202602-term-import-20260705_015108.sql.gz` 通过 `gzip -t`；正式导入新增 `18`、更新 `912`、跳过 `0`。
- `2026-03`：输出 `runtime/termbase_seed/hkjc-local-results-202603/seed_candidates.csv`，候选 `944` 条（`horse=838`、`race=81`、`jockey=25`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202603/seed_candidates.csv`；dry-run 总计 `944`、新增 `18`、更新 `926`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202603-term-import-20260705_020814.sql.gz` 通过 `gzip -t`；正式导入新增 `18`、更新 `926`、跳过 `0`。
- `2026-04`：输出 `runtime/termbase_seed/hkjc-local-results-202604/seed_candidates.csv`，候选 `975` 条（`horse=859`、`race=83`、`jockey=33`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202604/seed_candidates.csv`；dry-run 总计 `975`、新增 `41`、更新 `934`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202604-term-import-20260705_022703.sql.gz` 通过 `gzip -t`；正式导入新增 `41`、更新 `934`、跳过 `0`。
- `2026-05`：输出 `runtime/termbase_seed/hkjc-local-results-202605/seed_candidates.csv`，候选 `979` 条（`horse=873`、`race=80`、`jockey=26`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202605/seed_candidates.csv`；dry-run 总计 `979`、新增 `33`、更新 `946`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202605-term-import-20260705_024451.sql.gz` 通过 `gzip -t`；正式导入新增 `33`、更新 `946`、跳过 `0`。
- `2026-06`：输出 `runtime/termbase_seed/hkjc-local-results-202606/seed_candidates.csv`，候选 `844` 条（`horse=757`、`race=63`、`jockey=24`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-202606/seed_candidates.csv`；dry-run 总计 `844`、新增 `20`、更新 `824`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-202606-term-import-20260705_025830.sql.gz` 通过 `gzip -t`；正式导入新增 `20`、更新 `824`、跳过 `0`。
- `2026-07-01` 至 `2026-07-04`：输出 `runtime/termbase_seed/hkjc-local-results-20260701-20260704/seed_candidates.csv`，候选 `310` 条（`horse=265`、`race=21`、`jockey=24`），生产文件为 `/opt/umanewsbot/imports/hkjc-local-results-20260701-20260704/seed_candidates.csv`；dry-run 总计 `310`、新增 `5`、更新 `305`、错误 `0`；备份 `backups/db/pre-hkjc-local-results-20260701-20260704-term-import-20260705_030505.sql.gz` 通过 `gzip -t`；正式导入新增 `5`、更新 `305`、跳过 `0`。

导入后生产计数：`TermEntry=5948`、`TermAlias=6164`；`source_language=en/racing_region=hong_kong` 分布为 `horse=2479`、`jockey=70`、`race=1132`，另保留既有 `fixed_phrase=1`、`racecourse=1`、`trainer=1`。`http://127.0.0.1/healthz/` 返回 `200`。HKJC 香港本地赛果已回溯到 `2026-07-04`；仍需继续 HKJC overseas 与 WP Stud 赛事/骑手缺口。

### HKJC overseas live dry-run 记录（2026-07-04）

本地低上限 live dry-run 命令如下；本次只触网读取 HKJC overseas 入口页并生成审核产物，不写正式术语库、不部署生产：

```bash
tmp_db="/tmp/umanews_hkjc_overseas_live_$(date +%Y%m%d_%H%M%S).sqlite3"
out_dir="runtime/termbase_seed/hkjc-overseas-live-smoke-$(date +%Y%m%d_%H%M%S)"
DB_ENGINE=sqlite SQLITE_DB_PATH="$tmp_db" .venv/bin/python server/manage.py migrate --noinput
DB_ENGINE=sqlite SQLITE_DB_PATH="$tmp_db" .venv/bin/python server/manage.py prepare_termbase_seed_data \
  --source hkjc_overseas \
  --allow-network \
  --limit-meetings 1 \
  --limit-races 1 \
  --max-requests 6 \
  --request-interval-seconds 3 \
  --timeout-seconds 15 \
  --output-dir "$out_dir"
```

结果：

- 审核目录：`runtime/termbase_seed/hkjc-overseas-live-smoke-20260704_174924/`。
- `candidate_count=0`、`conflict_count=0`、`skipped_races=0`、`request_count=1`、`dry_run_error_count=0`。
- 请求 `https://racing.hkjc.com/en-us/overseas/` 返回 `200`。
- `incomplete=true`，失败类型为 `render_fallback_unavailable`，原因是直接 HTML 中没有 Race Card 链接。
- 结论：当前代码能安全暴露 HKJC overseas 的 Next.js shell 边界，不会把空 HTML 当作成功空结果；如需稳定生成海外 Race Card 候选，下一步应补浏览器渲染缓存或解析 HKJC 前端 API，再重新执行小批 live dry-run。

### HKJC overseas QIDS 回溯与生产导入记录（2026-07-05）

本轮未部署新的生成器代码到生产；生成器在本地通过 HKJC QIDS GraphQL 抽取海外 Race Card 中英对照，产物审核后上传生产并使用既有 `import_terms` 导入。

本地生成范围：

- 日期范围：`2024-01-01` 至 `2026-07-04`。
- 月度目录：`runtime/termbase_seed/hkjc-overseas-qids-YYYYMM/`。
- 合并目录：`runtime/termbase_seed/hkjc-overseas-qids-merged-20240101-20260704/`。
- 合并结果：原始行 `11633`、候选 `7691`、冲突 `3`、`incomplete=false`。
- 候选类型：`horse=6481`、`jockey=847`、`race=363`。

生产导入：

- 生产文件：`/opt/umanewsbot/imports/hkjc-overseas-qids-merged-20240101-20260704/seed_candidates.csv`。
- 容器文件：`/app/server/runtime/imports/hkjc-overseas-qids-merged-20240101-20260704/seed_candidates.csv`。
- dry-run：总计 `7691`、新增 `7688`、更新 `3`、错误 `0`。
- 备份：`backups/db/pre-hkjc-overseas-qids-term-import-20260705_040238.sql.gz`，已通过 `gzip -t`。
- 正式导入：总计 `7691`、新增 `7482`、更新 `209`、跳过 `0`。

导入后发现当前 `import_terms` 的 upsert 身份是 `term_type + source_language + source_ja`，不会按 `racing_region` 拆分；同名国际骑师会被后导入来源更新地区。为保留香港本地赛果骑师地区，已执行 HKJC 本地骑师地区恢复：

- 恢复文件：`runtime/termbase_seed/hkjc-local-jockey-region-restore-20260705/seed_candidates.csv`。
- 生产文件：`/opt/umanewsbot/imports/hkjc-local-jockey-region-restore-20260705/seed_candidates.csv`。
- dry-run：总计 `69`、新增 `0`、更新 `69`、错误 `0`。
- 备份：`backups/db/pre-hkjc-local-jockey-region-restore-20260705_040950.sql.gz`，已通过 `gzip -t`。
- 正式导入：总计 `69`、新增 `0`、更新 `69`、跳过 `0`。

恢复后核验：

- `TermEntry=13430`、`TermAlias=13646`。
- HKJC overseas 官方来源计数：`7483`。
- `source_language=en/racing_region=hong_kong`：`horse=2479`、`jockey=69`、`race=1132`，另有 `fixed_phrase=1`、`racecourse=1`、`trainer=1`。
- `http://127.0.0.1/healthz/` 返回 `200`。

注意：共享国际骑师当前只能作为同一个英文源术语存在，不能同时保留多个地区版本；这不会影响英文原文命中和中文译名应用，但地区统计需要按当前主记录解释。

### WP Stud 赛事/骑师/马场生产导入记录（2026-07-05）

本轮继续处理当前发现的 WP Stud 赛事、骑师和马场页面。WP Stud 属社区来源，导入时必须避免覆盖 HKJC 官方主译名。

本地生成：

- 缓存目录：`runtime/termbase_seed/source_cache_wpstud_extra_20260705/`。
- 输出目录：`runtime/termbase_seed/wpstud-race-jockey-racecourse-review-20260705/`。
- 来源：`Translation/Race` 目录下 `21` 个赛事页面、`Translation/jockey.htm`、`Translation/racecourse/RaceCourse.htm`。
- 完整候选：`2095` 条，冲突 `17` 条，`incomplete=false`。
- 完整候选类型：`race=1392`、`jockey=276`、`racecourse=427`。

生产完整 dry-run：

- 文件：`/app/server/runtime/imports/wpstud-race-jockey-racecourse-review-20260705/seed_candidates.csv`。
- 结果：总计 `2095`、新增 `1891`、更新 `204`、错误 `0`。
- 更新命中：`204` 条中 `199` 条命中 HKJC overseas 官方术语、`3` 条命中 HKJC 本地官方术语、`2` 条命中其他既有术语。
- 处理：生成 `seed_candidates_new_only.csv` 仅导入新增项，生成 `seed_candidates_skipped_existing.csv` 留作人工审核和别名决策依据。

过滤后导入：

- 过滤文件：`/opt/umanewsbot/imports/wpstud-race-jockey-racecourse-review-20260705/seed_candidates_new_only.csv`。
- 跳过清单：`/opt/umanewsbot/imports/wpstud-race-jockey-racecourse-review-20260705/seed_candidates_skipped_existing.csv`。
- dry-run：总计 `1891`、新增 `1891`、更新 `0`、错误 `0`。
- 备份：`backups/db/pre-wpstud-race-jockey-racecourse-term-import-20260705_072047.sql.gz`，已通过 `gzip -t`。
- 正式导入：总计 `1891`、新增 `1891`、更新 `0`、跳过 `0`。

导入后核验：

- `TermEntry=15321`、`TermAlias=15537`。
- WP Stud 新增英文社区术语计数：`1891`。
- WP Stud 全部相关术语计数：`2103`，包含此前已导入的 `210` 条日文马名社区术语和本轮 `1891` 条英文社区术语。
- `source_language=en` 已覆盖香港、英国、法国、美国、日本和 other 的马名、赛事、骑师和马场。
- `http://127.0.0.1/healthz/` 返回 `200`。

## 全球赛马数据库导入入口

香港、英国、法国、美国真实赛马数据库导入属于高风险生产数据操作，不能只凭本地 proof、fixture 测试或少量 dry-run 进入正式写库。

执行前必须先阅读并按顺序使用：

- `docs/global_racing_database_handoff.md`：当前 proof 边界和未完成项。
- `docs/global_racing_sync_manifest.md`：当前主树同步范围、已验证命令和防误用验证。
- `docs/global_racing_next_run_checklist.md`：下一轮按 HKJC -> UK -> France -> US 开跑的检查表。
- `docs/global_racing_full_crawl_runbook.md`：完整 plan-only、小批 dry-run、离线审计和 commit 门禁命令。
- `docs/global_racing_full_crawl_completion_audit.md`：完整目标完成判定和禁止误用证据。

生产写库前必须满足：

- 每地最新 60 天 `plan-only` 已保存。
- 具体批次执行前已使用 `render_global_racing_batch_command --plan-file ... --all-batches --output-dir ...` 或 `--batch N` 从 plan 文件渲染精确命令，并复核 `source`、`target_key`、`target_count`、`suggested_output_path`、`command_line` 和 `tee_command_line`。
- 每地所有 plan 批次均已小批 dry-run，且 `completion.is_complete=true`。
- 所有涉及马匹 profile 或等价详情字段已覆盖。
- `audit_global_racing_import_outputs --fail-on-incomplete` 输出 `commit_candidate_ready=true` 且 `blocking_reasons=[]`。
- 数据库备份、导入锁检查、健康检查和用户显式确认齐全。
- 写库后记录 `run_id`、表计数、coverage、请求数、失败摘要、锁释放、健康检查和回滚口径。

当前 `runtime/global_racing_import/proof-20260627` 只能通过 proof-only 审计；按 commit 候选口径会被正确阻断。不得把这组 proof JSON 当作最近 60 天完整抓取或生产写库依据。

### 核验正式术语

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.models import TermEntry; print(TermEntry.objects.count()); print(list(TermEntry.objects.filter(source_ja__in=['キタサンブラック','宝塚記念']).values('term_type','source_ja','target_zh','race_grade','aliases_ja')))"
```

期望：

- `キタサンブラック` 为启用马名术语，中文译词为 `北部玄驹`
- `宝塚記念` 为启用比赛术语，`race_grade=G1`

### 执行日候选新闻池批量验收

验收不只看单篇文章。按服务器当前时区执行日 0:00 后进入候选新闻池的全部文章检查：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py validate_candidate_news_since_midnight --format json
```

如需指定起点：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py validate_candidate_news_since_midnight --since 2026-06-09 --format json
```

逐篇确认：

- `terms` 中已有正式术语命中
- 未命中的马名和比赛名存在术语候选证据
- `race_grade` 与 `race_priority` 合理
- `score_total` 与 `review_mode` 不再出现明显低估

### 单篇文章重跑

如需重跑文章 `3961`：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.tasks import translate_article_task, process_article_automation_task, discover_term_candidates_task; article_id=3961; translate_article_task.delay(article_id); process_article_automation_task.delay(article_id); discover_term_candidates_task.delay(article_id)"
```

重跑后进入后台文章详情页核验中文标题、翻译元数据、自动评分原因和术语候选证据。

### 回滚方式

- 数据导入错误：优先使用后台停用错误术语，或用 `import_terms --mode upsert` 导入修正 CSV。
- 代码异常：回滚到上一 commit 并重启 `web/worker/beat`。
- 数据结构回滚：仅在确认无法通过停用术语或代码回滚恢复时，使用部署前数据库备份还原。

### 部署前配置

首次部署保持默认关闭：

```env
TERM_DISCOVERY_ENABLED=false
TERM_DISCOVERY_PROVIDER=rules
TERM_DISCOVERY_MIN_CONFIDENCE=60
```

执行代码部署、数据库迁移与检查：

```bash
docker compose -f docker-compose.prod.lowcost.yml up -d --build web worker beat
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py migrate
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py check
```

### 单篇手动验证

在后台候选新闻详情页点击“重新发现术语”，或执行：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec web python manage.py shell -c "from stable.tasks import discover_term_candidates_task; print(discover_term_candidates_task.run(ARTICLE_ID))"
```

检查后台“术语候选”列表，确认候选类型、上下文、来源文章、置信度、冲突信息和出现次数合理；接受一条测试候选后，确认正式术语库新增记录且操作日志完整。

### 逐步启用

1. 先保持关闭，抽查若干单篇手动发现结果。
2. 将 `TERM_DISCOVERY_ENABLED=true`，只重启 `web` 与 `worker`。
3. 每日抽检待审核候选，重点观察误报、跨类型冲突和证据增长。
4. 根据质量谨慎调整 `TERM_DISCOVERY_MIN_CONFIDENCE`，不要在未抽检时降低阈值。

### 监控与关闭

- 通过 `TaskExecutionLog(task_name=discover_term_candidates)` 查看任务成功与失败。
- 观察候选池每日新增量、拒绝比例、平均证据数量和正式术语冲突。
- 若误报或任务异常增加，将 `TERM_DISCOVERY_ENABLED=false` 并重启 `web` 与 `worker`；无需回滚迁移或删除候选数据。
- 不进行历史全量回溯，不允许绕过工作人员审核直接写入 `TermEntry`。

### 本次执行记录（2026-06-07）

实际部署时确认的若干细节，供后续运维复用：

- 连接方式：`ssh root@47.239.167.86`（公网 IP，端口 `22`，公钥认证）；部署目录 `/opt/umanewsbot`，compose 用 `docker-compose.prod.lowcost.yml`。
- 服务器 `git pull origin main` 走 HTTPS 远端，从 `7123e4e` 快进到 `e2e3e07`。
- **`web` 容器启动脚本会自动执行 `migrate`**：`docker compose up -d` 重建 `web` 后，迁移 `0006` 已在启动时应用，随后显式 `migrate` 会显示 `No migrations to apply`，属正常。
- 生产数据库名与用户均为 `horse_news`；迁移前快照命令：
  ```bash
  docker compose -f docker-compose.prod.lowcost.yml exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' > backups/pre-0006-<时间戳>.sql
  ```
- 本次备份产物：`.env.backup.20260607_033207` 与 `backups/pre-0006-20260607_033207.sql`（74M）。
- 验证：`check` 0 issues；候选/证据计数 `0/0`；`nginx → web` 与外网 `umafans.run` / `www.umafans.run` 均 `200`；`worker` 无报错。
- 本轮保持 `TERM_DISCOVERY_ENABLED=false`，未改 `AUTOMATION_ENABLED`（线上为 `true`）与 HTTPS。

## 公开首页资讯流生产部署（2026-06-22）

### 部署内容

- GitHub PR #1 `[codex] Upgrade public home info feed` 已从 draft 转为 ready，并合并到 `main`。
- merge commit：`e834f58`；实现提交：`1c9be7d`。
- 服务器 `/opt/umanewsbot` 从 `62a6a02` 快进到 `e834f58`。
- 本次不包含数据库迁移、生产 `.env` 开关调整或 Compose 架构变更。
- 新增公开站点静态资源 `stable/public.css`，首页与详情页不再以后台 `console.css` 作为主要样式入口。

### 部署前状态与备份

- 服务器存在未跟踪 `.env.backup.*` 和 `imports/`，保留不清理。
- 服务器 tracked diff 仅为部署脚本权限位变化：
  - `deploy_lowcost.sh`
  - `deploy/deploy_lowcost.sh`
  - `deploy/docker/compose-wrapper.sh`
- 上述权限位变化是为了修复此前 `Permission denied`，内容无差异，部署时予以保留。
- 部署前 `.env` 备份：`.env.backup.20260622_140844`。

### 部署命令

```bash
cd /opt/umanewsbot
git fetch origin main
git pull --ff-only origin main
./deploy_lowcost.sh
```

脚本结果：

- 重建并重启 `web / worker / beat`。
- `migrate` 显示 `No migrations to apply`。
- `collectstatic` 成功处理公开静态资源，生产首页引用 `/static/stable/public.2eec24723b45.css`。
- `web` 容器为 healthy，`db / redis` healthy，`worker / beat` up。

### 验证结果

```bash
curl -I http://umafans.run/healthz/
curl -I http://umafans.run/
curl -I http://umafans.run/static/stable/public.2eec24723b45.css
docker compose -f docker-compose.prod.lowcost.yml ps
docker logs --tail=80 umanewsbot-web-1
docker logs --tail=80 umanewsbot-nginx-1
```

结果：

- `http://umafans.run/healthz/` 返回 `200`，响应体为 `{"status": "ok"}`。
- `http://umafans.run/` 返回 `200`。
- 首页 HTML 包含 `home-page`、`headline-card`、`news-card` 和“原站热度”。
- 首页引用 `/static/stable/public.2eec24723b45.css`，不再引用旧 `console.css`。
- `public.css` 可访问并包含移动端 `news-card`、`headline-card`、`-webkit-line-clamp` 和 390px 视口布局规则。
- 浏览器生产验收：
  - 桌面端：轻导航、主头条和热门模块显示正常。
  - 390px 移动端：普通新闻卡约 `128px` 高，右侧缩略图约 `104px x 78px`，首屏头条后可见 3 条普通新闻，无横向溢出。
  - 详情页：标题、封面、来源、公开详情结构和 `public.css` 引用正常，控制台无错误。

### 回滚方式

本次无数据库迁移。若公开首页出现严重问题，优先回滚代码与容器：

```bash
cd /opt/umanewsbot
git checkout 62a6a02
./deploy_lowcost.sh
```

如需保持 `main` 分支语义，优先在 GitHub revert `e834f58` 后服务器 `git pull --ff-only origin main` 并重新执行 `./deploy_lowcost.sh`。

## 移动端首页密度 follow-up 生产部署（2026-06-23）

### 部署内容

- GitHub PR #2 `[codex] Polish mobile public home density` 已从 draft 转为 ready，并合并到 `main`。
- merge commit：`04e2ee9`；实现提交：`b6e93b9`。
- 服务器 `/opt/umanewsbot` 从 `e834f58` 快进到 `04e2ee9`。
- 本次不包含数据库迁移、生产 `.env` 开关调整或 Compose 架构变更。
- 主要变更是移动端 `stable/public.css` 首屏密度微调：收紧顶部与页面间距、头条图片比例从 `16 / 9` 改为 `16 / 7`、移动端隐藏头条摘要，普通新闻卡保持约 `128px` 高。

### 部署前状态与备份

- 部署前 `.env` 备份：`.env.backup.20260623_120201`。
- 服务器仍存在历史 `.env.backup.*` 与 `imports/` 未跟踪文件，保留不清理。
- 服务器 tracked diff 显示多个部署脚本权限位变化，属线上执行权限修正遗留，部署时保留不回滚。

### 部署命令

```bash
cd /opt/umanewsbot
cp .env .env.backup.$(date +%Y%m%d_%H%M%S)
git pull --ff-only origin main
chmod +x deploy_lowcost.sh deploy/*.sh deploy/docker/*.sh
./deploy_lowcost.sh
```

脚本结果：

- 重建并重启 `web / worker / beat`。
- `migrate` 显示 `No migrations to apply`。
- `collectstatic` 完成，生产首页引用 `/static/stable/public.9aaf4b105424.css`。
- `web` 容器为 healthy，`db / redis` healthy，`worker / beat` up。
- `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check` 返回 `System check identified no issues`。

### 验证结果

```bash
curl -I http://umafans.run/healthz/
curl -I http://umafans.run/
curl http://umafans.run/ | grep public
docker compose -f docker-compose.prod.lowcost.yml ps
docker logs --tail=80 umanewsbot-web-1
```

结果：

- `http://umafans.run/healthz/` 返回 `200`。
- `http://umafans.run/` 返回 `200`。
- 首页 HTML 包含 `home-page`、`headline-card`、`news-card` 和“原站热度”。
- 首页引用 `/static/stable/public.9aaf4b105424.css`，不引用 `console.css`。
- `public.css` 可访问并包含移动端 `max-width: 599px`、`aspect-ratio: 16 / 7` 和摘要隐藏规则。
- 浏览器生产验收：
  - 390px 移动端：首页头条约 `257px` 高，第一张普通新闻卡 `top=388`，普通新闻卡约 `128px` 高，右侧缩略图约 `104px x 78px`，首屏可见 4 条普通新闻，无横向溢出。
  - 详情页：公开详情结构、标题、封面正常，无横向溢出，控制台无错误。

### 回滚方式

本次无数据库迁移。若移动端首页密度出现严重问题，优先在 GitHub revert `04e2ee9`，然后服务器执行：

```bash
cd /opt/umanewsbot
git pull --ff-only origin main
./deploy_lowcost.sh
```

如需临时直接回退到上一生产版本，可 checkout `e834f58` 后重新部署，但后续仍应通过 GitHub revert 保持 `main` 分支语义一致。

## 外部赛马数据导入运行手册

### 默认状态

外部赛马数据导入默认不运行：

```bash
EXTERNAL_HORSE_DATA_IMPORT_ENABLED=false
EXTERNAL_HORSE_DATA_ALLOW_NETWORK=false
```

Celery 任务 `stable.tasks.import_external_horse_data_task` 不加入默认全量 Celery Beat 调度，生产只能由人工明确触发。

### 生产执行前

1. 确认代码已部署并执行迁移。
2. 备份数据库。
3. 确认同一时间没有其他外部赛马数据导入任务运行。
4. 首次执行建议先不抓赔率，先只补 `entry/result/horse/history`。
5. 首次真实请求建议使用更保守限速：`8-10` 秒请求间隔，小批量执行。

### 依赖检查

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_external_horse_data --check-dependency
```

### dry-run

dry-run 不写入外部数据表：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_external_horse_data --year 2026 --month 5 --dry-run
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_external_horse_data --race-id 202605310101 --dry-run
```

### 单月小批量真实导入

必须同时打开配置和命令参数：

```bash
EXTERNAL_HORSE_DATA_IMPORT_ENABLED=true
EXTERNAL_HORSE_DATA_ALLOW_NETWORK=true
EXTERNAL_HORSE_DATA_REQUEST_INTERVAL_SECONDS=10
EXTERNAL_HORSE_DATA_JITTER_SECONDS=2
EXTERNAL_HORSE_DATA_MAX_RACES_PER_RUN=10
EXTERNAL_HORSE_DATA_MAX_HORSES_PER_RUN=30
EXTERNAL_HORSE_DATA_FETCH_ODDS=false
```

执行：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_external_horse_data \
  --year 2026 --month 5 \
  --allow-network \
  --max-races 10 \
  --max-horses 30 \
  --no-fetch-horse-detail
```

如需补单匹马，并且人工已知可信日文马名：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_external_horse_data \
  --horse-id 1000000000 \
  --horse-name マヤノライジン \
  --allow-network
```

### 验收查询

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_external_horse_data --lookup-name マヤノライジン
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_external_horse_data --stats-run-id <run_id>
```

重点看：

- `status`
- `failure_count`
- `coverage_stats.race_count`
- `coverage_stats.entry_count`
- `coverage_stats.result_count`
- `coverage_stats.unique_horse_id_count`
- `coverage_stats.unique_horse_name_count`
- `coverage_stats.missing_horse_id_or_name_count`

### 日志与停止

```bash
docker logs --tail=200 umanewsbot-web-1
docker logs --tail=200 umanewsbot-worker-1
```

如需停止：

1. 关闭 `EXTERNAL_HORSE_DATA_IMPORT_ENABLED=false` 和 `EXTERNAL_HORSE_DATA_ALLOW_NETWORK=false`。
2. 停止正在执行导入的命令或 Celery worker。
3. 保留外部数据表记录，新表不参与主新闻链路，不影响前台发布。

### 2026-06-23 首次生产小批量结果

- 部署提交：`58a6e82`。
- `.env` 备份：`.env.backup.external-horse-data-20260623_231514`。
- `stable.0008` 迁移已应用，`web` healthy，`/healthz/` 返回 `200`。
- `python manage.py import_external_horse_data --check-dependency` 返回 `keibascraper import ok`。
- dry-run 目标：`2026-05`，最多 10 场，预计 20 个请求。
- 真实导入参数：`2026-05`，最多 10 场，不抓赔率，不补马匹详情，请求间隔 10 秒 + 2 秒抖动。
- 结果：`run_id=1`，`status=paused`，成功 10 场，失败 0，因批量上限跳过 326 场。
- 写入：10 场比赛、151 条出走、143 条赛果、143 个唯一马 ID/马名索引。
- `2026-06-24` 已补充按月续跑逻辑：再次执行同一月份时会跳过已落库 race，只处理下一批未导入 race。
- 第二批续跑结果：`run_id=2`，已跳过首批 10 场，继续成功导入 10 场，失败 0；累计 20 场比赛、274 个唯一马 ID/马名索引。
- 第三批续跑结果：`run_id=3`，继续成功导入 30 场，失败 0；累计 50 场比赛、695 个唯一马 ID/马名索引，`/healthz/` 返回 `200`。
- 长循环导入中断记录：`run_id=4` 到 `run_id=8` 均成功；`run_id=9` 成功 7 场后进程退出码 `137` 中断，已标记为 `partial` 并释放导入锁。中断后累计 182 场比赛、2401 个唯一马 ID/马名索引，`/healthz/` 返回 `200`。

## 2026-06-25 外部马名索引识别链路生产部署

### 部署内容

- GitHub PR #6 `[codex] Use external horse aliases for name recognition` 已 squash merge 到 `main`。
- merge commit：`35b0866`。
- 服务器 `/opt/umanewsbot` 从 `817e1c8` 快进到 `35b0866`。
- 本次不包含数据库迁移或 `.env` 功能开关调整。
- 主要变更：
  - `ExternalHorseAlias` 接入文章马名识别、翻译保护、发布校验和术语候选发现。
  - 外部已知但无中文译名的马名在译文中原样保护，未保留时记录独立 `external_horse_not_preserved` warning。
  - `TermEntry` 仍作为正式中文术语库；外部马名索引不批量写入 `TermEntry`。

### 部署前状态与备份

- 部署前 `.env` 备份：`.env.backup.external-horse-alias-20260625_182936`。
- 服务器部署前只有 `.env.backup.*`、`imports/`、`napcat/`、`runtime/` 等未跟踪运行态文件；无 tracked diff。

### 部署命令

```bash
cd /opt/umanewsbot
cp .env .env.backup.external-horse-alias-$(date +%Y%m%d_%H%M%S)
git pull --ff-only origin main
chmod +x deploy_lowcost.sh deploy/*.sh deploy/docker/*.sh
./deploy_lowcost.sh
```

### 验证结果

- `./deploy_lowcost.sh` 执行成功。
- `migrate` 显示 `No migrations to apply`。
- `collectstatic` 完成，`0 static files copied`，`129 unmodified`，`360 post-processed`。
- `web` 容器 healthy，`db / redis` healthy，`worker / beat` up。
- `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check`：通过。
- `http://127.0.0.1/healthz/` 返回 `{"status": "ok"}`。
- `http://umafans.run/healthz/` 返回 `200`。
- `http://umafans.run/` 返回 `200`。
- 生产只读 smoke test：`ExternalHorseAlias=11521`；`recognize_horse_names("ロブチェンが出走", "ロブチェンは重賞へ向かう。")` 返回 `ロブチェン`，来源为 `external_alias`，外部 horse ID 为 `2023107089`。

## QQ Bot / OneBot 生产运行态配置（2026-06-24）

### 配置结论

- OneBot 网关：独立 Docker 容器 `umanewsbot-onebot-1`
- 镜像：`mlikiowa/napcat-docker:latest`
- 访问边界：
  - 宿主机仅绑定 `127.0.0.1:3000 -> 3000` 和 `127.0.0.1:6099 -> 6099`
  - 应用容器通过 Docker 网络别名 `http://onebot:3000` 访问
  - 不对公网暴露 OneBot API 或 NapCat WebUI
- 数据目录：
  - `/opt/umanewsbot/napcat/config`
  - `/opt/umanewsbot/napcat/qq`
- 机密文件：
  - `/opt/umanewsbot/runtime/secrets/onebot_access_token`
  - `/opt/umanewsbot/runtime/secrets/napcat_webui_token`

### 生产 `.env`

```env
ONEBOT_BASE_URL=http://onebot:3000
ONEBOT_TIMEOUT_SECONDS=30
QQ_PUSH_ENABLED=true
QQ_PUSH_SCOPE=high_value_only
QQ_PUSH_IMPORTANCE_STRATEGY=ranked
QQ_PUSH_MAX_ATTEMPTS=3
QQ_PUSH_URL_CHECK_TIMEOUT_SECONDS=5
QQ_PUSH_SENDING_STALE_SECONDS=600
QQ_PUSH_MIN_INTERVAL_SECONDS=60
```

`ONEBOT_ACCESS_TOKEN` 已写入生产 `.env`，但不得写入仓库文档。生产当前已将 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked` 用于测试群灰度，让后续自动推送只覆盖 netkeiba 访问量榜 / 注目数榜新闻。`QQ_PUSH_MIN_INTERVAL_SECONDS` 用于控制同一目标群两次自动发送尝试之间的最小间隔，避免批量补推或批量发布触发 QQ / NapCat 发送异常。

### 已配置群目标

- `PushTarget.group_id=1026525240`
- `name=UmaFans测试群`
- `is_active=true`

### 验证结果

- `docker ps` 显示 `umanewsbot-onebot-1` 正常运行。
- `ss -ltnp` 显示 `3000` 与 `6099` 均只监听 `127.0.0.1`。
- OneBot 直连测试返回 `{"status":"ok","retcode":0,...}`，消息发送到 `新闻测试(1026525240)`。
- Django 应用侧 `stable.services.onebot.BotPusher` 通过 `http://onebot:3000` 成功发送测试消息，返回 `retcode=0`。
- 重启 `worker / beat` 让它们读取新的 `.env`；Compose 同时按依赖短暂重建了 `db / web` 容器，但没有执行 `git pull`、没有 build、没有运行 `deploy_lowcost.sh`。
- 重启后 `web` healthz 返回 `{"status": "ok"}`，`web` 容器 healthy，`db / redis` healthy，`worker / beat` up。
- 2026-06-24 已部署 `add-qqbot-auto-push` 到 `main`，生产迁移 `stable.0010_qqpushdelivery` 已应用，`QQ_PUSH_ENABLED=true` 与 `QQ_PUSH_SCOPE=all_public` 已生效。
- 批量补推 126 篇存量公开文章时，`QQPushDelivery` 记录创建成功；NapCat / QQ 客户端返回 `EventChecker Failed ... 网络连接异常`，系统按 `send_failed` 记录并进入有限重试，未误标记成功。后续补推必须使用 `QQ_PUSH_MIN_INTERVAL_SECONDS` 或人工脚本限速。
- 2026-06-25 重新扫码登录 NapCat 后，Django 应用侧短消息和 `qq_auto_push_article_task` 自动任务链路均已成功发送到测试群。限速补推按 65 秒间隔成功发送 79 条交付记录；按当前验收口径，不再继续补推全部历史公开新闻，剩余历史失败记录保留在后台，不影响后续新发布文章自动推送。
- 2026-06-25 部署榜单重点推送后，生产已切换为 `QQ_PUSH_SCOPE=high_value_only` 与 `QQ_PUSH_IMPORTANCE_STRATEGY=ranked`；本次不补推历史公开新闻，后续等待自然榜单新闻触发测试群推送。
- 2026-06-26 再次排查 QQ 推送停滞时，生产日志确认 NapCat 快速登录态失效；处理时先将 `QQ_PUSH_ENABLED=false` 并重启 `worker / beat` 暂停自动推送，用户重新扫码登录后，`BotPusher().is_online()` 返回 `(True, '')`，`/get_login_info` 显示 QQ `1577955464`，群列表包含 `1026525240`，Django 应用侧测试消息发送成功。随后恢复 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked` 并重启 `worker / beat`。本次不补推全部已发表新闻。
- 2026-06-26 OneBot 离线防护已部署到生产 `a2146d6`，部署前 `.env` 备份为 `.env.backup.qqbot-offline-guard-20260626_223731`。部署后 `web` healthy，迁移无新增，`manage.py check` 通过，本地和公网 `/healthz/` 均为 `200`，worker 环境确认 QQ 自动推送仍开启；`BotPusher().is_online()` 返回 `(True, '')`，测试群部署验证消息发送成功，`message_id=1364343902`。

## 2026-06-25 榜单重点 QQ 推送与公开文章 ID URL 生产部署

### 部署内容

- `elevate-ranked-netkeiba-sources`：同一 netkeiba 新闻先被新着顺命中、稍后被访问量榜或注目数榜命中时，主来源可从 `latest` 提升为 `access` 或 `attention`；访问量榜和注目数榜不互相覆盖。
- `push-ranked-news-to-qq`：生产 `high_value_only` 改为按 `QQ_PUSH_IMPORTANCE_STRATEGY=ranked` 判断重点新闻，本期只推 `netkeiba:access` / `netkeiba:attention` 且无 blocker 的公开文章；来源提升后的已公开文章会触发 QQ 自动推送编排。
- `use-article-id-public-urls`：公开详情主路径改为 `/news/<article_id>/`，旧非纯数字 slug URL 保留为 `302` 跳转入口，QQ 消息中的 `阅读全文` 不再包含标题全文。

### 部署前状态与备份

- 合并 PR：#8 `[codex] Implement ranked QQ push and ID article URLs`。
- 部署提交：`00e4bd4`。
- 服务器部署前 HEAD：`b0c986a`。
- 部署前确认无正在运行的 `ExternalDataImportRun(status="started")`。
- 部署前 `.env` 备份：`.env.backup.qq-ranked-idurl-20260625_191826`。
- 服务器部署前只有 `.env.backup.*`、`imports/`、`napcat/`、`runtime/` 等未跟踪运行态文件；无 tracked diff。

### 部署步骤与配置

```bash
cd /opt/umanewsbot
git pull --ff-only origin main
cp .env .env.backup.qq-ranked-idurl-20260625_191826
```

生产 `.env` 已设置：

```env
QQ_PUSH_ENABLED=true
QQ_PUSH_SCOPE=high_value_only
QQ_PUSH_IMPORTANCE_STRATEGY=ranked
QQ_PUSH_MAX_ATTEMPTS=3
QQ_PUSH_MIN_INTERVAL_SECONDS=60
ONEBOT_BASE_URL=http://onebot:3000
ONEBOT_TIMEOUT_SECONDS=30
```

随后执行：

```bash
bash ./deploy_lowcost.sh
```

### 验证结果

- `./deploy_lowcost.sh` 执行成功，`db / web / worker / beat` 已重建，`nginx / redis` 正常运行。
- `migrate` 显示 `No migrations to apply`。
- `collectstatic` 完成，`0 static files copied`，`129 unmodified`，`360 post-processed`。
- `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check`：通过。
- 生产 worker 环境确认 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked`。
- `http://umafans.run/healthz/` 返回 `200`。
- `http://umafans.run/` 返回 `200`。
- 抽检公开文章 `ARTICLE_ID=5551`：`http://127.0.0.1/news/5551/` 返回 `200`。
- 抽检旧 slug URL 返回 `302`，`Location` 指向 `/news/5551/`。
- 本轮不补推全部已发表新闻；后续只等待自然榜单新闻触发测试群推送。

### 归档结果

- `add-qqbot-auto-push` 已归档为 `openspec/changes/archive/2026-06-25-add-qqbot-auto-push/`，并创建正式规格 `openspec/specs/qqbot-auto-push/spec.md`。
- `elevate-ranked-netkeiba-sources` 已归档为 `openspec/changes/archive/2026-06-25-elevate-ranked-netkeiba-sources/`，并同步到 `openspec/specs/crawl-freshness-and-source-health/spec.md`。
- `use-article-id-public-urls` 已归档为 `openspec/changes/archive/2026-06-25-use-article-id-public-urls/`，并同步到 `openspec/specs/public-home-info-feed/spec.md`。
- `push-ranked-news-to-qq` 已归档为 `openspec/changes/archive/2026-06-25-push-ranked-news-to-qq/`，并同步到 `openspec/specs/qqbot-auto-push/spec.md`。
- 前期废弃的空目录 `openspec/changes/refine-ranked-news-push/` 已清理，避免 OpenSpec active 列表出现无任务占位 change。
- 归档后 `openspec validate --all` 通过。

### 自动推送上线步骤

1. 合入并部署 `add-qqbot-auto-push`。
2. 执行迁移，确认 `stable_qqpushdelivery` 表存在。
3. 确认测试群 `PushTarget.is_active=true`。
4. 设置 `QQ_PUSH_ENABLED=true`、`QQ_PUSH_SCOPE=high_value_only`、`QQ_PUSH_IMPORTANCE_STRATEGY=ranked`。
5. 重启 `worker / beat`。
6. 发布或复用一篇公开文章触发自动推送，核对测试群消息、`QQPushDelivery` 和 worker 日志。

### 停用方式

停用自动推送：

```env
QQ_PUSH_ENABLED=false
```

停用 OneBot 网关：

```bash
cd /opt/umanewsbot
docker rm -f umanewsbot-onebot-1
```

## expand-international-racing-coverage 部署前运维说明

> 当前状态：本 change 仍在本地实现与验证阶段，尚未部署生产。本节用于后续部署前核对。

### QQ 群级自动推送配置

- `QQ_PUSH_ENABLED` 仍是总开关，只决定自动推送任务是否运行。
- `PushTarget.allowed_regions`、`PushTarget.push_scope`、`PushTarget.importance_strategy` 决定“推什么给谁”。
- 迁移会把已有 `PushTarget.allowed_regions` 回填为 `["japan"]`，保留旧的日本新闻推送行为；运行时若遇到空地区列表，也按兼容默认处理为仅允许 `japan`，不得默认推送全球新闻。
- `PushTarget.push_scope` 为空时回退到全局 `QQ_PUSH_SCOPE`。
- `PushTarget.importance_strategy` 为空时回退到全局 `QQ_PUSH_IMPORTANCE_STRATEGY`。
- 文章 `racing_region` 缺失或非法时，自动推送必须跳过，原因记录为 `region_missing`。
- 自动推送创建交付前会逐个目标群判断地区、范围和重点策略；不符合目标群配置的群不会创建新的 `QQPushDelivery`。

部署后建议核对：

```bash
python manage.py shell -c "from stable.models import PushTarget; print(list(PushTarget.objects.values('name','group_id','is_active','allowed_regions','push_scope','importance_strategy')))"
```

回滚/停用方式：

```env
QQ_PUSH_ENABLED=false
```

如果只想恢复旧日本新闻推送行为，可在 Django Admin 中把目标群 `allowed_regions` 设置为 `["japan"]` 或留空，并把 `push_scope / importance_strategy` 留空，让代码只在范围和重点策略上回退到全局配置。

### HKJC 外部数据导入命令

HKJC 导入默认 dry-run，不会写正式外部缓存表：

```bash
python manage.py import_hkjc_external_data --race-date 2026-06-21 --payload-file /path/to/hkjc_sample.json
```

确认样本字段后再提交写入 External* 缓存表：

```bash
python manage.py import_hkjc_external_data --race-date 2026-06-21 --payload-file /path/to/hkjc_sample.json --commit
```

提交写入仍是小样本受控导入：命令会按配置检查 `max_races / max_horses`，payload 超过上限时直接失败，不会静默截断或部分写入。遇到超限时应拆分样本文件后重新 dry-run，再提交。

HKJC 真实网络小样本相关配置保持保守值：

```env
HKJC_IMPORT_NETWORK_BASE_URL=https://racing.hkjc.com
HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=8
HKJC_IMPORT_MAX_RACES_PER_RUN=20
HKJC_IMPORT_MAX_HORSES_PER_RUN=80
HKJC_IMPORT_MAX_REQUESTS_PER_RUN=200
```

真实网络 dry-run 可从单场或小范围 recent-days 开始，并记录请求边界：

```bash
python manage.py import_hkjc_external_data --race-id HK20260624HV01 --allow-network
python manage.py import_hkjc_external_data --recent-days 60 --limit-races 1 --limit-horses 1 --max-requests 10 --allow-network
```

生产最近 2 个月全量前，先用 plan-only 生成拆批计划。plan-only 只抓赛日和 race links，不抓单场结果或马匹详情：

```bash
python manage.py import_hkjc_external_data --recent-days 60 --limit-races 20 --max-requests 80 --allow-network --plan-only
```

plan-only 的每个 batch 会输出 `skip_races`，后续批次 dry-run/commit 必须带对应 offset，避免每批都从第一场重跑：

```bash
python manage.py import_hkjc_external_data --recent-days 60 --skip-races 20 --limit-races 20 --limit-horses 200 --max-requests 260 --allow-network
```

更推荐使用 plan-only 输出里的 `race_ids` 做精确批次。该模式只请求指定比赛页和涉及马匹详情页，不需要为后续批次重新扫描前置赛日页：

```bash
python manage.py import_hkjc_external_data --race-ids HK20260624HV02,HK20260613ST04 --limit-horses 200 --max-requests 260 --allow-network
```

2026-06-26 本地 plan-only 结果显示：最近 60 天 HKJC 下拉目标日期页 `28` 个；过滤 overseas simulcast 的 `S*` racecourse 后，本地香港 `HV/ST` 比赛为 `144` 场，按每批 `20` 场拆为 `8` 批。生产环境仍需重跑 plan-only，以生产当时页面为准。

`recent-days/date-range/race-ids` 输出中的 `completion` 是生产门禁字段：

- `completion.is_complete=false`：本次因 `limit-races`、`limit-horses` 或请求上限等原因只是小样本/拆批运行，不能当作最近 2 个月全量完成。
- `completion.stop_reason`：记录停止原因，例如 `limit_horses_reached`。
- `completion.meetings_found / races_imported / unique_horses_found / horse_profiles_fetched`：用于估算下一批请求量和生产 commit 风险。
- `race-ids` 批次没有 `meetings_found`，以 `race_ids / races_imported / unique_horses_found / horse_profiles_fetched` 作为审计字段。

隔离环境验证过的真实网络 payload 可以 commit，但生产执行前必须先备份数据库、检查单来源锁和 `started` run、跑 dry-run、取得用户显式确认：

```bash
python manage.py import_hkjc_external_data --recent-days 60 --limit-races 1 --limit-horses 1 --max-requests 10 --allow-network --commit
```

查询导入统计：

```bash
python manage.py import_hkjc_external_data --stats-run-id <run_id>
```

查询本地 HKJC 马名索引：

```bash
python manage.py import_hkjc_external_data --lookup-name "Lucky Star"
```

生产注意事项：

- 部署前必须确认没有正在运行的外部数据导入。
- 真实网络请求必须保持低频限速；扩大到最近 2 个月全量前，应先用 `--limit-races / --limit-horses / --max-requests` 分批 dry-run，确认请求量和字段覆盖。
- 生产最近 2 个月全量 commit 前必须记录备份路径、dry-run 结果、锁检查、健康检查和用户确认。
- 本 change 不创建比赛页、赛果页、马匹页；导入数据只作为外部缓存、马名识别和后续项目底座。
- 2026-06-26 生产第 1 批 full dry-run 曾在 HKJC 马匹 profile 补抓阶段遇到 `ReadTimeout` / TLS handshake timeout；该次为 dry-run，未写表，锁为空。随后已补 transient timeout retry：单请求最多 3 次，失败尝试会保留在请求证据中。长批次仍建议先 dry-run，失败后检查 `started_runs`、单来源锁和表计数再重试。

## 2026-06-26 HKJC 数据导入 readiness 与英法美 spike 生产部署

### 部署前状态

- change：`start-hkjc-data-import-and-global-spikes`
- 部署 commit：`b0361cf`
- 服务器部署前 HEAD：`4d09d25`
- 部署前 `.env` 备份：`.env.backup.hkjc-global-spikes-20260626_164045`
- 部署前只读检查：
  - `ExternalDataImportLock` 运行中锁：无
  - `ExternalDataImportRun(status="started")`：无
  - `web` 容器：healthy

### 部署命令

```bash
cd /opt/umanewsbot
cp .env .env.backup.hkjc-global-spikes-20260626_164045
git pull --ff-only origin main
chmod +x deploy_lowcost.sh deploy/*.sh deploy/docker/*.sh
bash ./deploy_lowcost.sh
```

### 部署结果

- 服务器 `/opt/umanewsbot` 已从 `4d09d25` 快进到 `b0361cf`。
- `bash ./deploy_lowcost.sh` 执行成功。
- 迁移显示 `No migrations to apply`。
- `web / worker / beat` 已重建，`web` healthy。
- `collectstatic` 完成：`0 static files copied`，`129 unmodified`，`360 post-processed`。

### 生产验证

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check
curl -I http://127.0.0.1/healthz/
curl -I http://umafans.run/healthz/
curl -I http://umafans.run/
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_hkjc_external_data --race-date 2026-06-21 --payload-file stable/fixtures/hkjc/2026-06-21-race-date-sample.json
```

结果：

- `manage.py check`：通过。
- `http://127.0.0.1/healthz/`：`200`
- `http://umafans.run/healthz/`：`200`
- `http://umafans.run/`：`200`
- HKJC 样本命令：dry-run 成功，`coverage_stats={"races":1,"entries":2,"results":2,"horses":2}`，`would_write_formal_tables=false`。

注意：第一次 HKJC smoke 使用了仓库根相对路径 `server/stable/fixtures/...`，容器内工作目录为 `/app/server`，因此返回 `FileNotFoundError`；已改用 `stable/fixtures/...` 重跑通过。这不是业务逻辑失败。

### 边界

- 该部署验证阶段没有执行 HKJC `--commit`；后续生产样本 commit 见下方单独记录。
- 本次生产没有启用英法美正式导入、Celery Beat 调度或生产命令队列。
- HKJC 真实网络 dry-run 当前最小 URL 构造返回 `404`，后续必须先确认稳定 JSON/API、页面脚本 payload 或 HTML 解析入口，才能进入真实网络 commit 设计。

### 归档同步

- 归档提交：`db0f3cc`
- 服务器 `/opt/umanewsbot` 已从 `b0361cf` 快进到 `db0f3cc`。
- `db0f3cc` 仅移动 OpenSpec change 到 archive 并同步正式 spec，不包含服务代码变更；因此未重新 build 或重启容器。
- 服务器未安装 `openspec` CLI，归档后的 `openspec validate --all` 在本地 worktree 执行并通过。
- 归档同步后 `http://umafans.run/healthz/` 和 `http://umafans.run/` 仍返回 `200`。

## 2026-06-26 HKJC 生产样本 commit

### 执行边界

- 本次只提交仓库 fixture：`stable/fixtures/hkjc/2026-06-21-race-date-sample.json`。
- 本次不是 HKJC 真实网络抓取；`--allow-network` 的稳定入口仍未确认。
- 本次不创建公开比赛页、赛果页或马匹页，只写 `External*` 外部缓存表和 `ExternalHorseAlias`。
- 本次不启用 Celery Beat 周期任务或后台持续导入队列。

### 备份

```bash
cd /opt/umanewsbot
mkdir -p backups/db
docker compose -f docker-compose.prod.lowcost.yml exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB"' | gzip > backups/db/pre-hkjc-sample-20260626_180646.sql.gz
gzip -t backups/db/pre-hkjc-sample-20260626_180646.sql.gz
```

结果：

- 备份文件：`backups/db/pre-hkjc-sample-20260626_180646.sql.gz`
- 大小：`42M`
- `gzip -t`：通过

### 预检查

```bash
cd /opt/umanewsbot
docker compose -f docker-compose.prod.lowcost.yml ps
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py shell -c 'from stable.models import ExternalDataImportLock, ExternalDataImportRun, ExternalRace, ExternalRaceEntry, ExternalRaceResult, ExternalHorse, ExternalHorseAlias; print({"active_locks": [], "started_runs": [], "hkjc_counts": {"runs": ExternalDataImportRun.objects.filter(source="hkjc").count(), "races": ExternalRace.objects.filter(source="hkjc").count(), "entries": ExternalRaceEntry.objects.filter(source="hkjc").count(), "results": ExternalRaceResult.objects.filter(source="hkjc").count(), "horses": ExternalHorse.objects.filter(source="hkjc").count(), "aliases": ExternalHorseAlias.objects.filter(source="hkjc").count()}})'
ps -eo pid,args | grep "[i]mport_hkjc_external_data\|[i]mport_external_horse_data" || true
```

结果：

- 生产 HEAD：`5f92e4d`
- `web / worker / beat / db / redis / nginx`：运行中，`web` healthy
- HKJC 生产导入前计数：`runs=0`、`races=0`、`entries=0`、`results=0`、`horses=0`、`aliases=0`
- 无 HKJC 导入进程

### dry-run

```bash
cd /opt/umanewsbot
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_hkjc_external_data --race-date 2026-06-21 --payload-file stable/fixtures/hkjc/2026-06-21-race-date-sample.json
```

结果：

- `dry_run=true`
- `coverage_stats={"races":1,"entries":2,"results":2,"horses":2}`
- `would_write_formal_tables=false`

### commit

```bash
cd /opt/umanewsbot
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_hkjc_external_data --race-date 2026-06-21 --payload-file stable/fixtures/hkjc/2026-06-21-race-date-sample.json --commit
```

结果：

- `run_id=1960`
- `status=success`
- `success_count=7`
- `skipped_count=0`
- `failure_count=0`
- `coverage_stats={"races":1,"entries":2,"results":2,"horses":2}`

### 提交后核验

```bash
cd /opt/umanewsbot
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_hkjc_external_data --stats-run-id 1960
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py import_hkjc_external_data --lookup-name "STELLAR EXPRESS"
docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py shell -c 'from stable.models import ExternalDataImportLock, ExternalDataImportRun, ExternalRace, ExternalRaceEntry, ExternalRaceResult, ExternalHorse, ExternalHorseAlias; print({"locks": list(ExternalDataImportLock.objects.values("source", "racing_region", "locked_by_run_id", "acquired_at")), "hkjc_runs": ExternalDataImportRun.objects.filter(source="hkjc").count(), "latest_run": list(ExternalDataImportRun.objects.filter(source="hkjc").order_by("-id").values("id", "status", "success_count", "skipped_count", "failure_count", "target_type", "current_target_id")[:1]), "counts": {"races": ExternalRace.objects.filter(source="hkjc").count(), "entries": ExternalRaceEntry.objects.filter(source="hkjc").count(), "results": ExternalRaceResult.objects.filter(source="hkjc").count(), "horses": ExternalHorse.objects.filter(source="hkjc").count(), "aliases": ExternalHorseAlias.objects.filter(source="hkjc").count()}})'
curl -sS -o /dev/null -w "public_healthz=%{http_code}\n" http://umafans.run/healthz/
```

结果：

- `--stats-run-id 1960`：`status=success`，`success_count=7`，`failure_count=0`
- `--lookup-name "STELLAR EXPRESS"`：命中 `external_horse_id=HKH_STELLAR_EXPRESS`，`confidence=100`
- HKJC 正式外部表计数：`races=1`、`entries=2`、`results=2`、`horses=2`、`aliases=4`
- `ExternalDataImportLock` 中 HKJC 记录为未占用状态：`locked_by_run_id=None`，`acquired_at=None`
- 未发现仍在运行的 HKJC 导入进程

## 2026-06-27 全球赛马数据库能力确认上线

本次上线只发布四地赛马数据库“抓取能力可用”相关改造，不执行最近 60 天完整大量爬取，也不执行生产 `--commit`。

上线包必须从 `origin/main` 干净基线整理，避免把当前本地大工作树中的 QQ 推送、前台信息流、compose 端口或历史 archive 差异混入。必要范围限定为：

- UK / France / US importer 与管理命令
- `audit_global_racing_import_outputs` 离线审计命令
- `render_global_racing_batch_command` 只读批次命令渲染器
- 四地真实来源 fixtures、OpenSpec `real-global-racing-data-ingestion` 规格/归档
- `docs/global_racing_*` 交接、runbook、审计和 proof 记录

上线后验收重点：

- `manage.py check` 通过
- 全球赛马目标测试通过
- `openspec validate --all` 通过
- `/healthz/` 返回 `200`
- `import_uk_external_data --help`、`import_france_external_data --help`、`import_us_external_data --help`、`audit_global_racing_import_outputs --help` 可用
- 生产不新增 `ExternalDataImportRun(status="started")`，不持有 `ExternalDataImportLock`

后续如果要完整抓取最近 60 天数据，必须新开执行窗口，先 plan-only，再小批 dry-run，再离线审计，最后经备份、锁检查、健康检查和用户显式确认后才允许讨论 `--commit`。

### 本次执行结果

- 提交：`93b7007 Ship global racing database import capability`
- 推送：`main` 从 `9ff667a` fast-forward 到 `93b7007`
- 部署：服务器 `/opt/umanewsbot` 执行 `git pull --ff-only origin main` 后运行 `bash ./deploy_lowcost.sh`
- 迁移：`No migrations to apply`
- 容器：`web / worker / beat` 已重建，`web` healthy
- 验证：
  - `manage.py check` 通过
  - `http://127.0.0.1/healthz/`、`http://umafans.run/healthz/` 和首页均返回 `200`
  - `import_uk_external_data`、`import_france_external_data`、`import_us_external_data`、`render_global_racing_batch_command` 命令入口可用
  - proof-only 审计通过，`proof_ready=true`、`proof_blocking_reasons=[]`、`commit_candidate_ready=false`
  - `ExternalDataImportRun(status="started")=0`
  - HKJC 与 netkeiba 的 `ExternalDataImportLock.locked_by_run_id=None`
  - 一次性 proof 审计容器已自动删除，无 `umanewsbot-web-run-*` 临时容器残留
- `http://umafans.run/healthz/`：`200`

### 恢复口径

如需要撤销本次样本写入，优先在维护窗口使用备份 `backups/db/pre-hkjc-sample-20260626_180646.sql.gz` 做整库恢复；不要只手工删除 `External*` 表行，避免遗漏 `ExternalDataImportRun`、`ExternalHorseAlias` 或锁状态证据。当前样本写入规模很小，且不参与公开前台或自动发布链路。

## 2026-06-30 HKJC 慢速真实 dry-run 启动

本次只执行香港 HKJC 真实网络 dry-run，不执行生产 `--commit`，不写正式表。

### 执行前检查

- 服务器：`/opt/umanewsbot`
- 代码：`7b6e51b`
- `docker compose -f docker-compose.prod.lowcost.yml ps`：`web/db/redis` healthy，`worker/beat/nginx` 运行中
- `ExternalDataImportRun(status="started")=0`
- HKJC 与 netkeiba 的 `ExternalDataImportLock.locked_by_run_id=None`
- `http://umafans.run/healthz/`：`200`

### 最新 plan-only

```bash
cd /opt/umanewsbot
mkdir -p runtime/global_racing_import/hkjc-20260630
docker compose -f docker-compose.prod.lowcost.yml run --rm --no-deps -T \
  -e HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=8 \
  -e HKJC_IMPORT_MAX_REQUESTS_PER_RUN=160 \
  web python manage.py import_hkjc_external_data \
  --recent-days 60 \
  --end-date 2026-06-30 \
  --plan-only \
  --limit-races 20 \
  --max-requests 160 \
  --allow-network \
  > runtime/global_racing_import/hkjc-20260630/hkjc-plan-20260630.json
```

结果：

- `coverage={"meetings":29,"races":146,"estimated_requests_without_horses":176}`
- `batch_count=8`
- `first_batch.race_count=20`
- `last_batch.skip_races=140`、`last_batch.race_count=6`
- 该 plan 已不同于历史 `144` 场；不要直接沿用旧 `120/144` 停点。

### 小批慢速 dry-run

```bash
cd /opt/umanewsbot
docker compose -f docker-compose.prod.lowcost.yml run --rm --no-deps -T \
  -e HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=8 \
  -e HKJC_IMPORT_MAX_REQUESTS_PER_RUN=100 \
  web python manage.py import_hkjc_external_data \
  --race-ids HK20260627ST02,HK20260627ST03 \
  --max-requests 100 \
  --allow-network \
  > runtime/global_racing_import/hkjc-20260630/hkjc-batch1-races-001-002-dryrun-20260630.json
```

结果：

- `dry_run=true`
- `would_write_formal_tables=false`
- `coverage_stats={"races":2,"entries":28,"results":28,"horses":28}`
- `completion={"is_complete":true,"stop_reason":"complete","race_ids":["HK20260627ST02","HK20260627ST03"],"races_imported":2,"unique_horses_found":28,"horse_profiles_fetched":28,"limit_horses":null,"max_requests":100}`
- 请求日志：`30` 条，全部 HTTP `200`

### 执行后复查

- `ExternalDataImportRun(status="started")=0`
- HKJC 与 netkeiba 的 `ExternalDataImportLock.locked_by_run_id=None`
- 无 `umanewsbot-web-run-*` 临时容器残留
- `http://umafans.run/healthz/`：`200`
- `http://127.0.0.1/healthz/`：`200`

## 2026-06-30 HKJC 慢速 dry-run 延伸到 2024-07

本次按用户要求把香港 HKJC 慢速抓取窗口延伸到 `2024-07-01`。执行口径仍为 dry-run，不执行生产 `--commit`，不写正式表。

### 长窗口 plan-only

```bash
cd /opt/umanewsbot
mkdir -p runtime/global_racing_import/hkjc-20260701-to-202407
docker compose -f docker-compose.prod.lowcost.yml run --rm --no-deps -T \
  -e HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=8 \
  -e HKJC_IMPORT_MAX_REQUESTS_PER_RUN=600 \
  web python manage.py import_hkjc_external_data \
  --start-date 2024-07-01 \
  --end-date 2026-06-30 \
  --plan-only \
  --limit-races 20 \
  --max-requests 600 \
  --allow-network \
  > runtime/global_racing_import/hkjc-20260701-to-202407/hkjc-plan-20240701-20260630.json
```

结果：

- 输出：`runtime/global_racing_import/hkjc-20260701-to-202407/hkjc-plan-20240701-20260630.json`
- `race_count=1496`
- `batch_count=75`
- `request_count=254`
- `request_statuses={"200":253,"missing":1}`
- 最后一个 plan 批次覆盖 `2024-09-11` 与 `2024-09-08`；`2024-07-01` 至 `2024-09` 之间没有更早的本地 `HV/ST` HKJC 场次进入计划。

### 后台 worker

运行脚本：

```bash
/opt/umanewsbot/runtime/global_racing_import/hkjc-20260701-to-202407/run_hkjc_slow_dryrun_to_202407.sh
```

关键文件：

- PID：`runtime/global_racing_import/hkjc-20260701-to-202407/hkjc-slow-dryrun.pid`
- 状态：`runtime/global_racing_import/hkjc-20260701-to-202407/hkjc-slow-dryrun.state`
- 日志：`runtime/global_racing_import/hkjc-20260701-to-202407/hkjc-slow-dryrun.log`
- 输出：`runtime/global_racing_import/hkjc-20260701-to-202407/hkjc-mini-races-*-dryrun.json`

运行参数：

- 每批 `5` 场
- `HKJC_IMPORT_REQUEST_INTERVAL_SECONDS=8`
- `HKJC_IMPORT_MAX_REQUESTS_PER_RUN=140`
- 批次间暂停 `60` 秒
- 从状态 `2` 开始，跳过已完成的 `HK20260627ST02,HK20260627ST03` 两场证据

### 启动后证据

- `races=3-7/1496`：`completion.is_complete=true`，`coverage_stats={"races":5,"entries":67,"results":67,"horses":67}`，有 `1` 次 horse profile 初始 `ReadTimeout` attempt，但最终 `horse_profiles_fetched=67`。
- `races=8-12/1496`：`completion.is_complete=true`，`coverage_stats={"races":5,"entries":66,"results":66,"horses":66}`，`request_count=71`，`non_200_request_attempts=0`。
- 截至记录时 worker 已进入 `races=13-17/1496`。

### 监控命令

```bash
cd /opt/umanewsbot
OUT_DIR=runtime/global_racing_import/hkjc-20260701-to-202407
cat "$OUT_DIR/hkjc-slow-dryrun.pid"
cat "$OUT_DIR/hkjc-slow-dryrun.state"
tail -40 "$OUT_DIR/hkjc-slow-dryrun.log"
pgrep -af "run_hkjc_slow_dryrun_to_202407|import_hkjc_external_data"
docker ps --format "{{.Names}} {{.Status}}" | grep "umanewsbot-web-run" || true
```

停止 worker：

```bash
cd /opt/umanewsbot
kill "$(cat runtime/global_racing_import/hkjc-20260701-to-202407/hkjc-slow-dryrun.pid)"
```

不要在 worker 运行时执行生产部署、重建容器或修改运行脚本的 `git pull`；需要同步文档时，先推 GitHub，等抓取暂停后再同步生产工作树。

## 多地区新闻常态生产灰度运行手册

本节只覆盖新闻来源常态抓取、自动发布灰度、地区运营观测和 QQ 群推送灰度；HKJC / UK / France / US 外部赛马数据库 importer 仍是独立受控导入，不进入新闻 Celery Beat。

### 启用前只读审计

```bash
cd /opt/umanewsbot
docker compose -f docker-compose.prod.lowcost.yml exec -T web \
  python manage.py audit_multiregion_news_production
```

如需留存基线：

```bash
docker compose -f docker-compose.prod.lowcost.yml exec -T web \
  python manage.py audit_multiregion_news_production \
  --output multiregion-news-baseline-$(date +%Y%m%d_%H%M%S).json
```

该命令只读查询 `NewsSource / CrawlJob / NewsArticle / QQPushDelivery / TermEntry / TermCandidate / ExternalHorseAlias`，不会创建 `CrawlJob`、`NewsArticle`、`QQPushDelivery` 或 `ExternalDataImportRun`。

### 灰度开启顺序

1. 备份 `.env`：

```bash
cp .env .env.backup.multiregion-news-$(date +%Y%m%d_%H%M%S)
```

2. 先只允许少量地区和来源进入通用轮询：

```dotenv
NEWS_SOURCE_POLL_ENABLED=true
NEWS_SOURCE_POLL_INTERVAL_MINUTES=30
NEWS_SOURCE_POLL_MAX_SOURCES=2
NEWS_SOURCE_POLL_ALLOWED_REGIONS=hong_kong,united_kingdom
NEWS_SOURCE_POLL_ALLOWED_SOURCES=hkjc_news:latest,scmp_racing:latest,sporting_life:latest,sky_sports_racing:latest
```

3. 自动发布默认仍保守。非日本地区只有显式配置后才允许自动发布：

```dotenv
MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS=hong_kong
MULTIREGION_AUTO_PUBLISH_ALLOWED_SOURCES=hkjc_news:latest
MULTIREGION_AUTO_PUBLISH_REGION_BATCH_LIMITS=hong_kong:1
MULTIREGION_AUTO_PUBLISH_REGION_DAILY_LIMITS=hong_kong:3
MULTIREGION_TERM_CANDIDATE_BACKLOG_THRESHOLD=50
```

4. QQ 灰度继续以群级 `PushTarget.allowed_regions` 为准。测试群可显式加入 `hong_kong / united_kingdom`，正式群不得因为 `QQ_PUSH_ENABLED=true` 自动接收新地区。

5. 重启 `worker / beat / web` 后观察至少一个自然调度窗口：

```bash
docker compose -f docker-compose.prod.lowcost.yml ps
docker logs --tail=120 umanewsbot-worker-1
docker logs --tail=120 umanewsbot-beat-1
curl -I http://127.0.0.1/healthz/
curl -I http://umafans.run/
```

### 后台验收入口

- `/admin/regions/`：地区生产概览，查看今日新增、待翻译、翻译失败、待审核、自动发布、人工发布、公开数量、近期 QQ 交付和术语候选积压。
- `/admin/sources/?region=hong_kong`：按地区筛选来源健康，确认成功、成功无新增、运行中、运行超时、失败和长时间未运行。
- `/admin/` 首页与公开首页地区 tab：确认后台与前台状态一致。

### 停用和回滚

如任一地区出现来源异常、翻译质量异常、候选池积压或 QQ 推送异常，按风险从小到大收敛：

```dotenv
NEWS_SOURCE_POLL_ENABLED=false
MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS=
MULTIREGION_AUTO_PUBLISH_ALLOWED_SOURCES=
QQ_PUSH_ENABLED=false
```

也可只收窄某个群的 `PushTarget.allowed_regions` 为 `["japan"]`，或在后台停用具体 `NewsSource.enabled`。停用后重新执行只读审计并检查 `worker / beat` 日志，确认没有新的国际来源轮询和异常 QQ 交付。

## 2026-06-30 多地区新闻常态生产部署与归档

### 部署前互斥处理

- 部署前生产服务器 `/opt/umanewsbot` 运行 `main` 的 `7b6e51b`。
- HKJC 长窗口 dry-run worker 正在运行，`runtime/global_racing_import/hkjc-20260701-to-202407/hkjc-slow-dryrun.state=92`，并存在临时 `umanewsbot-web-run-*` 容器。
- 为避免部署与长任务重叠，已先停止 `hkjc-slow-dryrun.pid` 对应 wrapper，并停止临时 `umanewsbot-web-run-*` 容器。
- 暂停后复查：`ExternalDataImportRun(status="started")=0`，HKJC 与 netkeiba 的 `ExternalDataImportLock.locked_by_run_id=None`。

### 部署步骤与结果

- 本地实现提交 `62a0f9a` 已快进推送到 `main`。
- 生产 `.env` 备份：`.env.backup.multiregion-news-20260630_185150`。
- 服务器执行 `git pull --ff-only origin main`，从 `7b6e51b` 更新到 `62a0f9a`。
- 执行 `bash ./deploy_lowcost.sh`，重建 `web / worker / beat`，`db / redis / nginx` 保持运行。
- 迁移已应用：`stable.0014_multiregion_news_indexes`、`stable.0015_termentry_racing_region`。
- `collectstatic` 结果：`0 static files copied`，`129 unmodified`，`360 post-processed`。
- 容器状态：`web` healthy，`db / redis` healthy，`worker / beat` running，`nginx` running。

### 验证结果

- `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check`：通过。
- `python manage.py showmigrations stable`：`0014`、`0015` 均为 `[X]`。
- `http://umafans.run/healthz/`：`200`。
- `http://umafans.run/`：`200`。
- `http://umafans.run/admin/login/`：`200`。
- `http://umafans.run/admin/regions/`：`302` 到 `/admin/login/?next=/admin/regions/`，路由存在且受后台登录保护。
- `python manage.py audit_multiregion_news_production`：只读审计可输出 `japan / hong_kong / united_kingdom / france / united_states` 五个地区；生产设置仍为 `NEWS_SOURCE_POLL_ENABLED=false`，非日本自动发布 allowlist 为空。

### 归档结果

- OpenSpec change：`operate-multiregion-news-production`。
- 归档目录：`openspec/changes/archive/2026-06-30-operate-multiregion-news-production/`。
- 正式规格已同步：
  - `openspec/specs/multiregion-news-production/spec.md`
  - `openspec/specs/crawl-freshness-and-source-health/spec.md`
  - `openspec/specs/automation-publish-gates/spec.md`
  - `openspec/specs/qqbot-auto-push/spec.md`
  - `openspec/specs/termbase-and-race-priority/spec.md`

### 后续注意

- 本次部署只上线能力与安全默认配置，不直接开启通用国际来源轮询。
- 如需继续 HKJC 长窗口 dry-run，应从 `hkjc-slow-dryrun.state=92` 对应进度恢复或重新渲染剩余批次；恢复前再次确认不与部署、重建容器或 `git pull` 重叠。

## 2026-06-30 多地区新闻生产开关开启

### 开启范围

按用户要求开启多地区新闻生产相关开关。本次只调整 `.env` 中多地区新闻生产配置，不恢复 HKJC 长窗口 dry-run，不修改数据库、翻译 Key 或 OneBot token。

备份：

- `.env.backup.enable-all-multiregion-20260630_203647`

当前生产配置：

```dotenv
NEWS_SOURCE_POLL_ENABLED=true
NEWS_SOURCE_POLL_INTERVAL_MINUTES=30
NEWS_SOURCE_POLL_MAX_SOURCES=12
NEWS_SOURCE_POLL_ALLOWED_REGIONS=japan,hong_kong,united_kingdom,france,united_states
NEWS_SOURCE_POLL_ALLOWED_SOURCES=
NEWS_SOURCE_POLL_RUNNING_TIMEOUT_MINUTES=60
NEWS_SOURCE_POLL_RETRY_STALE_RUNNING=false
MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS=hong_kong,united_kingdom,france,united_states
MULTIREGION_AUTO_PUBLISH_ALLOWED_SOURCES=hkjc_news:latest,scmp_racing:latest,sporting_life:latest,sky_sports_racing:latest,sky_sports_racing:access,france_galop_news:official,tdn_france:latest,tdn:latest,horse_racing_nation:latest,horse_racing_nation:access
MULTIREGION_AUTO_PUBLISH_REGION_BATCH_LIMITS=hong_kong:2,united_kingdom:2,france:1,united_states:1
MULTIREGION_AUTO_PUBLISH_REGION_DAILY_LIMITS=hong_kong:5,united_kingdom:5,france:3,united_states:3
MULTIREGION_TERM_CANDIDATE_BACKLOG_THRESHOLD=50
```

### 重启与验证

- 已重启 `web / worker / beat`。
- `manage.py check`：通过。
- `http://127.0.0.1/healthz/`：`200`。
- `http://umafans.run/healthz/`：`200`。
- `http://umafans.run/`：`200`。
- Django settings 确认 `NEWS_SOURCE_POLL_ENABLED=true`，地区与来源 allowlist 已按上述配置生效。

### 通用轮询 smoke

手动执行 `crawl_enabled_news_sources_task.run()` 后，选中并派发 `12` 个 due 来源：

- `sponichi:latest`
- `sponichi:access`
- `hkjc_news:latest`
- `scmp_racing:latest`
- `sky_sports_racing:access`
- `sporting_life:latest`
- `sky_sports_racing:latest`
- `france_galop_news:official`
- `tdn_france:latest`
- `tdn:latest`
- `horse_racing_nation:access`
- `horse_racing_nation:latest`

固定调度来源被正确跳过：

- `netkeiba:latest`
- `netkeiba:access`
- `netkeiba:attention`
- `jra:official`

当前 worker 并发为 `2`，因此 smoke 后先进入 active 的是两个 Sponichi 抓取任务，其余来源会随队列继续消化。

### 快速回滚

如国际来源抓取、翻译、自动发布或 QQ 推送出现异常，优先按以下顺序收敛：

```dotenv
NEWS_SOURCE_POLL_ENABLED=false
MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS=
MULTIREGION_AUTO_PUBLISH_ALLOWED_SOURCES=
QQ_PUSH_ENABLED=false
```

修改 `.env` 后重启 `web / worker / beat`，再执行 `audit_multiregion_news_production` 和日志检查。

## 2026-07-01 全部 OpenSpec 归档与生产部署

### 范围

- 归档 `add-netkeiba-horse-data-import`、`expand-international-racing-coverage`、`guard-qqbot-offline-send`。
- 同步正式规格到 `openspec/specs/external-horse-data-import/`、`openspec/specs/international-racing-coverage/` 及相关能力规格。
- 补齐 `ExternalDataSource` choices：`sporting_life`、`france_galop`、`geny_france`、`horse_racing_nation`。
- 新增并应用迁移 `stable.0016_alter_externaldataimporterror_source_and_more`。

### 本地验证

- `openspec list --json`：`changes=[]`。
- `openspec validate --all`：12 项通过。
- `DB_ENGINE=sqlite python server/manage.py check`：通过。
- `DB_ENGINE=sqlite python server/manage.py makemigrations --check --dry-run`：`No changes detected`。
- `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python server/manage.py test stable --noinput`：362 项通过。
- `git diff --check`：通过。

### 生产部署

部署前检查：

- 服务器 `/opt/umanewsbot` 部署前 HEAD：`538a1a9`。
- `docker compose -f docker-compose.prod.lowcost.yml ps`：`web / db / redis` healthy，`worker / beat / nginx` 运行。
- `ExternalDataImportRun(status="started")=0`。
- `ExternalDataImportLock` 中 HKJC 与 netkeiba 均未占用锁。
- HKJC 长窗口 dry-run 未运行，仍按此前记录暂停在 `hkjc-slow-dryrun.state=92`。

备份：

- `backups/db/pre-archive-all-20260701_153301.sql.gz`
- `gzip -t`：通过。

执行：

```bash
cd /opt/umanewsbot
git fetch origin main
git pull --ff-only origin main
bash ./deploy_lowcost.sh
```

结果：

- 服务器已快进到 `8c83708`。
- `web / worker / beat` 已重建。
- 迁移日志确认 `Applying stable.0016_alter_externaldataimporterror_source_and_more... OK`。
- `collectstatic` 完成，`web` healthy。

### 生产验收

- `docker compose -f docker-compose.prod.lowcost.yml exec -T web python manage.py check`：通过。
- `showmigrations stable`：`0016_alter_externaldataimporterror_source_and_more` 为 `[X]`。
- `ExternalDataSource.values`：`netkeiba / hkjc / sporting_life / france_galop / geny_france / horse_racing_nation`。
- `http://127.0.0.1/healthz/`：`200`。
- `http://umafans.run/healthz/`：`200`。
- `http://umafans.run/`：`200`。
- `http://umafans.run/admin/login/`：`200`。
- `http://umafans.run/admin/regions/`：未登录请求 `302` 到登录页；已登录浏览器可打开地区生产页。
- 浏览器验收：首页地区 tab 正常，香港/英国地区页可渲染已发布国际新闻，后台地区生产页显示五地区来源、今日新增、待审核、公开和 QQ 状态。

### 生产开关与来源状态

当前生产 settings：

```text
NEWS_SOURCE_POLL_ENABLED=True
NEWS_SOURCE_POLL_INTERVAL_MINUTES=30
NEWS_SOURCE_POLL_MAX_SOURCES=12
NEWS_SOURCE_POLL_ALLOWED_REGIONS=japan,hong_kong,united_kingdom,france,united_states
MULTIREGION_AUTO_PUBLISH_ALLOWED_REGIONS=hong_kong,united_kingdom,france,united_states
MULTIREGION_AUTO_PUBLISH_REGION_DAILY_LIMITS=hong_kong:5,united_kingdom:5,france:3,united_states:3
QQ_PUSH_ENABLED=True
QQ_PUSH_SCOPE=high_value_only
QQ_PUSH_IMPORTANCE_STRATEGY=ranked
```

enabled 来源最近状态显示五地区均有来源记录，多数为 `success`。当前仅 `Sponichi 新闻ランキング` 最近一次为上游 `502 Bad Gateway`，其余日本、香港、英国、法国、美国 enabled 来源最近状态为 `success`。该 502 属于来源站点临时响应异常，不阻断本次部署验收。

## 2026-07-01 多地区新闻增量窗口部署注意事项

本节对应 OpenSpec change `increase-multiregion-news-volume`。该变更包含新迁移和新 Celery Beat 项，部署后默认关闭。

### 部署前

1. 备份生产数据库和 `.env`。
2. 确认没有运行中的外部数据 importer、长窗口 dry-run 或手工导入任务。
3. 部署前本地必须通过：

```bash
DB_ENGINE=sqlite python server/manage.py check
DB_ENGINE=sqlite python server/manage.py makemigrations --check --dry-run
DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python server/manage.py test stable.tests.ProductionWindowModelTests stable.tests.ProductionWindowServiceTests stable.tests.PublishWindowServiceTests stable.tests.QQWindowServiceTests --noinput
openspec validate increase-multiregion-news-volume --strict
openspec validate --all
git diff --check
```

### 默认关闭验证

迁移和重启后先确认以下开关仍为关闭：

```dotenv
MULTIREGION_PRODUCTION_WINDOWS_ENABLED=false
MULTIREGION_PRODUCTION_WINDOWS_CRAWL_ENABLED=false
MULTIREGION_PRODUCTION_WINDOWS_PUBLISH_ENABLED=false
MULTIREGION_PRODUCTION_WINDOWS_QQ_ENABLED=false
```

执行只读审计：

```bash
python manage.py audit_multiregion_news_production --output multiregion-window-audit.json
```

重点查看 `settings`、各地区 `sources.production_approved`、`sources.backoff_active`、`production_windows` 和 `quota_exhausted`。

### 启用顺序

建议按以下顺序启用：

1. 标记来源 `production_approved=true`，确认没有高风险或需长间隔来源被误纳入。
2. 设置 `MULTIREGION_PRODUCTION_WINDOWS_ALLOWED_REGIONS=japan,hong_kong,united_kingdom,france,united_states`。
3. 开启总开关和抓取窗口，观察最近 4 个抓取窗口。
4. 开启发布窗口，观察最近 4 个发布窗口，每地区每窗口应为 `0-5` 篇，0 篇必须有 `reason_summary` 或候选决策原因。
5. 开启 QQ 窗口，观察最近 4 个 QQ 窗口，每地区每窗口最多 3 篇，保底文章不应自动 QQ。

### 快速回滚

优先使用分链路回滚：

```dotenv
MULTIREGION_ROLLBACK_DISABLE_CRAWL_WINDOWS=true
MULTIREGION_ROLLBACK_DISABLE_PUBLISH_WINDOWS=true
MULTIREGION_ROLLBACK_DISABLE_QQ_WINDOWS=true
MULTIREGION_ROLLBACK_DISABLE_OPS_NOTIFICATIONS=true
```

如需完全关闭新窗口：

```dotenv
MULTIREGION_PRODUCTION_WINDOWS_ENABLED=false
```

QQ 限流或 OneBot 异常时优先关闭：

```dotenv
MULTIREGION_PRODUCTION_WINDOWS_QQ_ENABLED=false
QQ_PUSH_ENABLED=false
```

## 2026-07-02 多地区新闻增量窗口生产上线记录

本节对应 OpenSpec change `increase-multiregion-news-volume`。

### 部署前检查

- 生产目录：`/opt/umanewsbot`。
- 部署前 `HEAD=80454c6`，`origin/main=b7b0ce0`；上线修复后最终运行 `HEAD=9e97e8c`。
- 外部数据导入锁检查：`hkjc / netkeiba` 均无占用者；未发现运行中的 HKJC/global racing/import 进程。
- 备份：
  - `.env.backup.multiregion-volume-20260702_040811`
  - `backups/db/pre-multiregion-volume-20260702_040811.sql.gz`
  - `gzip -t`：通过。

### 部署与迁移

执行：

```bash
cd /opt/umanewsbot
git pull --ff-only origin main
bash ./deploy_lowcost.sh
```

结果：

- 迁移已应用：
  - `stable.0017_majorraceevent_productionwindow_quotaledger_and_more`
  - `stable.0018_alter_notificationlog_type`
- `web / worker / beat` 已重建并运行。
- `docker compose -f docker-compose.prod.lowcost.yml ps` 显示 `web` healthy，`db / redis` healthy。
- `manage.py check`：通过。
- `http://127.0.0.1/healthz/`：`200`。
- `http://umafans.run/healthz/`：`200`。

### 启用开关

启用前备份 `.env`：

```text
.env.backup.enable-multiregion-volume-20260702_041242
```

当前生产窗口配置：

```dotenv
MULTIREGION_PRODUCTION_WINDOWS_ENABLED=true
MULTIREGION_PRODUCTION_WINDOWS_CRAWL_ENABLED=true
MULTIREGION_PRODUCTION_WINDOWS_PUBLISH_ENABLED=true
MULTIREGION_PRODUCTION_WINDOWS_QQ_ENABLED=true
MULTIREGION_PRODUCTION_WINDOWS_ALLOWED_REGIONS=japan,hong_kong,united_kingdom,france,united_states
MULTIREGION_PRODUCTION_WINDOW_DAILY_MINUTES=15
MULTIREGION_PRODUCTION_WINDOW_MAJOR_RACE_MINUTES=5
MULTIREGION_PRODUCTION_WINDOW_LOOKBACK_HOURS=3
MULTIREGION_CRAWL_DEFAULT_INTERVAL_MINUTES=15
MULTIREGION_PUBLISH_REGION_WINDOW_MAX=5
MULTIREGION_PUBLISH_REGION_WINDOW_MIN=1
MULTIREGION_QQ_REGION_WINDOW_MAX=3
MULTIREGION_OPS_NOTIFICATIONS_ENABLED=true
MULTIREGION_OPS_NOTIFICATION_QQ_GROUP_ID=1026525240
```

当前 16 个启用新闻源均已标记 `production_approved=true`。活跃 QQ 目标为 `UmaFans测试群`，群号 `1026525240`，允许 `japan / hong_kong / united_kingdom / france / united_states`。

### 上线中修复

首次真实抓取窗口暴露问题：`crawl_production_sources_window_task` 把 Celery `AsyncResult` 直接写入 `ProductionWindow.result_payload`，触发 `Object of type AsyncResult is not JSON serializable`。

处理：

1. 临时设置 `MULTIREGION_ROLLBACK_DISABLE_CRAWL_WINDOWS=true`，避免 beat 继续制造失败抓取窗口。
2. 修复代码，将异步派发结果序列化为 `{"task_id": "..."}`。
3. 新增测试 `test_crawl_window_serializes_async_dispatch_result`。
4. 验证：
   - `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable.tests.ProductionWindowServiceTests stable.tests.PublishWindowServiceTests stable.tests.QQWindowServiceTests stable.tests.MultiRegionNewsProductionTests --noinput`：51 项通过。
   - `DB_ENGINE=sqlite python manage.py check`：通过。
   - `git diff --check`：通过。
5. 提交并部署 `9e97e8c Fix crawl window async dispatch payload`。
6. 恢复 `MULTIREGION_ROLLBACK_DISABLE_CRAWL_WINDOWS=false`。

### 生产验收结果

- 默认关闭验证：启用前抓取、发布、QQ 三条窗口任务均返回 `disabled`。
- 生产资格审计：五地区生产窗口开关为开启；批准来源数为日本 6、香港 2、英国 3、法国 2、美国 3。
- 20:15 抓取窗口：15 个 due 来源被派发；最终 14 个成功，1 个失败。
  - 失败来源：`Sponichi 新闻ランキング`
  - 失败原因：上游详情页 `502 Bad Gateway`
- 20:15 发布窗口：
  - 香港：发布 1 篇。
  - 美国：发布 3 篇。
  - 日本、英国、法国：`no_ready_candidates`。
- 20:30 发布窗口：
  - 美国：发布 1 篇。
  - 日本、香港、英国、法国：`no_ready_candidates`。
- 20:15 QQ 窗口：
  - 美国：生成并发送 2 条 delivery。
  - 日本、香港、英国、法国：`no_eligible_articles`。
- 20:30 QQ 窗口：
  - 美国：`already_sent`。
  - 日本、香港、英国、法国：`no_eligible_articles`。
- Celery inspect：`active/reserved` 为空。
- ops 摘要通知：`NotificationLog #13051`，channel=`qq`，target=`1026525240`，status=`sent`。
- 浏览器验收：
  - `http://umafans.run/` 首页正常展示 20:15 窗口新发布的香港和美国文章。
  - `/?region=hong_kong`、`/?region=united_states`、`/?region=japan` 可展示对应地区新闻。
  - 英国、法国地区页可正常渲染，当前本轮无新 ready 候选。

### 继续观察项

- 因上线时间为后半夜新闻低峰，用户确认跳过继续等待 20:45 及后续自然窗口；最近 4 个自然窗口口径改为次日继续验证。
- `Sponichi 新闻ランキング` 当前失败为上游 `502`，如连续失败达到阈值会进入来源 backoff；必要时可在后台单来源暂停或降频。
- `TDN 美国新闻` 每轮最多 20 条列表且详情请求超时为 15 秒，单轮耗时可能偏长；如持续占用 worker，可另起优化将每轮详情数量做成配置或拆分任务。
- 生产构建上下文约 425MB，紧急修复发布时镜像构建前置上传较慢；后续应优化 `.dockerignore`。

### 2026-07-02 白天自然窗口复核

- 生产代码：`a122130`，`origin/main` 同步到同一提交。
- 容器状态：`web / worker / beat / db / redis / nginx` 均运行；`web` 与 `redis / db` healthy。
- 健康检查：
  - `http://127.0.0.1/healthz/`：`200`。
  - `http://umafans.run/healthz/`：`200`。
  - `http://umafans.run/`：`200`。
  - 抽检 `/news/6374/`、`/news/6426/`、`/news/6368/`：均 `200`。
- Celery：`inspect active reserved` 返回空，无积压任务。
- 开关配置：抓取 / 发布 / QQ 生产窗口均为 `true`；允许五地区；日常 `15` 分钟、重要赛事 `5` 分钟；发布每地区每窗口 `1-5` 篇；QQ 每地区每窗口最多 `3` 篇；当前没有地区处于重要赛事升频窗口。
- 最近 6 小时窗口结果：
  - 发布窗口：五地区各 `24` 个窗口。非零发布为美国 `04:30` 1 篇，日本 `04:45` 2 篇、`05:30` 4 篇、`06:30 / 08:15 / 09:45` 各 1 篇；所有非零窗口均未超过 5 篇。
  - 0 发布原因：其余发布窗口均为 `no_ready_candidates`。
  - QQ 窗口：五地区各 `24` 个窗口。实际发送 6 条，美国 3 条、日本 3 条，目标均为 `UmaFans测试群(1026525240)`；其余窗口为 `no_eligible_articles` 或 `already_sent`。
  - 抓取窗口：`succeeded/completed=260`，`skipped/coalesced_to_latest_crawl_window=109`，后者符合停机 / 延迟恢复时只补最近窗口的设计。
  - 来源状态：16 个 `enabled=true` 且 `production_approved=true` 来源最新抓取均为 `success`；`TDN France Galop 关键词英文新闻` 和 `TDN 美国新闻` 仍显示已过期 `backoff_until`，但最新抓取窗口已成功完成，当前不影响运行。
- 结论：白天最近几个自然窗口满足本期诉求：五地区窗口按 15 分钟节奏产生，发布 / QQ 上限未突破，0 结果有明确原因，生产服务和队列健康。

### 2026-07-02 11:07 最新窗口按地区拆因

- 复核口径：最新 4 个发布窗口（`10:15 / 10:30 / 10:45 / 11:00`，CST）+ 发布候选 3 小时回看。
- 五地区最新 4 个发布窗口均为 `succeeded / no_ready_candidates`，均未发布新文章。
- 日本：
  - 最近 4 个发布窗口共有 `18` 条候选决策，全部为 `blocked / hard_gate_blocked`。
  - 主要原因：部分文章翻译失败；部分文章进入 `manual_review_required`；高分候选中存在 `core_term_missing` 和轻微数字缺失提示。
  - 结论：日本不是新闻源无内容，也不是抓取整体失效；主因是抓到的候选未通过自动发布门禁或需要人工处理。
- 中国香港：
  - `HKJC Racing News` 与 `SCMP Racing` 最近 3 小时抓取均成功，最新消息分别为 `新增 0，重复 5`、`新增 0，重复 4`。
  - 最近 3 小时没有新入库香港文章，也没有发布候选。
  - 结论：主因是来源没有新稿，只有重复旧稿。
- 英国：
  - `Sporting Life Racing`、`Sky Sports Racing 新闻`、`Sky Sports Racing Top Stories` 最近 3 小时抓取均成功，最新消息为新增 0、重复旧稿。
  - 最近 3 小时没有新入库英国文章，也没有发布候选。
  - 结论：主因是来源没有新稿，只有重复旧稿。
- 法国：
  - `France Galop 英文新闻` 最近抓取成功，新增 0、重复 20。
  - `TDN France Galop 关键词英文新闻` 在 `08:25-09:05` 出现过 `525` / read timeout，`10:10` 已恢复成功，`failure_streak=0`，最新消息为 `新增 0，重复 20`。
  - 最近 3 小时没有新入库法国文章，也没有发布候选。
  - 结论：当前主因是来源没有新稿；早间 TDN 短暂失败已恢复，不是最新窗口 0 发布主因。
- 美国：
  - `Horse Racing Nation 新闻` 与 `Horse Racing Nation Trending` 最近抓取成功，新增 0、重复旧稿。
  - `TDN 美国新闻` 在 `08:25-09:05` 出现过 read timeout，`10:10` 已恢复成功，`failure_streak=0`，最新消息为 `新增 0，重复 20`。
  - 最近 3 小时没有新入库美国文章，也没有发布候选。
  - 结论：当前主因是来源没有新稿；早间 TDN 短暂失败已恢复，不是最新窗口 0 发布主因。

## 多地区归属与英文门禁上线检查

适用 change：`support-multiregion-news-attribution-and-english-gates`。

上线前：

1. 备份生产数据库。
2. 确认待部署代码包含迁移 `stable.0023_multiregion_news_attribution`，并依赖已上线的 `stable.0022_horseprofile_horsefollow_articlehorselink_and_more`。
3. 本地或 CI 需通过：
   - `DB_ENGINE=sqlite .venv/bin/python server/manage.py check`
   - `.venv/bin/python server/manage.py makemigrations --check --dry-run`
   - `.venv/bin/python server/manage.py test stable.tests.MultiRegionAttributionAndGateTests stable.tests.IngestionSourceElevationTests stable.tests.InternationalSourceMetadataTests stable.tests.MultiRegionNewsProductionTests stable.tests.TermRegionFilterTests stable.tests.QQAutoPushTests stable.tests.QQWindowServiceTests stable.tests.PublishWindowServiceTests --keepdb`
   - `openspec validate support-multiregion-news-attribution-and-english-gates --strict`
4. 如本地没有 `.env`，`docker compose ... config` 可临时复制 `.env.example` 为 `.env`，校验后立即删除。

上线后：

1. 执行迁移并确认：
   - `.venv/bin/python server/manage.py showmigrations stable | grep 0022`
2. 先 dry-run 重算近期英文门禁文章：
   - `.venv/bin/python server/manage.py reprocess_multiregion_attribution_gates --region france --hours 6 --dry-run --json`
   - `.venv/bin/python server/manage.py reprocess_multiregion_attribution_gates --region united_kingdom --hours 6 --dry-run --json`
   - `.venv/bin/python server/manage.py reprocess_multiregion_attribution_gates --region hong_kong --hours 6 --dry-run --json`
3. 抽样确认 `old_regions / new_regions / inferred_regions / attribution_locked / attribution_applied / blockers` 符合预期后，再按地区小批量 commit。人工锁定文章应保持 `attribution_applied=false`，且 `new_regions` 代表 commit 实际会使用的地区；`scanned_count / candidate_count / has_more_candidates` 用于判断是否需要继续分批，`--limit` 按有效候选数量计算。commit 只恢复候选，不直接发布。
4. 验收公开页：
   - `/`
   - `/?region=france`
   - `/?region=united_kingdom`
   - 抽样文章详情页确认地区标签显示多个地区。
   - 确认主地区单独显示且关联地区不会排在主地区之前；文章编辑页取消全部关联地区后可保存为空。
5. 验收窗口审计：
   - `audit_multiregion_news_production --json` 中确认 `primary_total / related_visible_total`、发布 0 原因、QQ 0 原因正常。
6. 回滚时可先设置：
   - `MULTIREGION_ATTRIBUTION_ENABLED=false`
   - `MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false`
   - 必要时收窄 `MULTIREGION_QQ_ALLOWED_CONTENT_CATEGORIES`

`MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false` 必须同时让公开地区 tab、公开列表卡片/文章详情地区展示、发布窗口、QQ 窗口和文章发布后的 QQ 即时任务只使用主地区；关联地区数据不删除。验收回滚配置时至少用一篇“英国主地区 + 法国关联地区”文章确认：法国群返回 `region_not_allowed`，首页卡片和文章详情不显示法国关联地区。

迁移回滚一般不建议删除 `NewsArticleRelatedRegion` 表；代码回滚后该表可闲置，不影响旧主地区逻辑。

### 2026-07-02 15:10 最近 2 小时窗口复核

- 复核口径：`13:15` 至 `15:00` 自然窗口，服务器时区 CST。
- 发布窗口：五地区每 15 分钟均生成窗口且状态为 `succeeded`；本时段网页发布 `0` 篇，原因均为 `no_ready_candidates`。
- QQ 窗口：五地区每 15 分钟均生成窗口且状态为 `succeeded`；本时段 QQ delivery `0` 条，原因均为 `no_eligible_articles`。
- 抓取窗口：最近 2 小时新入库 `8` 篇，按地区为日本 `5`、香港 `1`、英国 `2`、法国 `0`、美国 `0`；其中日本存在翻译失败稿，其他候选多为 `manual_review_required / pending_review`，未达到自动发布条件。
- 来源状态：16 个生产批准来源中 14 个最新抓取为 `success`；`TDN France Galop 关键词英文新闻` 与 `TDN 美国新闻` 在 `15:02` 各出现一次 read timeout，`failure_streak=1`，属于同一上游站短时超时。
- 结论：窗口调度、发布和 QQ 链路正常运转；当前 0 发布不是系统停摆，而是候选未通过自动发布资格或来源暂无新稿。后续可改进 `WindowCandidateDecision.payload`，在 `hard_gate_blocked` 时写入更具体的 blocker 明细，降低排障成本。

### 2026-07-03 00:13 今日窗口复核

- 复核口径：`2026-07-03 00:00` 至 `00:13`，服务器时区 CST；因刚过零点，今日目前只有 `00:00` 一个自然窗口。
- 抓取窗口：五地区均成功。日本 `5` 个来源新增 `0`、重复 `274`；香港 `2` 个来源新增 `0`、重复 `9`；英国 `3` 个来源新增 `0`、重复 `42`；法国 `2` 个来源新增 `0`、重复 `40`；美国 `3` 个来源新增 `1`、重复 `47`。
- 新入库文章：美国 TDN 新闻 `article_id=6500`，标题 `Book'em Danno Day Scheduled For July 17 At Monmouth Park`，已翻译，当前 `manual_review_required / pending_review`，未自动发布。
- 发布窗口：五地区均 `succeeded`，网页发布 `0` 篇，原因均为 `no_ready_candidates`；日本有 `2` 条 blocked 候选、英国 `4` 条、美国 `4` 条。
- QQ 窗口：五地区均 `succeeded`，delivery `0` 条；日本 / 美国原因 `already_sent`，香港 / 英国 / 法国原因 `no_eligible_articles`。
- 来源状态：16 个生产批准来源最新抓取均为 `success`，前一日 TDN France / TDN 美国 read timeout 已恢复。
- 结论：今日首个窗口调度正常，暂无发布不是系统问题；需要继续等更多自然窗口累积样本。

### 2026-07-03 复核 2026-07-02 全日窗口

- 复核口径：`2026-07-02 00:00-24:00`，服务器时区 CST。多地区生产窗口昨日从 `04:00` 开始有账本，因此实际覆盖 `04:00-23:45` 共 `80` 个 15 分钟窗口起点。
- 发布窗口：
  - 五地区各 `80` 个窗口，全部 `succeeded`，无 `failed / partial`。
  - 窗口发布：日本 `37` 篇、香港 `1` 篇、美国 `10` 篇、英国 `0`、法国 `0`。
  - 非零发布窗口均未超过每地区每窗口 `5` 篇；0 发布主因是 `no_ready_candidates`。候选决策中日本 `576` 条、香港 `45` 条、英国 `68` 条、法国 `11` 条、美国 `157` 条为 `hard_gate_blocked`。
- QQ 窗口：
  - 五地区各 `80` 个窗口，全部 `succeeded`，无 `failed / partial`。
  - 窗口派发：日本 `3` 条、美国 `5` 条，香港 / 英国 / 法国为 `0`；无 failed delivery。
  - 昨日 `QQPushDelivery` 记录按创建时间统计为日本 `15` 条、美国 `9` 条，全部 `sent`；窗口内较多 `already_sent` 表示推送记录已由发布触发链路创建并发送，不是 QQ 失败。
- 抓取窗口：
  - 抓取窗口无 `failed`。按窗口 payload 统计新增：日本 `79`、香港 `5`、英国 `11`、法国 `1`、美国 `28`。
  - 日本出现 `7` 次榜单唤醒，说明 `ranked_revived_at` 链路已有生产命中。
  - `coalesced_to_latest_crawl_window` 为恢复 / 延迟场景下只补最近窗口的预期跳过；昨日也记录了 Sponichi 上游 `502`、TDN read timeout / 525 等上游短时异常，但最终截至 `2026-07-03 00:13`，16 个生产批准来源最新状态均为 `success`。
- 文章口径：
  - 昨日新入库：日本 `93`、香港 `6`、英国 `13`、法国 `1`、美国 `37`。
  - 昨日按 `published_to_web_at` 统计公开：日本 `38`、香港 `1`、美国 `13`、英国 `0`、法国 `0`；该口径包含窗口外或已存在文章后续公开，因此与窗口直接发布数略有差异。
- 结论：昨日窗口健康。发布 / QQ 调度成功率为 100%，没有窗口级失败；发布量没有超上限，QQ 没有失败；主要限制是候选质量与门禁，英国 / 法国仍没有自动发布成功。

### 2026-07-03 地区归属错配只读审计

- 复核问题：当前文章地区完全按新闻源地区写入；用户提出两类更合理逻辑：
  - 第一种：新闻源地区与马 / 骑手 / 赛事任一实体地区一致时按新闻源地区；若实体全为另一地区则按该地区；若实体均非新闻源且互不相同，则按赛事、马、骑手优先级归属。
  - 第二种：马 / 骑手 / 赛事涉及多个地区时，文章应属于全部涉及地区。
- 当前字段状态：
  - `NewsArticle.racing_region` 与 `source_config.racing_region` 完全一致：`6598/6598`，现有逻辑确认为“完全按新闻源地区”。
  - 生产 `TermEntry.racing_region` 目前没有可用实体地区：马 `1884`、赛事 `153`、骑手 `2` 均为空地区。
  - `MajorRaceEvent` 当前为空。
  - 外部缓存实体地区主要只有日本：`ExternalHorseAlias` 日本 `12421` 条，香港 `4` 条；英法美外部马名 / 赛事 proof 尚未写入正式缓存表。
- 严格结构化审计结果：
  - 有明确实体地区证据的文章：`462/6598`，且全部为当前日本文章。
  - 按第一种逻辑推断错配：`0`。
  - 按第二种逻辑推断单地区不完整或错配：`0`。
  - `2026-06-30` 以来：`544` 篇中有实体地区证据 `214` 篇，错配 `0`。
  - `2026-07-02`：`150` 篇中有实体地区证据 `49` 篇，错配 `0`。
- 限制与风险：
  - 上述 `0` 是“当前结构化数据能证明的下限”，不能说明真实业务没有错配。
  - 非日本文章的 `translation_metadata.terms / recognized_horse_names` 当前基本为空；英文来源中出现的 `Yutaka Take / Japan Cup / Forever Young / Royal Ascot / Arc` 等实体，没有稳定地区识别。
  - 关键词粗扫发现 `1213` 篇疑似跨地区提及，其中 `2026-06-30` 以来 `231` 篇、`2026-07-02` `60` 篇；该口径噪声较高，只能作为后续设计实体地区识别的参考线索。
- 结论：当前没有结构化证据显示已入库文章违反第一种或第二种逻辑，但这是因为实体地区识别底座不足。若要真正按第一种或第二种逻辑运行，需要先补齐马 / 骑手 / 赛事地区维表与英文别名识别，再把文章从单 `racing_region` 升级为“主地区 + 涉及地区集合”或等价索引。

### 2026-07-02 榜单唤醒未发布文章上线准备

- 变更：`revive-ranked-news-for-publish`。
- 状态：已完成、归档并部署生产。
- 数据库迁移：新增 `server/stable/migrations/0019_newsarticle_ranked_revived_at.py`，为 `NewsArticle` 增加 nullable/indexed `ranked_revived_at` 字段；历史文章默认 `NULL`，不回填。
- 部署记录：
  - 本地提交 `a774672` 已推送到 `origin/main`，服务器 `/opt/umanewsbot` 从 `a122130` 快进到 `a774672`。
  - 部署前备份 `.env`：`.env.backup.ranked-revival-20260702_145529`。
  - 部署前数据库备份：`backups/db/pre-ranked-revival-20260702_145529.sql.gz`，已执行 `gzip -t` 校验。
  - 执行 `bash ./deploy_lowcost.sh` 成功，`web / worker / beat` 已重建，`db / redis / nginx` 正常。
  - `showmigrations stable` 确认 `[X] 0019_newsarticle_ranked_revived_at`。
  - `manage.py check` 通过；生产 shell 确认 `NewsArticle.ranked_revived_at` 为 `null=True db_index=True`，`revive_article_after_ranked_source_elevation` 可 import。
  - `http://127.0.0.1/healthz/` 返回 `{"status":"ok"}`，`http://umafans.run/healthz/`、首页和 `/admin/login/` 均返回 `200`。
  - Celery `active/reserved` 为空，`web / worker / beat` 近 80 行日志未见 traceback/error。
- 后续观察：
  1. 观察最近发布窗口的 `WindowCandidateDecision.payload.ranked_revival`、翻译重试任务、重新评分结果和 QQ delivery。
  2. 当新着顺旧稿后续进入榜单时，确认未发布文章走“重试翻译 / 重新评分 / 发布窗口候选”链路，而不是直接发布或直接 QQ 推送。
- 回滚边界：如需回滚代码，`ranked_revived_at` 字段可留存不用，不影响旧逻辑；如需删除字段，后续单独做清理迁移。

### 2026-07-11 赛事历史抓取证据链验收步骤

1. 先运行 plan 阶段，检查 `<run>/expected_targets.json` 和 `review/expected_targets_review.csv`；不得直接修改应到 JSON。
2. 审核无误后编辑固定的 `review/expected_targets_approval.json`，把 `status` 设为 `approved`，填写 `approved_by / approved_at`，并保持其中 `expected_targets_identity.sha256` 与当前文件一致。
3. 只有审批通过后才允许网络 prepare。确认 `<run>/input/events_<region>.csv` 仅包含该地区本次计划目标；不要把工作区共享 `events.csv` 复制进 run 目录代替生成文件。
4. coverage 必须无 blocker；重点检查 `series_needs_review`、`empty_<module>`、`source_url_missing` 和应到/实到差异。
5. apply-check 前准备真实数据库 gzip 备份。工具会完整读取并解压校验，手工写 `backup_gzip_test=passed` 不能替代真实文件。
6. 每个实际 `region + source + modules` 确认记录必须包含 `status=approved`、`confirmed_by`、`confirmed_at`；coverage、dry-run、当前应到清单和批准候选的 SHA-256 必须一致。
7. 只执行 apply-check 生成、带 `--expected-sha256` 的 importer 命令。任何 blocker 出现时重新生成相应证据，不得手改 apply-check 结果绕过。

本轮只完成本地实现与测试，未执行生产赛事抓取或写入。多地区新闻迁移编号为 `stable.0023_multiregion_news_attribution`，部署时必须先确认 `stable.0022_horseprofile_horsefollow_articlehorselink_and_more` 已应用。

第六轮返修补充：

- prepare 会比较当前 `RaceEvent` 与批准快照中的完整 adapter 输入。出现 `changed after approval` 时不要修改快照或 CSV，应删除本次未执行的 run artifact，重新运行 plan 并重新审批。
- importer 的候选保存和 apply 已整批事务化；命令失败后应先确认本批候选和正式赛事数据均未变化，再修正输入重跑。
- 混合来源策略确认必须由 `status=approved` 且带批准人、批准时间的记录提供；pending 记录中的策略 SHA 不生效。
- 当前仍按手动单进程方式执行同一 run，不要同时启动两个 prepare/resume。`--expected-sha256` 保持兼容性可选，但规范批量流程仍只使用 apply-check 生成的命令。

### 2026-07-11 赛事编排与多地区归属灰度部署记录

- 发布提交：`38974f1`；部署前生产提交：`de4bb78`。
- 环境备份：`.env.backup.multiregion-orchestration-20260711_034313`。
- 数据库备份：`backups/db/pre-multiregion-orchestration-20260711_034313.sql.gz`，约 `101M`，`gzip -t` 通过。
- 迁移：`stable.0023_multiregion_news_attribution` 已应用，`NewsArticleRelatedRegion=0`，未回填旧文章。
- 灰度开关：`MULTIREGION_ATTRIBUTION_ENABLED=false`、`MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false`。
- 五地区只读验收 artifact：`runtime/deployment_acceptance/multiregion-20260711_0352-enabled-dry-run/`。命令仅对子进程临时设置两个开关为 true，没有修改 web/worker/beat 的运行配置。
- 验收结论：英文门禁继续保留 blocker，没有候选被直接发布；但法国样本 `7031` 被推断为英国主地区，日本样本也出现改为中国香港，且部分样本关联三至四个地区。归属产品口径未通过，不得开启生产开关或执行 commit。
- 赛事编排命令已部署并通过 `--help` smoke；本次未运行网络 prepare、未执行赛事 apply。
- 部署后：六个容器正常，Django check 通过；本地和 Host `/healthz/` 正常；首页、法国/英国地区页、后台登录均为 `200`；web/worker 近 15 分钟未见 error/traceback。

后续启用前必须先完成：

1. 产品确认主地区是否允许被弱实体信号覆盖，以及赛事、马、骑手、来源之间的优先级。
2. 产品确认关联地区上限，避免普通文章一次进入三至四个地区池。
3. 修正规则后重新执行五地区真实文章 dry-run，并人工抽检 `old_regions / new_regions / blockers`。
4. 五地区均通过后才修改 `.env` 开关并重建 web/worker/beat；仍先保持 `--commit` 禁止，观察自然新稿后再决定历史回填。

### 2026-07-11 赛事编排归档与归属短路热修复上线

- 生产发布提交：`6e2cc92`；本次更新前生产提交：`87ac1b2`。
- 上线前停止 beat 防止继续派发，确认没有运行中的外部数据导入；停止旧 worker 后不 purge Redis 队列，使未确认任务由新 worker 恢复处理。
- 环境备份：`.env.backup.orchestration-hotfix-20260711_093556`。
- 数据库备份：`backups/db/pre-orchestration-hotfix-20260711_093556.sql.gz`，约 `102M`，`gzip -t` 通过。
- 执行 `bash ./deploy_lowcost.sh` 成功；无新增迁移，`stable.0023_multiregion_news_attribution` 保持已应用。web、worker、beat 已按新镜像重建，db、redis、nginx 正常。
- 上线过程中发现归属功能关闭时 `apply_article_attribution()` 仍先执行完整术语扫描，造成两个 crawl worker 子进程长时间高 CPU。提交 `6e2cc92` 将功能关闭和人工锁定场景前置短路；本地完整 `stable` 测试 `591` 项通过。
- 生产只读验证使用现有文章调用 `apply_article_attribution(save=False)`，并 mock `infer_article_attribution()`：结果为 `attribution_disabled` 且 mock 未被调用。worker CPU 后续降至约 `0.04%`；抓取积压已处理，Celery reserved 为空，仅观察到正常术语发现任务；近 10 分钟日志无 traceback/error。
- 外部数据导入锁表保留 `hkjc / netkeiba` 两条来源记录，但 `locked_by_run_id` 和 `acquired_at` 均为空，不是持有中的锁；运行中导入为 `0`。
- 接口验收：本机与公网 `/healthz/`、`/`、`/?region=france`、`/?region=united_kingdom`、`/races/`、`/admin/login/` 均返回 `200`。
- 浏览器验收：应用内浏览器真实打开首页、法国频道、英国频道、赛事日历和后台登录页；页面标题、地区导航、新闻列表、赛事表格和登录控件均正常渲染。
- 生产开关继续保持 `MULTIREGION_ATTRIBUTION_ENABLED=false`、`MULTIREGION_RELATED_REGION_QUERIES_ENABLED=false`。`support-multiregion-news-attribution-and-english-gates` 的五地区产品抽样仍未通过，任务 `9.6` 不得勾选；本次未执行 `reprocess_multiregion_attribution_gates --commit`，也未执行赛事网络 prepare/apply。

### 2026-07-11 第一批赛事应到清单

- 生产 run：`runtime/race_event_crawl_runs/first-acceptance-race-event-crawl-20260711/`。
- 本地审核副本：同路径同步到本地工作区，运行产物由 `.gitignore` 排除。
- 审核 CSV：`review/expected_targets_review.csv`；审批文件：`review/expected_targets_approval.json`。
- 范围：日本、香港、英国、法国、美国各 1 场已完赛核心赛事，三模块均为 `runners / results / history_winners`。
- 结果：`expected_targets=5`，五地区齐全，全部 `preflight_status=ready`；审批状态为 `pending`。
- 本次 `allow_network=false`，只执行 `plan`，没有网络请求、候选生成或数据库赛事详情写入。
- 原 fixture 中香港杯、凯旋门和简短肯塔基德比种子包含未来赛事或空壳展示行；本批改用生产中已完赛且已有三模块基线的正式赛事行，以便后续验证抓取差异和覆盖保护。
- 用户确认 CSV 中赛事原名、中文名、年份、地区和 slug 前，不得批准应到清单或进入网络 `prepare`。

首批 prepare 前镜像检查：

- `Dockerfile` 必须把 `runtime/tools` 复制到 `/app/runtime/tools`，并让 `/app/server/runtime` 符号链接到 `/app/runtime`；Django 与 AdapterRunner 必须看到同一个 run 根目录。`.dockerignore` 只放行工具目录，仍排除 plans、runs、抓取缓存和其他 runtime artifact。
- 部署后同时检查 `/app/runtime/tools/race_event_request_budget.py` 和 `/app/server/runtime/tools/race_event_request_budget.py`，并逐项检查 plan 中注册 adapter 的脚本存在，再恢复 network run。
- 该检查只确认执行文件可用，不代表允许绕过应到审批、请求预算、coverage、dry-run 或 apply-check。

首批网络抓取 v2 与 v3 处理：

- v2 prepare 共生成 9 条 adapter 候选，请求计数 `49/60`；coverage 为 `blocked`，完整地区为香港、英国、法国，日本和美国不完整，因此未运行 dry-run、apply-check 或正式写入。
- 日本阻断原因是 `prepare_jra_race_detail_candidates.py` 以前按列表序号绑定结果页。单赛事子集会误取 JRA 全年列表第一场，本次把日本德比错配成中山金杯。修复后必须按 `original_name / aliases` 在列表行文本中唯一匹配；零个或多个匹配都直接失败。
- 美国采用明确的混合来源策略：HRN 提供参赛名单，Equibase PDF 提供正式赛果，TOBA 年度分级赛页面提供历届冠军。TOBA 线上 2023-2026 页面当前返回 403，v3 使用此前已成功抓取并留存的同源原始页面；不得手工拼写候选数据。
- v3 与用户批准的五场应到清单逐字段一致，只新增 `us_equibase_results` adapter。prepare 前复用缓存后仍须重新生成候选、运行 mixed-source coverage audit，并确认五个地区的 `runners / results / history_winners` 全部完整；审计未通过时继续禁止 dry-run 和写库。
- adapter 镜像 smoke 不只检查脚本文件存在和 `py_compile`；还要逐项 import 非主应用依赖。Equibase PDF adapter 需要 `pdfplumber==0.11.9`，生产镜像必须通过 `python -c 'import pdfplumber'` 后才允许 resume。
- v3 空缓存重抓在法国探测阶段用尽 `60/60` 请求预算，HRN 因此先生成空候选；不提高预算，改为补入此前留存的同源 HRN 日期页和 Churchill Downs 赛场页。resume 后 HRN 得到 24 匹参赛马且无新增请求，再继续 Equibase 和 TOBA。
- mixed-source coverage 中，声明了模块但 `items=[]` 的候选不得与另一条非空候选形成 `duplicate_candidate`，也不得覆盖非空候选做现有数据完整度比较或 apply scope；如果该模块没有任何非空替代来源，仍必须报告 `empty_<module>`。本规则用于 HRN 空赛果与 Equibase 18 条正式赛果组合。
- 法国 Wikipedia 历史 adapter 在请求预算耗尽后产出空文件时，使用同一历史批次留存的 `source_wiki_search_prix_de_diane_longines.json` 与 `source_wiki_page_prix_de_diane.html` 恢复；仍由原 adapter 重新解析，不直接复制候选 JSONL。
- 当前 adapter canonical query 为 `Prix de Diane`，原搜索缓存请求为同赛事 `Prix de Diane Longines`；保留原文件并以完全相同 SHA-256 建立 `source_wiki_search_prix_de_diane.json` 缓存别名，两个原始证据一并留存。
- aggregate 生成正式 `combined_candidates.jsonl` 时必须剔除显式 `items=[]` 模块；若一条记录剔除后没有模块，则整条不进入 combined 文件。每次该规则变化后必须重新计算 candidate identity、coverage 和 dry-run，不得沿用旧 apply-check 证据。
- `candidate_less_complete` 不只比较行数，还必须逐模块比较关键字段非空数量；候选总行数相同但会把已有练马师、骑手、完赛时间等字段覆盖为空时，同样阻断 apply 并在 blocker 写入 `field_completeness_regressions`。
- JRA 重赏年度列表不含练马师和完赛时间；`jra_history_winners` 必须依赖同批 `jra_detail`，用当届冠军赛果补齐这些字段并保留 `current_result` 来源。第一批真实缓存 smoke 应确认 2026 日本德比历史冠军为 `ロブチェン / 杉山 晴紀 / 2:22.7`。
- 第一批最终证据：候选 SHA-256 `2dd40a141219f7fd39799b7f586efb862f2332e8e037e4091f46c88bee48eac5`；coverage `passed / 5/5 / blocker=0`；dry-run `events=11 / modules=15 / runners=75 / results=64 / history_winners=47`；请求数 `60`。正式 apply 前必须取得八个实际地区/来源/module scope 的人工确认、法国和美国 mixed-source strategy SHA 确认，以及字段 diff review 批准。
- 2026-07-12 用户确认后 apply-check 通过，八个 scope、两个 mixed-source strategy、候选/coverage/dry-run 身份和数据库备份均一致；锁定候选命令执行 `candidates=15 / applied=15`。写前目标计数 `75 / 64 / 46`，写后 `75 / 64 / 47`，最新 15 个候选全部 applied。备份：`backups/db/pre-first-race-crawl-apply-20260712_000116.sql.gz`，约 `105M`，SHA-256 `48a87f2d8941ba09ab24076d4813b27d0729b2c8e3a7b5752a6a3144b8eb703f`，`gzip -t` 通过。

### 2026-07-11 国际新闻门禁与产量验收

- 最近 24 小时英文新稿 `50`、公开 `15`、存在 `core_term_missing` 的文章 `25`。普通词降级已有生产命中，但错误登记为 `horse` 的普通词会被 `horse_term_without_common_seed` 强制判为 proper noun，仍可误挡发布。
- 最近 24 小时地区新增/公开：日本 `114/21`、香港 `3/0`、英国 `12/2`、法国 `1/0`、美国 `34/13`。所有启用来源最新抓取均成功；香港/法国低产主要是有效新稿不足、翻译失败和门禁待审核，不是全局抓取调度停摆。
- 当前启用且生产批准来源数：日本 `6`、香港 `2`、英国 `3`、法国 `3`、美国 `3`。法国宽关键词 TDN 源最近 24 小时新增 `0`，At The Races 法国源仍关闭；后续国际扩源尚未落地。
- 禁止直接在生产批量执行 `reprocess_term_gate_blocked_articles`：本次发现 `--limit 5 --dry-run` 仍会长时间占用单核。若需复验，先在代码侧优化术语匹配/缓存和候选边界，在隔离环境做性能测试，再使用生产只读小样本。
- 本次误启动的重处理进程已全部终止，web CPU 恢复、`/healthz/` 返回 `200`。验收过程中并行赛事 adapter 部署重建 web/worker/beat，17:15 抓取窗口短暂中断后继续排空；该部署不改变上述 24 小时新闻验收结论。
# 2026-07-12 赛事名称中文展示与出马表排序上线

- 部署提交：`d071952`。
- 产品行为：赛事详情、历史冠军和赛事日历赛果中的马名/骑师名精确命中 active 正式术语主原文或别名时展示中文译名；未命中保留原文。出马表按马号自然升序，缺号回退闸位，赛果仍按完赛名次。
- 本地验证：赛事页目标测试 `23` 项、完整 `stable` 回归 `612` 项、Django check、迁移漂移、OpenSpec 严格校验和 `git diff --check` 全部通过。
- 部署前生产 HEAD：`8fbc6c6`；外部导入、外部锁和抓取中任务均为 `0`，内外 healthz 正常。
- `.env` 备份：`.env.backup.race-display-20260712_002533`。
- 数据库备份：`backups/db/pre-race-display-20260712_002533.sql.gz`，约 `105M`，已通过 `gzip -t`；SHA-256 为 `99994e84d3154dd9d4c1503b96688cd24bf7e00d9ad13aca02a965a69d64a8c0`。
- 部署方式：生产 `git pull --ff-only origin main` 快进到 `d071952`，执行 `bash ./deploy_lowcost.sh`；无新增迁移。
- 部署后：`web / worker / beat / db / redis / nginx` 正常，web/db/redis healthy；Django check、内外 healthz、`/races/` 和日本德比详情均通过，近 5 分钟日志无 traceback/error。
- 数据抽检：英国马名 `13/13`、骑师 `9/13` 命中；美国马名 `2/18`、骑师 `11/18`；法国马名 `1/7`、骑师 `0/7`；日本德比马名 `1/18`、骑师 `0/18`。日本当前页面大量原文属于术语库覆盖缺口，不应通过页面层临时翻译解决。

## 2026-07-12 历史赛事回填安全门禁

- 默认配置必须保持：`HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`。
- 保守预算默认值：单 run 请求预算 `250`、source cache 上限 `2147483648` bytes、启动前最小剩余磁盘 `5368709120` bytes。plan 只能声明更小或相等的请求/cache 上限，磁盘不足时 fail closed。
- 离线 plan 命令可在功能关闭时执行：`python server/manage.py build_historical_race_inventory --catalog-jsonl <catalog.jsonl> --timeline-jsonl <timeline.jsonl> --output-dir <artifact-dir>`。它只生成审核文件，不写数据库、不发网络请求。
- 官方 source cache 先使用 `python server/manage.py parse_historical_race_catalog --source-manifest <manifest.json> [--source-manifest ...] --output-dir <candidate-dir>` 离线生成 `catalog_candidate.jsonl` 和 `series_timeline_candidate.jsonl`；manifest 必须绑定 provider、支持年份、source URL、cache SHA-256 和 parser version，输出目录必须为空。`server/stable/fixtures/historical_race_catalog/` 只是解析测试摘录，禁止作为生产完整目录审批依据。
- inventory commit 必须使用既有 artifact，禁止边生成边写：`python server/manage.py build_historical_race_inventory --artifact-dir <artifact-dir> --approval <artifact-dir/approval.json> --commit`。执行前必须人工核对 conflict=0、review、summary、manifest SHA 和 approval 的批准人/时间。
- 首次部署只允许空模型与只读工具：先备份数据库，执行迁移和 `manage.py check`，检查旧赛事 URL/页面，再检查只读总账后台。不得在同一步开启历史功能、网络或提交总账。
- 网络 prepare 还必须同时满足：功能开关开启、网络总开关开启、plan `allow_network=true`、应到 artifact 已批准、共享请求预算有效、source cache/磁盘预检通过。任一条件缺失不得启动 adapter。
- 代码、全量测试、clean review、生产迁移和 2026 mapping 已完成；后续逐年目录和历史详情仍必须继续遵守本节门禁。
- 用户已授权在上述准备门禁全部通过后自主执行生产抓取和落库。执行期间可临时开启功能/网络开关；每批完成或中止后必须恢复 `HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`，并确认历史年度赛事没有被意外公开。
- `RACE_EVENT_PUBLIC_CACHE_SECONDS` 默认 `300` 秒，生产 `RACE_EVENT_CACHE_URL` 应指向共享 Redis（建议独立 DB，例如 `redis://redis:6379/2`）；测试使用 LocMem。赛事或历史总账状态变更会主动清理 sitemap 数量和赛事年份缓存，Redis 暂时不可用时回退数据库。部署迁移后须抽查 sitemap 分片数量、年份筛选，并确认 `race_event_visible_year_idx`、`race_event_sitemap_idx`、`race_result_official_event_idx` 已创建。

## 2026-07-12 历史赛事编排工具首次生产部署与 2026 mapping

- 部署提交：`c3b66a6`；生产从 `dc6e434` 快进，并执行 `bash ./deploy_lowcost.sh`。
- 部署前 `.env` 备份：`.env.backup.historical-race-backfill-20260712_044501`。数据库备份：`backups/db/pre-historical-race-backfill-20260712_044501.sql.gz`，`110878772` bytes，SHA-256 `524accd73e30e3d4a87ca4c974b06811edbf78f80b755cb55d86121eaaccffeb`。
- mapping 写入前备份：`backups/db/pre-2026-race-series-mapping-20260712_051047.sql.gz`，`111044004` bytes，SHA-256 `701b951aca74ba1a7dad5665eb4dd9f333bd2233aa0f275011a36ae132510453`。两份备份均通过 `gzip -t`。
- 迁移验收：`0024_historical_race_inventory`、`0026_historical_race_query_indexes` 已应用；三个目标索引存在。`manage.py migrate stable 0023 --plan` 已完整列出 reverse plan；真实恢复入口仍为 `deploy/restore_db.sh <backup>`。
- 初始 dry-run 为 `995` 场、`786` 自动批准、`209` 待审、`212` 冲突。完成日本/香港稳定 key 审核、美国重复空壳清理、英国 Gold Cup 合并及相似名称显式区分后，最终 artifact 为 `runtime/historical_race_inventory/mapping-2026-approved-20260712_051808/`，结果 `992/992 approved`、`0 review_required`、`0 conflict`。
- mapping commit 仅在一次性管理容器中设置 `HISTORICAL_RACE_BACKFILL_ENABLED=true`，未开启网络；首次结果 `series_created=992 / events_bound=992`，幂等复跑 `0/0`。常驻 web/worker/beat 从未开启历史功能。
- 写后验收：`RaceSeries=992`、2026 `RaceEvent=992`、已绑定 `992`、未绑定 `0`；日本 `186`、香港 `20`、英国 `202`、法国 `174`、美国 `410`。`HistoricalRaceEventTarget=0`，1984–2025 赛事及其公开数均为 `0`。
- URL 抽检：`/races/`、`/races/2026/gold-cup/`、日本德比、香港董事杯均返回 `200`。已合并的 BHA 重复地址 `/races/2026/uk-bha-flat-2026-0618-045/` 返回 `404`，其 slug 已作为主赛事别名保留，正式入口固定为 `/races/2026/gold-cup/`。
- 最终开关：`HISTORICAL_RACE_BACKFILL_ENABLED=false`、`HISTORICAL_RACE_BACKFILL_ALLOW_NETWORK=false`；共享页面缓存为 `redis://redis:6379/2`。容器正常，内外 `/healthz/` 为 `200`，近 10 分钟无 traceback/error。

## TJCIS 年鉴目录生产生成

1. 部署已 review 提交，确认生产镜像内 `python -c 'import pdfplumber, bs4'` 通过。
2. 设置独立 run 目录、请求预算 artifact、source-cache manifest 和磁盘预算。1998–2026 首次下载需要 2 个索引请求和 29 个 PDF 请求，但不得超过历史回填全局上限。
3. 仅在下载窗口临时开启两个历史开关，执行 `python runtime/tools/prepare_tjcis_ics_catalog.py --years 1998-2026 --output-dir <run-dir> --allow-network`。中断后用同目录追加 `--resume`，禁止手工替换缓存。
4. 对五个 `manifest_<region>.json` 运行 `parse_historical_race_catalog`，再用 `build_historical_race_inventory` 生成部分只读总账 artifact。核对每年五地区非零、平地自报总数一致、conflict/review/gap 和原始 PDF SHA。
5. 1984–1997 未补齐前不得批准完整 inventory manifest、不得 commit 总账，也不得启动历史详情全量 apply。
6. 无论成功或失败都恢复两个开关为 `false`，验证内外 `/healthz/`、当前赛事页、`HistoricalRaceEventTarget=0` 和 1984–2025 公开赛事数为 `0`。

### 2026-07-12 首次 TJCIS 执行记录

- 生产直连 TJCIS 超时，禁止继续盲目重试；本次采用同一工具本机受控抓取、生产离线 SHA 复验。原始目录为 `runtime/historical_race_inventory/tjcis-ics-1998-2026-relay-20260712/`，31 个 cache 文件全部验证通过。
- 最终成功年只有 `2016 / 2020 / 2021`；`summary.json` 中 25 个 `year_errors` 是后续修复入口，不得删除、改成 warning 或从完成率分母隐藏。
- v3 candidate/inventory 路径分别为 `tjcis-candidates-2016-2021-v3-20260712/` 和 `tjcis-inventory-partial-2016-2021-v3-20260712/`。`conflict_count=82`，因此 approval 保持空白，禁止执行 `build_historical_race_inventory --commit`。
- 本轮没有数据库备份，因为全程只读且未进入 commit；写后核验为 targets/pre-2026/public-pre-2026 全部 `0`。常驻开关始终 `false`，生产 HEAD `3dc8dff` 后继续健康。
