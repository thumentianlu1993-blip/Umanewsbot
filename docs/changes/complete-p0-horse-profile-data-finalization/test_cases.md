# P0 马完整资料补全收尾测试

## 2026-07-19 最终安全与完整度回归

- source cache 版本升级为 `p0-horse-source-cache.v2`；日本等非美国缓存也必须由原始马名或
  alias 命中请求马，美国缓存缺少原始马名时不得用请求名回填。
- 来源总出赛数缺少来源名、HTTP(S) URL、带时区核验时间，或逐场权威状态不在枚举中时，
  cache validator 拒绝；normalizer 保留数量差异为零但将生涯状态降为 `partial`。
- 五地区 client 仅允许各自登记 HTTPS 主机，transport 自动重定向关闭；不允许的初始 URL
  不发请求，跨主机 `302` 在第二次请求前阻断并保留请求预算计数。
- 旧 `complete + complete_profile_full` 且权威性未知的迁移样本同时降为
  `needs_review + complete_pedigree_2gen`。
- 正式来源赛果覆盖旧 `unknown` 时，旧来源 `N/A` 继续作为直接原始值，标准原始值和归一化值
  使用正式来源证据。
- 跨 provider 只有同名/alias 且候选缺父、母、出生年时拒绝；数据库 evaluator 在总数证据
  缺失时保持 `partial`，整匹马 evaluator 也独立阻断。
- 同 provider 缺候选 external ID 时仍要求四字段；显式 source namespace 与 external key 的
  provider 冲突时在读取资料前拒绝。
- provider 大小写不同但 external ID 冲突仍拒绝；日本授权离线 replay 的 10 匹逐匹重建并
  复算 source/actual/missing/excess。
- 带空格主机和非法端口的总数 URL 均不能完成；新 ignored 建议保留审计但不覆盖此前 APPLIED
  完整证据。
- 第 4 名及以后和来源 `finished/unplaced` 均归一为 `unplaced`，真实模块审核 apply 后数据库
  仍为合法枚举；年份精度记录保留，但 dry-run 与落库后都保持 partial。
- 人工基础字段的主 URL/佐证 URL、血统证据 URL、逐场赛果和总数 URL 对空格主机、非法端口
  全部 fail closed。
- Python/Node 生成器对 `source_blocked`、`unknown` 和非法 authority 均不得输出完整；
  `source_records_verified` 是唯一完整白名单。官方总数为零时空记录列表通过，非零时仍拒绝。
- 父母来源身份必须同时具备马名、父名、母名和出生年；provider namespace 全局规范化时，
  external ID 仍按 opaque string 精确一致。自动 Netkeiba 父母 URL 只接受无凭据、端口、
  query、fragment 的精确 horse 详情路径。
- Kentucky Wood 的父系纠错必须把 1925 年 Netkeiba 同名 Balko 留在 v1，并让 v2 使用
  Racing Post `595446` 的 2001 年 Balko；纠错前后身份和父母字段均进入审计。
- 工作簿 builder 默认使用 v2 JSON、`-v2.xlsx` 和 `previews-v2`，环境变量覆盖配置；冻结 v1
  workbook 与 previews 输出必须拒绝。
- 扩大后的离线组合命令最终发现并通过 `282/282`，包含
  `stable.tests.P0HorseProfileDataCompletionTests` 整类；没有网络抓取或生产数据库写入。

## 统一 payload

- 五地区 adapter 返回相同顶层字段集合。
- 缺失身份、来源 URL或原始证据时返回明确 `failure_reason`，不能伪造完整资料。
- 别名去重后保留原文和多语种形式。
- 字段覆盖统计按硬字段、血统、履历和来源证据分别计算。

## 受控来源

- 网络开关关闭时任何 adapter 请求都被拒绝。
- fixture/cache 命中时不发网络请求。
- 单批上限、请求间隔和请求预算传递给现有来源客户端。
- 来源 URL、外部马匹 ID、抓取时间和 raw payload 保留在证据中。

## 完整履历

- 数字名次映射为 won/placed/unplaced。
- DNF、PU、UR 等映射为 did_not_finish，DSQ 映射为 disqualified。
- scratched/withdrawn 不计入实际出赛数。
- 来源只给年份时保留 year 精度，不虚构月日。
- 海外远征跨来源重复只生成一条记录，同时保留多来源证据。
- 无 `RaceEvent` 的普通比赛生成未关联履历 payload。
- 来源总出赛数与采集实际出赛数不一致时状态保持 partial/blocked。

## Artifact

- 输出逐马 JSONL、审核 CSV、summary、失败/冲突 JSONL、source evidence manifest。
- manifest 包含全部输出 SHA-256、审核状态、模块 diff、来源 URL 和失败样例。
- 相同输入生成稳定业务内容；已有目标目录拒绝覆盖。
- dry-run 前后 `HorseProfile`、`HorseP0Source`、`HorseProfileDataCandidate` 和 `HorseRaceRecord` 计数不变。

## 模块审核

- `apply` 记录 before/after、处理人、时间和被人工锁定跳过字段。
- `ignore` 记录原因，不改主表。
- `conflict` 保留 raw payload，不改 `HorseProfile` 或 `HorseRaceRecord`。
- 未审核或低置信模块无法进入 apply。

## 首批 50 匹

- 审核输入严格为五地区各 10 匹、候选键唯一、全部 `reviewed=true` 且决定为确认纳入。
- 30 匹强身份可进入资料解析；20 匹弱身份先进入身份补强，不因人工纳入而绕过门禁。
- dry-run 报告每地区完成数、blocker、请求数、字段覆盖和下一批建议。

## RED/GREEN 证据

### RED（2026-07-18）

测试文件：

- `server/stable/test_p0_horse_completion_adapters.py`
- `server/stable/fixtures/p0_horse_completion/*.json`

静态前置检查：

```bash
python3 -m py_compile server/stable/test_p0_horse_completion_adapters.py
jq -e . server/stable/fixtures/p0_horse_completion/*.json
```

结果：两条命令均退出 `0`，测试文件语法与五地区 JSON fixture 有效。

focused RED 使用现有本地测试镜像并显式关闭容器网络：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-horse-red.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_adapters --verbosity 2
```

真实结果：`Ran 17 tests`，`FAILED (errors=14)`，退出 `1`；Django 测试数据库迁移完成，`System check identified no issues`，没有发生网络请求。

- `13` 项 RED 为 `ModuleNotFoundError: No module named 'stable.services.p0_horse_completion_adapters'`，对应统一 payload、五地区 adapter、网络关闭/cache、履历规范化和 artifact writer 尚未实现。
- `1` 项 RED 为 `HorseProfileDataCandidate.DoesNotExist`，对应现有 `apply_reviewed_completion_artifact` 遇到模块 `status=ignore` 时没有保存 `IGNORED` 审核记录。
- 已有模块审核行为中，`apply` 的字段 diff/人工锁、`conflict` 的 raw payload 审计和低置信 apply 拒绝共 `3` 项通过，证明 focused 环境与既有审核入口可正常执行。

本机系统 Python 直接运行 Django 测试会因没有安装 `django` 失败，该命令不计入 RED；以上 Docker 结果才是本阶段有效证据。

### GREEN（2026-07-18）

实现文件：

- `server/stable/services/p0_horse_completion_adapters.py`
- `server/stable/services/p0_horse_profiles.py`（仅补 `ignore` 模块审核审计）

focused GREEN 继续使用现有本地测试镜像，并以 `--network none` 明确禁止任何网络访问：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-horse-green.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_adapters --verbosity 2
```

真实结果：最终一次运行 `Ran 17 tests in 0.429s`，`OK`，退出 `0`；Django 迁移完成，`System check identified no issues`。五地区缓存 fixture、受控 source-client 参数转发、网络关闭、状态映射、年精度、保守跨来源去重、未关联普通履历、稳定 artifact、拒绝覆盖以及 apply/ignore/conflict 审核合同全部通过。

直接相关 P0 回归：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-horse-regression-final.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test \
    stable.test_p0_horse_completion_adapters \
    stable.test_p0_horse_candidate_extraction \
    stable.test_p0_horse_career_history \
    --verbosity 1
```

真实结果：最终一次运行 `Ran 46 tests in 0.997s`，`OK`，退出 `0`；仅出现测试镜像缺少 `/app/server/staticfiles/` 的既有 `UserWarning`，不影响结果。

框架与规格门禁：

```bash
DB_ENGINE=sqlite python manage.py check
DB_ENGINE=sqlite python manage.py makemigrations --check --dry-run
openspec validate complete-p0-horse-profile-data --strict
openspec validate --all
git diff --check
```

前四项真实结果分别为：

- Django check：`System check identified no issues (0 silenced)`。
- 迁移漂移：`No changes detected`。
- 目标变更严格校验：`Change 'complete-p0-horse-profile-data' is valid`。
- 全量 OpenSpec：`30 passed, 0 failed`。

以上 Django 命令实际在同一 `--network none` 测试镜像中执行；`git diff --check` 最终退出 `0`。本阶段没有真实网络抓取、生产数据库写入、commit、push、merge 或部署。

### 50 匹已审核候选批次编排 RED（2026-07-18）

本轮只新增测试，没有修改 adapter、管理命令或其他实现。新增契约覆盖：

- 审核 CSV 必须严格为日本、中国香港、英国、法国、美国各 10 匹，`candidate_key` 全局唯一，且 50 行全部为 `reviewed=true`、`review_decision=confirm_batch_inclusion`；任一条件不满足即整批 fail closed。
- 缓存文件只按稳定 `candidate_key` 的 SHA-256 路由，避免马名变化、同名马和不安全路径字符影响缓存归属。
- 网络关闭且单匹无缓存时，将该马转成结构化 `network_disabled_cache_missing` blocker，不中断剩余候选；弱身份马同时保留 `identity_enrichment_required`。
- 50 行 dry-run 必须报告 `processed_count=50`、五地区各 10，网络请求数为 0，且 `HorseProfileCompletionRun`、`HorseProfile`、`HorseP0Source`、`HorseProfileDataCandidate`、`HorseRaceRecord` 均零写。
- 输出目录必须持久化 `p0_horse_completion_batch_manifest.json`；`complete_horse_profiles --dry-run` 必须通过显式 `--p0-reviewed-candidates` 进入该批次，不得回落到旧 profile 队列，也不得隐式开启网络。

静态检查：

```bash
python3 -m py_compile server/stable/test_p0_horse_completion_adapters.py
python3 - <<'PY'
from pathlib import Path

paths = [
    Path("server/stable/test_p0_horse_completion_adapters.py"),
    Path("docs/changes/complete-p0-horse-profile-data-finalization/test_cases.md"),
]
for path in paths:
    assert all(
        line == line.rstrip()
        for line in path.read_text(encoding="utf-8").splitlines()
    ), path
PY
```

两项检查均退出 `0`；测试文件语法有效，两个指定文件均无尾随空白。

focused RED 继续复用现有本地测试镜像，并在容器级关闭网络：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-horse-batch-red.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_adapters --verbosity 2
```

真实结果：`Found 22 test(s)`，`Ran 22 tests in 0.585s`，`FAILED (errors=5)`，退出 `1`；Django 全部迁移成功，`System check identified no issues (0 silenced)`。

- 原有 `17` 项 adapter、完整履历、artifact 和模块审核测试全部继续通过。
- 新增 `5` 项按预期 RED：
  - 缺少 `load_reviewed_p0_horse_candidates`；
  - 缺少 `p0_horse_completion_cache_path`；
  - 缺少 `run_reviewed_p0_horse_completion_batch`，影响单马 blocker 隔离与 50 行只读 manifest 两项；
  - `complete_horse_profiles` 尚不识别 `--p0-reviewed-candidates`。
- 测试运行于 `--network none`，没有网络抓取；测试数据库在结束时销毁，没有生产写入。

实现阶段风险：

- `confirm_batch_inclusion` 只代表人工确认进入首批，不得覆盖 `needs_identity_enrichment`；日本、美国弱身份样本仍须保留身份补强 blocker。
- 单匹缓存缺失、缓存损坏或 adapter 失败必须局部降级，不能让 50 匹批次提前终止。
- overall manifest 应在所有逐马 artifact 成功落盘后持久化，并绑定审核 CSV SHA-256 与各输出 SHA-256；非空输出目录仍应拒绝覆盖。
- 新命令入口必须显式分流到 reviewed-candidates runner，保留旧 dry-run 行为，并始终显式传递 `allow_network=False`。

### 50 匹已审核候选批次编排 GREEN（2026-07-18）

实现文件：

- `server/stable/services/p0_horse_completion_adapters.py`
- `server/stable/management/commands/complete_horse_profiles.py`

实现结果：

- 审核 CSV loader 要求恰好 50 行、五地区各有且仅有排名 1-10、候选键全局唯一、全部 `reviewed=true` 且决定为 `confirm_batch_inclusion`；必需 JSON 列必须可解析为列表。
- 缓存文件使用 `sha256(candidate_key).json`，不使用马名、地区或不安全路径字符。
- 每匹缓存缺失、缓存损坏或 adapter 异常都会生成独立结构化 blocker，批次继续处理后续马匹；弱身份输入始终保留 `identity_enrichment_required`。
- 批次输出既有六个业务 artifact、内部 artifact manifest 和 overall batch manifest。overall manifest 绑定审核 CSV 的大小与 SHA-256、全部业务输出的大小与 SHA-256、逐地区 summary、网络开关和数据库写入计数。
- 管理命令只有显式提供 `--p0-reviewed-candidates` 才进入新批次入口，并固定传递 `allow_network=False`；旧 profile 队列 dry-run 不受影响。

focused GREEN 继续使用现有测试镜像，并在容器级关闭网络：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-horse-batch-green.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_adapters --verbosity 2
```

最终真实结果：`Ran 22 tests in 0.536s`，`OK`，退出 `0`；新增 5 项和原有 17 项全部通过，Django 迁移完成，`System check identified no issues (0 silenced)`。

P0 直接相关回归：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-horse-regression-green.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test \
    stable.test_p0_horse_completion_adapters \
    stable.test_p0_horse_candidate_extraction \
    stable.test_p0_horse_career_history \
    --verbosity 1
```

最终真实结果：`Ran 51 tests in 0.907s`，`OK`，退出 `0`；仅出现测试镜像缺少 `/app/server/staticfiles/` 的既有 `UserWarning`。

真实已审核输入的离线 dry-run 使用：

- 输入：`runtime/p0_horse_candidates/production-reviewed-20260718-all-50-approved/p0_participant_sample_review.reviewed.csv`
- 输入 SHA-256：`f36d2f3f71fccc90a7f498f4d1c021e1a6d4275450122de599bc4b8767e240fa`
- 模式：容器 `--network none`、空缓存、临时输出目录、管理命令显式 `--p0-reviewed-candidates`
- 结果：处理 `50` 匹，法国、中国香港、日本、英国、美国各 `10`；网络请求 `0`；overall manifest 约束的 `7` 个文件 SHA-256 全部复核一致。
- blocker：空缓存使 `50/50` 都有 `network_disabled_cache_missing`；日本和美国共 `20/50` 另外保留 `identity_enrichment_required` 和 `missing_identity`。本次只验收编排能力，不把空缓存样本误报为资料补全完成。

框架与规格门禁：

```bash
DB_ENGINE=sqlite python manage.py check
DB_ENGINE=sqlite python manage.py makemigrations --check --dry-run
openspec validate complete-p0-horse-profile-data --strict
openspec validate --all
git diff --check
```

真实结果：

- Django check：`System check identified no issues (0 silenced)`。
- 迁移漂移：`No changes detected`。
- 目标 OpenSpec：`Change 'complete-p0-horse-profile-data' is valid`。
- 全量 OpenSpec：`30 passed, 0 failed`。
- Python 编译和 `git diff --check` 均退出 `0`。

全过程没有真实网络抓取、生产数据库写入、commit、push、merge 或部署。

### Reviewer P1：候选来源与补全来源身份隔离 GREEN（2026-07-18）

问题根因：

- 原实现使用 `source.external_horse_id or request.external_horse_id` 生成统一 ID，混淆了重点赛事候选来源和资料补全缓存来源。
- 跨 provider 的合法 ID 会被直接比较并误报冲突；目标来源缺少 ID 时还会错误借用候选来源 ID。
- 履历 `horse_identity_key` 和 `external_horse_id` 因此可能被写成不属于目标来源的 provider-bound 身份。

修复结果：

- `P0HorseCompletionRequest` 明确携带候选 `candidate_source_name` 和候选 external ID；缓存 payload 的 `source.name` 与 `source.external_horse_id` 独立作为目标来源身份。
- 只有候选 provider 与目标 provider 相同、且两边 ID 都存在时才比较；同 provider 不同 ID 立即抛出 `P0HorseCompletionSourceError`。
- 跨 provider 不直接比较 ID，`identity_keys` 和 `source_evidence` 同时保留候选与目标两套 `provider:external_id`，并以 `reviewed_candidate` / `completion_source` 标记证据角色。
- 目标来源缺少 external ID 时，顶层和履历记录的目标 `external_horse_id` 保持为空，不借用候选 ID。只有完整“马名 + 父名 + 母名 + 出生年份”才能满足目标身份门禁；字段不全时保留 `missing_identity` blocker。
- 履历身份键按顺序使用目标来源 `external:<provider>:<id>`、完整血统规范键 `pedigree:<sha256>`、原始 `candidate_key`。无论哪个 fallback，都不会制造错误的目标 provider ID。
- 缓存完全缺失时，结构化 blocker 同样只在候选身份字段和候选来源证据中保存候选 ID，顶层目标 external ID 保持为空。

focused GREEN：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-horse-provider-p1-green-final.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_adapters --verbosity 1
```

最终真实结果：`Ran 25 tests in 0.492s`，`OK`，退出 `0`。新增 3 项覆盖同 provider 冲突拒绝、跨 provider 双身份保留、目标无 ID 不借用候选 ID；原有 22 项继续通过。

P0 直接相关回归：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-horse-provider-p1-regression-final.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test \
    stable.test_p0_horse_completion_adapters \
    stable.test_p0_horse_candidate_extraction \
    stable.test_p0_horse_career_history \
    --verbosity 1
```

最终真实结果：`Ran 54 tests in 0.709s`，`OK`，退出 `0`；仅出现测试镜像缺少 `/app/server/staticfiles/` 的既有 `UserWarning`。

额外只读履历身份检查确认：

- 目标 `geny` 有 ID：顶层、履历记录和 `horse_identity_key` 使用 `fr-001` / `external:geny:fr-001`。
- 目标无 ID、四元组完整：顶层和履历 external ID 为空，使用 `pedigree:<sha256>`。
- 目标无 ID、四元组不完整：顶层和履历 external ID 为空，使用原 `external:zeturf:candidate-1` 作为候选 fallback，并保留 `missing_identity`。

全过程保持容器 `--network none`，没有生产数据库写入、commit、push、merge 或部署。

### 多来源补全与人工字段补录 TDD（2026-07-18）

新增契约覆盖：

- 自动第二来源只补空字段，保留主来源完整生涯和来源身份；不同非空值产生 `source_conflict`。
- 第二来源不得携带生涯记录，自动来源必须属于地区已批准 provider。
- 人工 CSV 只接受精确表头和白名单字段；`pending/rejected/needs_more_evidence` 不参与合并。
- `approved` 行必须绑定候选地区和马名、直接证据 URL、录入人、不同的复核人及 UTC 复核时间；同一候选同一字段不得重复批准。
- 人工记录只能补身份、基础资料和二代血统，禁止 `career`；证据明确输出 `manual_supplement`，adapter key 为空。
- 人工补录文件在批次 manifest 中记录大小、SHA-256、批准字段数和候选数。

RED 先后真实得到目标函数缺失 `3` 项错误、source client 尚未接受人工映射及证据角色未保留 `2` 项错误。完成实现后运行：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-source-clients-full.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server:ro \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_source_clients --verbosity 1
```

真实结果：发现 `56` 项，`System check identified no issues (0 silenced)`，`Ran 56 tests in 0.630s`，`OK`。容器使用 `--network none`，没有生产数据库写入、网络抓取、commit、push、merge 或部署。

审核工作簿由官方 spreadsheet artifact runtime 生成并逐页渲染检查，包含：

- `批次总览`：50 匹、已完成 10、待补全 40、生产写入 0；
- `马匹队列`：五地区 50 匹身份、来源、阻断和下一步；
- `人工字段审核`：中国香港 50 行、英国 20 行，共 70 个待审核字段；
- `来源阻断`：四地区单马真实探测结论和证据 URL；
- `字段说明`：16 个审核 CSV 字段及全部可补资料字段。

公式错误扫描为 0，五张表均完成 PNG 视觉检查。工作簿路径：
`outputs/p0-horse-info-completion-20260718/P0马详细信息补全_字段审核工作簿_20260718.xlsx`。

### 独立 reviewer 三项修复与相邻门禁（2026-07-18）

首轮独立 review 结论为 `REVISE`，指出：

1. 审核候选 CSV 先算 SHA 后按路径重读，存在解析内容与冻结哈希不是同一快照的竞态。
2. 人工补录 CSV 同样存在审计 SHA 与实际解析内容分离的竞态。
3. 美国 HRN 的“搜索、profile、独立 results”合法回退需要三次请求，而固定预算只有两次。

修复采用测试先行：

- 两类 loader 新增 `captured_bytes`，批次只解析首次读取并用于大小/SHA 的同一字节快照；测试在捕获后篡改路径文件，仍只解析已冻结快照。
- 美国单马请求预算由 `2` 调整为 `3`，并要求三请求 HRN 回退完整通过；五地区 10 匹测试总请求预算由 `90` 更新为 `100`。
- 人工补录若指向本次未选择的网络地区、与自定义 source client factory 同时使用，或目标字段已经非空，均在来源访问前 fail closed。

最终离线回归：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-horse-four-module-review-fixes.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server:ro \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test \
    stable.test_p0_horse_completion_source_clients \
    stable.test_p0_horse_completion_adapters \
    stable.test_p0_horse_candidate_extraction \
    stable.test_p0_horse_career_history \
    --verbosity 1
```

首轮修复后真实结果：发现 `113` 项，`System check identified no issues (0 silenced)`，`Ran 113 tests in 1.101s`，`OK`。source-client 单模块为 `58/58`。全过程没有真实网络、生产数据库写入、commit、push、merge 或部署。

第二轮独立 review 继续发现 cache hit 会绕过人工补录。新增回归证明：

- 合法 cache 的空身份字段会在内存快照上应用 approved 人工补录，artifact 保留 `manual_supplement` 证据；
- 原 cache 字节保持不变，不把人工内容回写输入 cache；
- cache 已有不同值时产生 `source_conflict`；
- cache 已包含完全相同的人工来源和审核元数据时可幂等复放。

实现由 `_PerCandidateSourceClient` 将同一人工合并入口代理到 cache 路径，网络与 cache 使用同一合并函数。文档中的美国单马预算同步由 `2` 修正为 `3`。

第二轮修复后 source-client 为 `59/59`（`Ran 59 tests in 0.508s`），四模块为 `114/114`（`Ran 114 tests in 1.133s`），均为 `OK`。

第三轮独立 review 继续指出 canonical cache 污染、人工输入缺实际 outcome、证据备注未进入幂等判断，以及运行手册美国预算残留。修复后：

- 网络 cache miss 先验证并缓存纯自动来源快照，再仅对本批内存工作副本应用人工补录；cache 不包含人工字段、`supplemental_sources`、人工 provenance 或 outcome。
- 每个批准字段产生 `applied / already_applied / blocked / ignored` outcome；总体、地区 summary 和 batch manifest 同时记录字段数与候选数。
- 来源失败时该候选的批准人工字段全部记录为 `blocked`，并保留字段、来源、录入人、复核人和失败原因。
- 幂等指纹包含 `evidence_note` 和 `review_notes`；只有完整审核证据一致才允许 `already_applied`。
- `docs/deploy_runbook.md` 的美国请求预算同步为 `3`。

最终 source-client 为 `60/60`（`Ran 60 tests in 0.551s`），四模块为 `115/115`（`Ran 115 tests in 1.131s`），均为 `OK`。

第四轮独立 review 发现 canonical validator 仍可能接受历史人工污染 cache，以及 artifact 发布前没有把冻结输入与 outcome 一一对账。修复后：

- canonical cache 默认严格拒绝顶层 outcome、人工 `field_provenance`、人工 `supplemental_sources`、`raw_payload.manual_supplements` 及递归人工标记；
- 网络 source snapshot 在允许“不完整自动字段由本批补录填空”之前，先独立执行纯净边界检查；自定义 client 返回混合 payload 时不写 cache；
- cache hit 无人工输入时保留既有 missing-target-ID 兼容 blocker 语义，但仍再次拒绝新增人工标记；确有冻结人工输入时才允许工作副本含人工标记并执行补录后完整校验；
- staging 前按候选、字段、当前值、建议值和完整 source evidence 指纹逐条对账，状态只允许 `applied/already_applied/blocked/ignored`；
- 新增污染 cache、混合来源、缺失 outcome、重复 outcome、未知状态、证据备注漂移和无输入旧 outcome 的 fail-closed 测试，失败时最终 output 目录不存在。

第四轮修复后 source-client 为 `63/63`（`Ran 63 tests in 5.960s`），四模块为 `118/118`（`Ran 118 tests in 26.382s`），均为 `OK`。Django check、迁移无漂移、OpenSpec strict/all `30/30` 和 `git diff --check` 同时通过；仍未执行真实网络批次或数据库写入。

第五轮独立 review 指出递归纯净检查只处理 `dict/list`，自定义 client 可把人工标记藏入 tuple，首次检查放行后由 JSON 序列化变成数组并污染 cache。修复后 canonical payload 在检查人工标记前先递归验证严格 JSON 类型：对象键必须是字符串，容器只允许 `dict/list`，标量只允许 `null/string/boolean/integer/finite float`。真实 custom-client + network + cache 测试把 `manual_review` 藏入 tuple，证明调用失败且 cache 文件不存在。修复后 source-client `63/63`（`Ran 63 tests in 6.391s`）、四模块 `118/118`（`Ran 118 tests in 26.855s`），Django check、迁移无漂移、OpenSpec strict/all `30/30` 和 `git diff --check` 全部通过。

第六轮独立 review 指出循环/过深容器会泄漏裸 `RecursionError`，且 tuple 测试未经过真实审核批次包装层。修复后严格 JSON validator 改为迭代 enter/exit 遍历，以当前活动容器 ID 检测循环，并以 `CANONICAL_JSON_MAX_DEPTH=100` 阻断过深结构。新增直接 adapter 的循环/过深测试，以及真实授权 reviewed batch + custom factory 测试：英国 10 匹中分别注入 tuple、set、非字符串 key、NaN、Infinity、循环和过深结构 7 类非法 payload，结果为 `7 blocked / 3 complete`，10 匹均被调用，非法候选归入 `source_cache_or_adapter_error`，cache 目录精确只包含 3 个合法候选 JSON，无目标污染文件或临时残留。修复后 source-client `64/64`（`Ran 64 tests in 7.070s`）、四模块 `119/119`（`Ran 119 tests in 26.864s`），Django check、迁移无漂移、OpenSpec strict/all `30/30` 和 `git diff --check` 全部通过。

第七轮独立 review 指出 source validator 在严格形状检查前先 `deepcopy`，且 `_read_cache()` 未包装 JSON decoder 对超深 cache 的 `RecursionError`。修复后 validator 先在原始对象上执行迭代 JSON 检查和人工标记检查，只有通过后才复制；直接测试使用 1200 层对象及会主动抛错的 `__deepcopy__` 对象，证明前者转为最大深度 blocker，后者在复制前作为非 JSON 值阻断。磁盘测试写入 1200 层真实 JSON cache，通过完整 reviewed batch 证明其归入 `source_cache_or_adapter_error`，其余 9 个 cache hit 继续、client 网络调用为 0、地区结果为 `1 blocked / 9 complete`。修复后 source-client `66/66`（`Ran 66 tests in 7.027s`）、四模块 `121/121`（`Ran 121 tests in 27.128s`），Django check、迁移无漂移、OpenSpec strict/all `30/30` 和 `git diff --check` 全部通过。

第八轮独立 review 指出自定义 `dict/list` 子类仍可在通过 `isinstance` 后利用 `__deepcopy__` 抛错或篡改内容，且深层坏 cache 测试未核对原文件不变。修复后容器只接受精确内置 `dict/list`，标量继续兼容项目实际使用的 `RacingRegion` 字符串枚举；通过形状与人工标记检查后，用 `json.dumps(..., allow_nan=False)` + `json.loads()` 生成纯内置类型副本，不再调用 payload 自定义复制钩子。直接测试新增抛错型 dict 子类和篡改型 list 子类，两者均在复制前作为非 JSON 值阻断。cache-hit 批次记录运行前后全部 cache 文件名和字节，结果逐项完全一致，因此同时证明无删除、截断、改写或临时残留。四模块再次为 `121/121`（`Ran 121 tests in 27.222s`），Django check、迁移无漂移、OpenSpec strict/all `30/30` 和 `git diff --check` 全部通过。

第九轮独立 review 指出 JSON 规范化后未再次检查人工标记，且 `merge_reviewed_manual_supplements` / `merge_p0_horse_source_payloads` 仍可能在严格检查前复制输入。修复后 canonical validator 在原对象与规范化副本上各检查一次人工标记；测试用自定义 `str` 子类让原始 `== manual_review` 和 `manual_supplements in dict` 返回假，但 JSON round-trip 后变成普通字符串，证明二次检查能阻断，同时 `RacingRegion` 仍规范为普通 `str`。两个合并 helper 现在先对主 payload 和补充列表执行严格 JSON 规范化；直接测试使用抛错型嵌套 dict 与篡改型补充 list 子类，四条路径均在复制或合并前阻断。修复后 source-client `68/68`（`Ran 68 tests in 7.292s`）、四模块 `123/123`（`Ran 123 tests in 27.244s`），Django check、迁移无漂移、OpenSpec strict/all `30/30` 和 `git diff --check` 全部通过。

第十轮独立 review 指出 `reject_manual_supplements_from_canonical_source_payload()` 仍只检查原始对象，虽然随后完整 validator 会偶然补拦，但该独立 purity gate 自身可被欺骗型字符串绕过。修复后 gate 先执行严格形状检查和安全 JSON copy，再同时检查原对象与规范化副本。既有欺骗值/键测试现在分别直接调用 purity gate 和完整 validator；实际 adapter + network + cache 测试也加入欺骗型 `entry_method`，证明来源在 cache 写入前被阻断且 cache 文件不存在。四模块再次为 `123/123`（`Ran 123 tests in 27.711s`），Django check、迁移无漂移、OpenSpec strict/all `30/30` 和 `git diff --check` 全部通过。

第十一轮同一独立 reviewer 重新读取完整 diff 后返回 `VERDICT: APPROVED`，明确无 actionable findings。审前与审后 fingerprint 均为 `9d2a7a276236306d3468e7a302df46e448ecfee257c64763db4700197edc8303`，reviewer stdout SHA-256 为 `b124808e0a93c4662687790b11f87dd192f29d9dff53692ff9383d96edb8ed8a`，sandbox 为只读且未修改文件。该审查结论不授权真实网络批次、生产数据库写入、发布、Git 合并或部署。

### 第十二轮：补充来源身份、证据原子组与最终计数参照（2026-07-19）

同一独立 reviewer 在上一轮实现上继续指出六个旁路：自动补充来源只按马名合并；审核 artifact
和数据库只检查 URL 非空；新总数可借用旧来源证据；cache 硬字段只检查非空；研究摘要仍固定
比较备用来源总数；source client 的 URL 只做 `urlparse` 粗判。

修复后：

- 自动补充来源只有同 provider 且 external ID 精确一致，或主/补充双方各自完整命中马名、
  父名、母名、出生年份时才能合并。
- source client、审核 apply、逐场记录和数据库 evaluator 统一使用 Django `URLValidator`
  严格验证 HTTP(S) URL，非法主 URL 与 `source_refs` 都不能贡献完整度。
- 总数、来源名、来源 URL、带时区核验时间作为原子证据组写入；新组不完整时整组清空，不能
  借用旧字段。
- cache 验证硬字段类型、出生年份范围、精确 ISO 日期和年份一致性；年份精度履历仍可保存并
  保持 partial。
- 研究摘要优先使用官方总数，否则才用来源总数，因此官方总数与备用来源数不一致时会正确
  报告缺口。

Docker `--network none` 定向回归发现并通过 `174/174`；扩大到来源解析、adapter、生涯模型、
既有 P0 完整档案、50 匹产物和血统研究的组合回归发现并通过 `251/251`。测试数据库使用
SQLite 临时文件，结束后销毁；没有真实网络、生产数据库写入、commit、push、merge 或部署。

### 第十三轮：父母实体强身份与历史 APPLIED URL（2026-07-19）

同一 reviewer 继续发现三项：父母实体唯一同名候选会被自动采用；人工血统证据会把 external
ID 去标点并忽略大小写；数据库最终完整度只检查历史 APPLIED profile/pedigree URL 非空。

修复后：

- 唯一同名结果保持 unresolved；只有预期 external ID 精确一致，或已有父名与候选完整来源
  身份共同命中才允许自动填祖父母。
- provider namespace 继续规范化，external ID 只去首尾空格并按 opaque string 精确比较；
  `AB-12` 与 `ab12` 明确不匹配。
- 旧 JSON 的 `62` 条 name-only 父系证据和 `54` 条 name + known sire 母系证据没有伪装成
  新算法结果；该轮 manifest 绑定 v1 SHA、每匹目标马强身份、父母马 Netkeiba ID、字段值和
  既有项目负责人审核上下文，再生成当时的 v2 中间产物。这不表示项目负责人逐字段提供或审核
  后续补入的 `55` 个父母出生年；独立出生年证据与最终 v2 收口见第十四轮。
- 最终数据库 evaluator 对历史 APPLIED profile/pedigree URL 使用同一严格 HTTP(S) 校验。
- 工作簿归一化最终出口把 evidence 层残留 `finished` 转为 `unplaced`，避免优先 evidence
  绕过记录层转换。

定向回归发现并通过 `83/83`；完整离线 P0 组合回归发现并通过 `277/277`。v2 工作簿包含
`2050` 条逐字段证据、`1439` 条履历、`2679` 条逐场字段证据和 `9` 张预览，公式错误为 `0`。
全过程 `--network none`，没有生产写入、commit、push、merge 或部署。

### 第十四轮：父母出生年、全局来源身份与 v2 冻结保护（2026-07-19）

第十三轮 `277/277` 后新增 5 项回归，覆盖父母实体完整来源身份、全局 provider + opaque ID
一致性、Balko 显式纠错、严格 Netkeiba URL，以及工作簿 v2 默认路径与 frozen v1 保护。

- `116` 条已审核 pedigree evidence 解析为 `55` 个唯一父母来源身份；全部 `116`
  `source_identity` 均含 `horse_name + sire_name + dam_name + birth_year`，两种 legacy
  method 计数为 `0`。
- 出生年证据是独立 approved artifact
  `reviewed_parent_birth_year_evidence.json`，`reviewed_by=codex_manual_source_review`，
  SHA-256 `ed9f6419dccd41485b96884410ea9ab5976d8ab5ba2acfb97e03837a7a3deb54`；
  不记为项目负责人逐字段审核 `55` 个出生年。
- Kentucky Wood 的旧 Netkeiba `000a02bd3f` 已确认是 1925 年同名 Balko，只保留在 v1；
  v2 使用 Racing Post `595446` 的 2001 年 Balko，父母为 Pistolet Bleu / Ella Royale，
  并保留 old/new identity 与 correction reason。
- 自动 Netkeiba 父母候选只接受精确 `https://en.netkeiba.com/db/horse/<id>/`；凭据、显式端口、
  query 或 fragment 均拒绝。provider namespace 可规范化，但 external ID 在证据、manifest、
  v2 JSON 和工作簿全链路按不透明原值精确一致。
- 工作簿 builder 默认读取 v2 JSON、写入 `-v2.xlsx` 和 `previews-v2`；环境变量优先于配置，
  frozen v1 workbook / previews 输出会被拒绝。

最终冻结 SHA-256：

- v1 JSON：`55d80abed2b76a2d7fcf0cb97aadff800c3130c3815e84d8e6eb5b1c16b4befd`
- v1 workbook：`4b68b87a076793eab0acc2357762afbd0c0fcaf2282fcf4122e3a2a855c2b696`
- v2 JSON：`a1184dbfb0257ecbe2a4ddbc4e729b0a74d73f911c8d52a20ab65854520325b7`
- parent identity manifest：`b211d9040814b0b56ec30e8ef8930fdc10f4140a3a660cf491fcae12d0b6ab2b`
- v2 workbook：`f67ad84408e68af69f14e2eef06e7135ca0b19cfc4fd18faf8925798acdbb1eb`

reviewer 最后一条意见指出工作簿结论数字被硬编码。新增
`careerConclusionRows(horses)` 后，法国、中国香港、英国和美国的结论数字均从当前 horses
输入动态统计；合成输入中缺少具名马时不生成该马结论。RED 阶段 summary test 因缺少
`careerConclusionRows` 导出而退出 `1`；GREEN 阶段 summary/path tests 均退出 `0`，
builder/summary 的 Node `--check` 通过。重建 v2 workbook 成功，结果为 `50 horses / 2050
field evidence / 1439 career records / 2679 career field evidence / 9 previews / formula
errors 0`；首页预览已人工检查，无溢出或遮挡。

最终 Python 离线组合回归从 `277/277` 增至 `282/282`；Node summary/path 测试、Django check、
迁移漂移、Python `compileall`、OpenSpec change strict 通过、all strict `30/30`、工作簿公式
错误扫描和 `9` 张预览均通过。50 匹仍为
`1439 records = 1432 actual + 7 non-start`，缺少/多采均为 `0`，严格完整 `40/50`，美国
`10` 匹数量对齐但逐场官方性待确认。全过程没有生产写入、部署、发布或网络 career crawl，
生产保持 `NO-GO`。

### 第十五轮：来源调研与批次文案动态化（2026-07-20）

- `buildSourceResearchRows(horses)` 从当前 horses 输入动态计算法国、英国、美国与 Fort George
  结论；日本、香港“本批无缺口”按当前 `field_status` 与 career 数据生成，无地区或具名马
  样本时不制造结论。
- `workbookBatchMetadata(horses)` 动态生成标题、范围、总表 sheet 名及美国字段字典中的批次
  数字；默认输出文件名仍绑定冻结 50 匹 artifact。
- 两轮 RED 均因缺少新 helper 导出使 summary test `exit 1`；GREEN 后 summary/path tests
  均 `exit 0`，builder/summary Node `--check` 通过。
- v2 workbook 重建结果为 50 horses / 2050 field evidence / 1439 career records /
  2679 record evidence / 9 previews / formula errors 0，SHA-256 为
  `f67ad84408e68af69f14e2eef06e7135ca0b19cfc4fd18faf8925798acdbb1eb`。首页与来源调研页
  人工检查无溢出或遮挡；生产保持 **NO-GO**。

### 第十六轮：地区汇总与字段矩阵动态化（2026-07-20）

- `regionSummaryConclusion` 对非空地区按硬字段、血统、missing/excess/unknown 与 career
  completeness 动态生成结论，美国追加逐场官方性说明；无样本明确显示“当前输入无样本”。
  `japanBatchConclusion` 空样本不再产生 `0/0` 成功结论。
- `regionSourcePolicy` 与 `regionNextRoute` 改为通用来源能力和入口；字段矩阵移除固定
  Fort George/JBIS 本批覆盖说明与固定样本 URL，无样本不再因 `0=0` 显示可正常获取。
- RED 阶段 summary test 因缺少 `regionNextRoute` 导出失败；GREEN 后 summary/path tests
  和 builder/summary Node `--check` 通过。
- 动态美国结论与字段矩阵长文本首次视觉检查发现行高不足，随后仅将 summary `A5:M9`
  行高由 `42` 调至 `72`、matrix data rows 由 `34` 调至 `56`。重建仍为
  50 / 2050 / 1439 / 2679 / 9 previews / formula errors 0，SHA-256 为
  `f67ad84408e68af69f14e2eef06e7135ca0b19cfc4fd18faf8925798acdbb1eb`；首页与字段矩阵
  复查无裁切或遮挡，生产保持 **NO-GO**。

### 第十七轮：血统结论空样本保护（2026-07-20）

- RED 证明 `pedigreeCompletionStatement([])` 会把 0 匹误判为全部补齐；GREEN 后
  `pedigreeCompletionStatement([])` 与 `regionPedigreeStatement([])` 均返回“当前输入无样本”，
  非空输入行为不变。summary/path tests、Node `--check` 与 `git diff --check` 通过。
- 为确认当前 50 匹输出最后重建一次，结果仍为 50 / 2050 / 1439 / 2679 / 9 previews /
  formula errors 0，可见内容与前次一致。二进制生成元数据使 SHA-256 更新为
  `f67ad84408e68af69f14e2eef06e7135ca0b19cfc4fd18faf8925798acdbb1eb`；此后不再重建，
  生产保持 **NO-GO**。


### 任务 4.2：受控审核批次网络入口 RED（2026-07-18）

本轮严格测试先行，只修改
`server/stable/test_p0_horse_completion_source_clients.py` 与本测试证据文档。没有修改
service、management command、model、settings、OpenSpec tasks 或其他文档。新增测试复用既有
50 匹 reviewed CSV 生成器，并只通过 fake source-client factory 返回内存 payload；容器全程
`--network none`，不会访问真实网站。

修改前基线命令：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-source-clients.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server:ro \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_source_clients --verbosity 1
```

基线真实结果：发现 `20` 项，`System check identified no issues (0 silenced)`，
`Ran 20 tests in 0.056s`，`OK`，退出 `0`。

新增 `8` 个测试方法，锁定以下批次入口合同：

- `--allow-network` 只允许与 `--dry-run + --p0-reviewed-candidates` 一起使用；commit
  和普通 legacy dry-run 均必须在进入业务逻辑前拒绝。
- CLI flag 与 `HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=True` 必须同时满足；缺少任一项
  都不得建立 source client 或发起 fake transport。
- 网络批次必须显式给出至少一个 `--region`。只有选中地区可用网络，未选地区只读 cache；
  cache miss 保持逐马 `network_disabled_cache_missing`，不能中断整批。
- 每个选中地区只建立并复用一个受控 client，每区固定最多 `10` 匹；逐马 request budget
  使用 JBIS=`3`、HKJC=`1`、Sporting Life=`1`、Geny=`2`、HRN=`2`。
- 网络 payload 必须继续走现有 adapter 和原子 cache；同一 reviewed CSV 随后离线重跑时，
  已缓存地区全部 `cache_hit` 且 network request count 为 `0`。
- batch manifest、summary 和逐马 retrieval 必须一致记录 `network_allowed`、选中地区、
  network request count、cache hit/miss；`read_only=true`、`database_writes=0` 不变。
- 网络模式不得放宽 50 行 reviewed CSV 结构、输入 SHA、空 output-dir、每区 10 匹、
  身份和完整度门禁；单马 source payload 缺少二代血统时形成 blocker，后续马继续处理。

新增测试后的 RED 命令：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-source-clients-red.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server:ro \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_source_clients --verbosity 2
```

真实结果：发现 `28` 项，原有 `20` 项全部继续通过；新增 `8` 个测试方法全部按预期未通过。
最终为 `Ran 28 tests in 0.072s`、`FAILED (failures=2, errors=7)`、退出 `1`。其中
`failures=2` 是同一个 CLI 合同测试的两个 subtest，因此不是 9 个新增测试。

RED 精确暴露两个尚未实现的入口层缺口：

- management command 尚未注册 `--allow-network`，commit 与 legacy dry-run 两个负例都先得到
  `CommandError: Error: unrecognized arguments: --allow-network`，还没有进入预期的模式门禁。
- reviewed batch 尚未接收 `network_regions` 与 `source_client_factory`；离线路径也尚未显式传递
  空的 `network_regions`。因此 1 项为 `KeyError: 'network_regions'`，其余 service 合同停在
  `TypeError: run_reviewed_p0_horse_completion_batch() got an unexpected keyword argument
  'network_regions'`。

该 RED 只证明受控审核批次网络入口仍缺实现，不代表 task 4.2 已完成，也不代表可以真实抓取
或写生产资料。全过程没有网络访问、生产数据库写入、commit、push、merge、deploy 或 reviewer
调用。

### 任务 4.2：真实来源 blocker 异常分类 RED（2026-07-18）

本轮继续严格限制为测试和测试证据文档，没有修改实现、配置、OpenSpec tasks 或其他文件。
测试使用注入的单个法国 fake source client：第 1 匹先设置
`last_request_count=2`，再抛真实
`p0_horse_completion_source_clients.P0HorseSourceBlocked("rate_limited: HTTP 429")`；
后续 9 匹由同一个 client 返回完整内存 payload。没有真实 transport 或网络访问。

新增测试前的 28 项基线：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-source-clients-28-baseline.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server:ro \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_source_clients --verbosity 1
```

真实结果：发现 `28` 项，`System check identified no issues (0 silenced)`，
`Ran 28 tests in 0.241s`，`OK`，退出 `0`。

新增 `1` 个最小合同测试，要求：

- `P0HorseSourceBlocked` 归入 `source_cache_or_adapter_error`，不得归入
  `unexpected_adapter_error`。
- blocker payload 的 retrieval 保留 `network_request_count=2`、
  `error_type=P0HorseSourceBlocked` 和
  `error_message=rate_limited: HTTP 429`。
- 单马来源 blocker 不终止整批；同一法国 client 仍处理全部 `10` 匹，批次仍处理 `50` 匹，
  法国网络请求汇总为 `20`。

最终 RED 命令：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-source-clients-source-blocker-red-final.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server:ro \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_source_clients --verbosity 2
```

真实结果：发现 `29` 项，原有 `28` 项全部继续通过；最终为
`Ran 29 tests in 0.365s`、`FAILED (failures=1)`、退出 `1`。唯一失败为新增测试中的分类
subtest：

```text
['unexpected_adapter_error'] != ['source_cache_or_adapter_error']
```

分类断言使用 subtest，因此失败后其余断言仍继续执行并全部通过：当前实现已经准确保留请求数
`2`、异常类型和消息，也会继续处理同地区后续候选，并得到整批 `processed_count=50`、
`network_request_count=20`。缺口仅在于 batch 没有把真实来源层
`P0HorseSourceBlocked` 视为预期的 source/cache/adapter blocker。

该 RED 不代表实现完成，也不授权真实抓取或生产写入。全过程没有访问网络、写生产数据库、
调用 reviewer、commit、push、merge 或 deploy。

### Reviewer 三项 finding 的新增合同测试（2026-07-18）

本轮仍只修改 source-client 测试与本测试证据文档，没有修改实现、配置、OpenSpec tasks
或其他文件。所有网络相关对象均为 patch/fake，容器保持 `--network none`。

新增测试前的 29 项基线：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-source-clients-29-baseline.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server:ro \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_source_clients --verbosity 1
```

真实结果：发现 `29` 项，`System check identified no issues (0 silenced)`，
`Ran 29 tests in 0.259s`，`OK`，退出 `0`。

新增 `3` 个测试方法：

1. **跨候选请求数隔离**：英国第 1 匹无 cache，fake client 实际请求 `1` 次并成功；第 2 匹在
   精确 candidate-key cache 路径预置缺少 `dam_dam` 的无效 cache；第 3 至 10 匹预置有效
   cache。整批理论上只有第 1 匹发生网络请求。要求第 2 匹
   `retrieval.network_request_count=0`，总体和英国地区汇总均为 `1`，并继续读取后 8 匹 cache。
2. **direct service setting gate**：`HORSE_PROFILE_COMPLETION_ALLOW_NETWORK=False` 时直接调用
   `run_reviewed_p0_horse_completion_batch(... allow_network=True, network_regions=(uk,))`，
   必须在 factory/client 创建前抛 `P0HorseCompletionBatchError`，且 `factory.calls=[]`。
3. **默认生产 factory 路径**：不传 `source_client_factory`，离线 patch
   `requests.Session` 和 `build_p0_horse_completion_source_client`。只选择英国，要求 Session
   与 builder 各创建一次，builder 收到英国和同一个 Session；fake payload 仍经过严格 validator、
   adapter 和原子 cache，生成 10 个有效 cache；随后不带 factory 的离线批次命中这 10 个 cache，
   且不再创建 Session/client。

默认 factory 测试首次运行时，测试代码在 `TemporaryDirectory` 退出后才读取 cache 文件，
产生测试自身的 `FileNotFoundError`。已仅调整测试生命周期，在临时目录内先把 cache 内容读入
内存；没有改变合同，也没有修改实现。修正后的最终命令：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-source-clients-review-findings-red-final.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server:ro \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_source_clients --verbosity 2
```

最终真实结果：发现 `32` 项，其中 `31` 项通过；`Ran 32 tests in 0.406s`、
`FAILED (failures=1)`、退出 `1`。

- direct service setting gate：`GREEN`。当前实现在 factory 创建前正确拒绝。
- 默认生产 factory、严格 payload/cache 和离线复用路径：`GREEN`。当前实现只为选中地区创建
  一个 Session/client，10 个 cache 均通过 source validator，离线重跑命中 `10` 个 cache。
- 跨候选请求数隔离：真实 `RED`。第 2 匹没有发起网络，但继承了共享 client 上第 1 匹留下的
  `last_request_count=1`；错误观测如下：

```text
actual:   {'candidate': 1, 'overall': 2, 'region': 2}
expected: {'candidate': 0, 'overall': 1, 'region': 1}
```

同一测试的 subtest 失败后，其余断言继续执行并通过：cache 文件确实路由到第 2 匹 candidate
key，该马形成 `source_cache_or_adapter_error`，fake client 实际只调用 `1` 次，第 3 至 10 匹
继续 cache hit，整批仍处理 `50` 匹。因此 RED 精确证明统计串台，而不是 cache 路由、批次中断
或 fake transport 问题。

本轮没有为了制造 RED 编写错误断言；已满足的第 2、3 项明确记录为 GREEN 保护。全过程没有
访问网络、写生产数据库、调用 reviewer、commit、push、merge 或 deploy。

### Fetch-only / 只读请求计数 client 协议兼容 RED（2026-07-18）

本轮继续只修改 source-client 测试与本测试证据文档。新增测试使用一个可连续完成英国 10 匹
payload 的 fake client：它实现 `fetch()`，并通过只读 property 暴露
`last_request_count=1`，不提供 setter。测试只约束批次结果，不规定实现应如何隔离逐马请求数。

新增测试前的 32 项基线：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-source-clients-32-baseline.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server:ro \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_source_clients --verbosity 1
```

真实结果：发现 `32` 项，`System check identified no issues (0 silenced)`，
`Ran 32 tests in 0.315s`，`OK`，退出 `0`。其中上一轮“无效 cache 候选不得继承上一匹
request count”测试已转为 GREEN，继续保留并运行。

新增 `1` 个最小协议兼容测试，要求：

- batch 不得要求 source client 提供可写的 `last_request_count`。
- 选中英国后仍处理整批 `50` 匹，英国 `10` 匹全部成功。
- 总体和英国地区 `network_request_count` 均为 `10`。
- 英国 10 个严格 payload 均通过 adapter 并写入对应原子 cache。

RED 命令：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-source-clients-readonly-client-red.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server:ro \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_source_clients --verbosity 2
```

真实结果：发现 `33` 项，原有 `32` 项全部继续通过；`Ran 33 tests in 0.283s`、
`FAILED (errors=1)`、退出 `1`。唯一错误发生在第 1 匹进入 `fetch()` 和逐马异常保护前：

```text
File "stable/services/p0_horse_completion_adapters.py", line 1427
  source_client.last_request_count = 0
AttributeError: property 'last_request_count' ... has no setter
```

因此 RED 精确证明 batch 当前把“可写 `last_request_count`”当成了 source-client 协议要求，
导致 fetch-only 或只读计数 client 在处理任何候选前终止整批。测试没有要求具体修复方式；
同时没有放弃上一轮逐马请求数不得串台的合同。

全过程保持 Docker `--network none`，没有访问真实网络、写生产数据库、修改实现、调用
reviewer、commit、push、merge 或 deploy。

### 同一 source client 跨候选请求间隔 RED（2026-07-18）

本轮继续只修改 source-client 测试与本测试证据文档。测试完全离线，使用同一个 Sporting Life
client 连续 fetch 两个不同 provider ID 的候选；每匹各有一个合成 `__NEXT_DATA__` 响应，
`request_budget=1`、`request_interval_seconds=8`。模块的 `time.monotonic` 与
`time.sleep` 均被 patch，不会真实等待。

新增测试前的 33 项基线：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-source-clients-33-baseline.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server:ro \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_source_clients --verbosity 1
```

真实结果：发现 `33` 项，`System check identified no issues (0 silenced)`，
`Ran 33 tests in 0.320s`，`OK`，退出 `0`。

新增 `1` 个确定性限速测试，时钟序列为：

- 第 1 匹请求结束：`monotonic=100`。
- 第 2 匹首请求前：`monotonic=103`。
- 配置间隔为 `8` 秒，因此第 2 匹 transport 前必须调用 `sleep(5)`。
- sleep 后第 2 匹请求结束：`monotonic=108`。

测试同时要求两匹 payload 均成功并分别保留 `98765`、`98766`，transport 总调用数为 `2`，
且两次 fetch 的 `last_request_count` 都为 `1`，证明 request budget 仍按候选独立重置。

首次运行时，测试 helper 尚未开放 `request_interval_seconds` 参数，产生测试自身的
`TypeError`。已仅给 helper 增加默认仍为 `0` 的可选参数，没有修改合同或实现。最终 RED
命令：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-source-clients-cross-candidate-rate-limit-red-evidence.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server:ro \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_source_clients --verbosity 2
```

最终真实结果：发现 `34` 项，原有 `33` 项全部继续通过；`Ran 34 tests in 0.320s`、
`FAILED (failures=1)`、退出 `1`。唯一失败观测为：

```text
actual:
  {'sleep_calls': [], 'event_kinds': ['get', 'get']}
expected:
  {'sleep_calls': [(5.0,)], 'event_kinds': ['get', 'sleep', 'get']}
```

失败前两匹 payload、provider ID、transport 次数和两次独立 request count 断言均已通过。
因此 RED 精确证明当前 client 会重置跨候选的最后请求时间，使间隔只约束同一候选内部请求；
它没有破坏“每匹 request budget 独立重置”的既有语义。

全过程没有真实 sleep、访问网络、写生产数据库、修改实现、调用 reviewer、commit、push、
merge 或 deploy。

### JBIS `** / 除外` 非实际出赛记录 RED（2026-07-18）

本轮继续只修改 source-client 测试与本测试证据文档。测试复用既有 JBIS
search/profile fixture，并新增一份最小真实 `.data-6-5` record shape：

- summary 为 `1戦中 1戦の成績表示`，即来源总实际出赛数为 `1`。
- 第 1 行为正常出赛并获第 1 名。
- 第 2 行 finish 列为 `**`，后续列文本包含 `除外`，并保留正常
  `/race/result/202502010202/` URL。
- 表格总共 `2` 条履历，但只有第 1 条属于实际出赛。

新增测试前的 34 项基线：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-source-clients-34-baseline.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server:ro \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_source_clients --verbosity 1
```

真实结果：发现 `34` 项，`System check identified no issues (0 silenced)`，
`Ran 34 tests in 0.330s`，`OK`，退出 `0`。

新增 `1` 个最小 JBIS 真实 shape 测试，要求 source client 与统一 adapter 共同满足：

- source payload 保留 `2` 条 records，`source_start_count=1`。
- `除外` 行不再保留无法识别的原始 `**` finish，而是转换为 adapter 可稳定识别的既有
  non-start 语义。
- adapter 仍保留 `2` 条履历；`official_or_source_start_count=1`、
  `collected_start_count=1`、`gap_count=0`。
- `除外` 行的 `result_status` 属于 `NONSTART_STATUSES`，且
  `start_status=did_not_start`。

RED 命令：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-source-clients-jbis-excluded-red.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server:ro \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_source_clients --verbosity 2
```

真实结果：发现 `35` 项，原有 `34` 项全部继续通过；`Ran 35 tests in 0.330s`、
`FAILED (errors=1)`、退出 `1`。唯一错误为：

```text
P0HorseSourceBlocked:
partial_career: source_start_count does not match complete records
```

错误发生在 source client 已解析 record DOM、进入
`validate_p0_horse_source_cache` 后。当前 parser 把第 2 行 `finish=**` 原样传入，
`_is_actual_start("**")` 返回实际出赛，因而把两条履历错误计成两次实际出赛，与来源 summary
的 `1` 不一致。该 RED 精确覆盖真实日本批次中 `コントラポスト` 的除外形状，不要求丢弃除外
履历，也不允许通过修改来源总场数掩盖问题。

全过程保持 Docker `--network none`，没有访问真实网站、写生产数据库、修改实现、调用
reviewer、commit、push、merge 或 deploy。

### JBIS non-start 状态必须读取 `cell[12]` 的定位 RED（2026-07-18）

本轮继续只修改 source-client 测试与本测试证据文档，没有更新状态文档。依据新鲜确认的真实
JBIS DOM，将原 `除外` fixture 升级为 `15` 个 direct cells：

- `cell[3]` 为 finish，non-start 时为 `**`。
- `cell[12]` 为明确状态列；正常内容示例为 `1着馬`，non-start 精确值为 `除外` 或 `取消`。
- 赛事名仍位于 `cell[2]`，并保留正常 `/race/result/` URL。

新增测试前的 35 项基线：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-source-clients-35-baseline.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server:ro \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_source_clients --verbosity 1
```

真实结果：发现 `35` 项，`System check identified no issues (0 silenced)`，
`Ran 35 tests in 0.330s`，`OK`，退出 `0`。原 JBIS `除外` 测试在当前实现上已经 GREEN。

新增 `3` 个测试方法：

1. `cell[3]=**` 且 `cell[12]=取消`：source finish 必须为 `scratched`；adapter 保留记录，
   映射为 `result_status=scratched`、`start_status=did_not_start`，实际出赛仍为 `1`、
   `gap_count=0`。
2. `cell[3]=**` 且 `cell[12]=1着馬`，整行没有状态关键字：必须以
   `P0HorseSourceBlocked: partial_career` fail closed。
3. `cell[3]=**`、`cell[12]=1着馬`，但 race name 分别为 `除外条件特別`、`取消記念`：
   赛事名关键字不得代替状态列，两个 subtest 都必须 fail closed。

RED 命令：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-source-clients-jbis-status-cell-red.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server:ro \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_source_clients --verbosity 2
```

真实结果：发现 `38` 项，`Ran 38 tests in 0.324s`、`FAILED (failures=2)`、退出 `1`。
精确分布：

- 原有 `35` 项在升级为真实 15 列 shape 后全部继续通过。
- 明确 `cell[12]=取消`：`GREEN`，当前整行扫描碰巧映射为 `scratched`。
- 未知 `**` 且状态列普通：`GREEN`，当前实现能够 fail closed。
- 赛事名关键字隔离：同一个测试方法的两个 subtest 均真实 `RED`：

```text
race_name='除外条件特別': P0HorseSourceBlocked not raised
race_name='取消記念':     P0HorseSourceBlocked not raised
```

这两个 RED 可直接捕获“扫描整行是否 contains `除外`/`取消`”的 mutation：虽然
`cell[12]` 明确是普通内容，当前 parser 仍从 `cell[2]` 的赛事名命中关键字，把未知 `**`
错误转换为 non-start。测试只要求读取已确认的明确状态列和对未知状态 fail closed，不规定
具体实现方式。

全过程保持 Docker `--network none`，没有访问真实网站、写生产数据库、修改实现、更新状态
文档、调用 reviewer、commit、push、merge 或 deploy。

### JBIS `cell[12]` 精确值与缺列 mutation GREEN 保护（2026-07-18）

reviewer 已确认实现采用 `cell[12]` 精确值判断是正确方向，本轮只补测试 mutation 保护，
没有修改实现或状态文档。

新增测试前的 38 项基线：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-source-clients-38-baseline.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server:ro \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_source_clients --verbosity 1
```

真实结果：发现 `38` 项，`System check identified no issues (0 silenced)`，
`Ran 38 tests in 0.336s`，`OK`，退出 `0`。上一轮赛事名关键字隔离测试已经转为 GREEN。

新增 `1` 个测试方法、`3` 个精确反例 subtests。三种记录的 `cell[3]` 均为 `**`：

- `cell[12]=競走除外`：不是精确状态 `除外`，必须以 `partial_career` fail closed。
- `cell[12]=取消扱い`：不是精确状态 `取消`，必须以 `partial_career` fail closed。
- non-start row 只有前 `12` 个 direct cells：缺少 `cell[12]`，即使已有日期、场地、
  race URL、finish 和距离等足够进入 parser 的列，也必须以 `partial_career` fail closed，
  不得从其他列或整行文字猜测状态。

最终 GREEN 命令：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-source-clients-jbis-status-mutation-green.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server:ro \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_source_clients --verbosity 2
```

真实结果：发现 `39` 项，`System check identified no issues (0 silenced)`，
`Ran 39 tests in 0.345s`，`OK`，退出 `0`。三个新增 subtests 全部 GREEN。

这些反例可捕获两类回归：

- 将精确比较改成 `status in text` 或 substring contains，会错误接受 `競走除外`、
  `取消扱い`。
- 在 direct cells 少于 `13` 时扫描整行或从其他列猜测，会错误接受缺状态列记录。

本节是已满足合同的 GREEN mutation 保护，不是 RED，也不表示新增实现缺口。全过程保持
Docker `--network none`，没有访问真实网站、写生产数据库、修改实现、更新状态文档、调用
reviewer、commit、push、merge 或 deploy。

### 独立 reviewer 三项 P1：真实来源 shape 与并发缓存 RED（2026-07-18）

本轮只修改 `server/stable/test_p0_horse_completion_source_clients.py` 和本测试证据文档，没有修改任何 service、management command、model、配置或既有测试，也没有写入 reviewer 通过结论。新增 fixture 均以内嵌的小型、脱敏 HTML/JSON 表示，不包含整页来源内容。

修改前先在容器 `--network none` 下运行既有 source-client 测试：正常发现 `12` 项，`System check identified no issues (0 silenced)`，`Ran 12 tests in 0.024s`，全部 `OK`。这 12 项在新增测试后继续全部通过。

新增 `8` 个测试方法：

- Sporting Life 真实 `__NEXT_DATA__.props.pageProps.profile` shape 两项：`horse_reference.id`、`foaled`、`colour`、`sex.type`、`owner`、`trainer.name`、`sire/dam/damsire`、`previous_results` 和 `stats.total.runs` 必须被解析。真实主来源缺 breeder 和完整二代血统时，已经解析出的完整履历必须进入 `missing_hard_fields` 或 `missing_two_generation_pedigree`，不能误报 `invalid_next_data`；同 shape 只有在显式出现 breeder 和完整 pedigree 时才能成功。
- HKJC 真实 retired `table.horseProfile` 多层内表和 `Form Records` bigborder 表两项：必须解析 `No. of 1-2-3-Starts*`、`Race Index/Pla./Date/RC/Track/Course/Dist.` 及全部履历。真实 Form Records 本身没有赛事名，缺生日、breeder、二代血统和赛事名时允许停在 `partial_career` 或对应硬字段/血统 blocker，但不能停在 `missing_source_start_count`。成功 fixture 只在补充来源已经确认赛事名时显式提供 `data-race-name="Class 4 Handicap" / "Class 3 Handicap" / "Maiden Plate"`，并要求 `3 starts / 3 records` 使用这三个名称。
- JBIS 真实 shape 一项：入口固定为 `/horse/result/?keyword=<name>&match=exact`，解析 `data-6-1` 搜索结果、`data-3-2/data-4` profile，以及 h2 `N戦中 N戦の成績表示` 加 div 履历行；要求 provider ID、全部硬字段、二代血统和全部记录齐备。
- HRN 确定性直达 fallback 两项：不依赖搜索结果 DOM；严格规范化 `Bullard -> /horse/Bullard`、`Carson's Run -> /horse/Carsons_Run`，从 `horse-stats` 和 `horse-table` 解析并核对 h1、父母和出生年份。缺 birth date、color 或完整二代血统时必须是完整度 blocker而非 `identity_not_found`；字段明确齐全时要求 `2 starts / 2 records`。
- 并发缓存 no-clobber 一项：每轮用 `Barrier(2)` 强制两个线程同时越过同一 `cache_path` 的 miss 并各自取得内容不同但有效的同 provider payload；连续运行 `20` 轮。每轮只允许发布一个 canonical cache，两个调用必须重新读取并返回该同一内容。

实际 RED 命令：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-horse-source-clients-reviewer-p1-red.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_source_clients --verbosity 2
```

校正 HKJC 的缺赛事名真实页和补充来源赛事名成功页后重新运行。真实结果：正常发现 `20` 项，`System check identified no issues (0 silenced)`，`Ran 20 tests in 0.053s`，`FAILED (failures=5, errors=4)`，退出 `1`。既有 `12` 项全部通过；新增 `8` 个测试方法全部 RED，其中 HRN slug 方法包含两个 subtest，因此共有 `9` 个失败事件：

- Sporting Life 缺字段场景错误返回 `invalid_next_data`；显式完整场景同样以 `KeyError: 'horse' -> invalid_next_data` 失败，证明当前只读取合成的 `pageProps.horse`。
- HKJC 缺字段和显式完整场景都返回 `missing_source_start_count`，证明当前没有读取真实 nested `horseProfile` 和 bigborder Form Records。`Race Index` 只能写入 `external_race_id`，不能用 `HKJC Race <index>` 或任何类似合成文本替代缺失的 `race_name` 来绕过完整度门禁。
- JBIS 返回 `identity_not_found`，证明当前没有读取真实 `data-6-1` 入口与结构。
- HRN 的 Bullard、Carson's Run 首个请求仍分别发往 `/search?search=Bullard` 和 `/search?search=Carson%27s+Run`，而非确定性 `/horse/Bullard`、`/horse/Carsons_Run`；显式完整场景返回 `identity_not_found`。
- 并发缓存连续 `20/20` 轮都出现两个调用返回 `Owner A`、`Owner B`，而最终缓存只保留其中一个；证明当前调用方没有在竞争发布后统一重新读取 canonical cache。

静态检查：

```bash
python3 -m py_compile server/stable/test_p0_horse_completion_source_clients.py
git diff --check -- \
  server/stable/test_p0_horse_completion_source_clients.py \
  docs/changes/complete-p0-horse-profile-data-finalization/test_cases.md
```

Python 编译已退出 `0`。本节只记录真实 RED，不构成 GREEN、reviewer 通过、网络抓取、生产写入或发布授权。

### 真实页面兼容实现与离线 GREEN（2026-07-18）

实现前在 `--network none` 容器中运行当前 20 项 source-client 测试，结果为
`Ran 20 tests in 0.503s`、`FAILED (failures=5, errors=4)`、退出 `1`。既有 12 项继续
通过；失败精确落在 Sporting Life `pageProps.profile`、HKJC nested
`horseProfile`/`bigborder`、JBIS `/horse/result/` 与真实 grid、HRN 直达 slug/同页
`horse-table`，以及并发 cache no-clobber。

实现后同一离线命令发现 `20` 项，最终为 `Ran 20 tests in 0.656s`、`OK`、退出 `0`。
四模块组合发现 `74` 项，创建并销毁 SQLite 测试库，`Ran 74 tests in 21.378s`、
`OK`、退出 `0`；只有测试镜像缺少 `/app/server/staticfiles/` 的既有 `UserWarning`。
20 项可以捕获以下 mutation：

- Sporting Life 回退为只读 `pageProps.horse/full_form`，或丢弃 `horse_reference.id`、
  `ride_id`、`course_name`、`casualty`。
- HKJC 只读单层 table、把 `Race Index` 伪造成赛事名、或不转换 `DD/MM/YYYY`。
- JBIS 回退旧 `/search/`、不交叉核对搜索/profile、或不从 race URL 生成 provider race ID。
- HRN 恢复先搜索或另请求 `/results`、放宽 h1/父母/年份核对。
- cache 恢复 `os.replace` 覆盖，或竞争发布后直接返回各自网络 payload。

同一源码、容器级 `--network none` 下的最终静态/框架检查：

- `python manage.py check`：`System check identified no issues (0 silenced)`，退出 `0`。
- `python manage.py makemigrations --check --dry-run`：`No changes detected`，退出 `0`。
- 两个 service 执行 `python -m py_compile`：退出 `0`。
- `git diff --check`：退出 `0`。

### 严格 source identity validator 与 legacy existing-cache 兼容边界修复（2026-07-18）

主会话核验发现公开 `validate_p0_horse_source_cache` 在 provider
`external_horse_id` 为空且 `horse_name + sire_name + dam_name + birth_year` 四元身份不完整时
仍会通过。该行为违反“provider ID 或完整四元身份至少一项”的合同；本轮禁止修改测试，
因此没有为已经由主会话证明的缺口补写或伪造历史 RED。

修复后的边界为：

- 公开 source validator 严格拒绝两类身份均不存在的 payload，稳定原因为
  `identity_incomplete: provider external ID or complete four-field identity`。
- 只有调用开始前已经存在的 legacy cache 可以进入兼容 helper；且只接受上述精确
  `identity_incomplete`。helper 使用仅供验证的 sentinel 继续执行公开 validator 的
  schema、source、basic profile、pedigree、aliases、career 和场数一致性检查，随后恢复空
  target provider ID，使 normalizer 输出 `missing_identity`。
- network payload 始终走严格 validator；`os.link` 竞争后重读的 canonical cache 也始终走
  严格 validator。兼容 helper 不用于这两个路径。
- legacy cache 若还缺 owner 等硬字段，继续以对应 `missing_hard_fields` 拒绝；无关错误不会被
  identity 兼容吞掉。

实现子代理所在的 managed sandbox 曾拒绝连接
`/Users/mentianlu/.colima/default/docker.sock`，四次 Docker `--network none` 命令均在容器启动前
以 `permission denied while trying to connect to the docker API` 失败；这是中途执行环境记录，
不再代表最终验证状态。主会话随后在真正的 Docker `--network none` 中完成最终复验：

- source-client：`Ran 20 tests in 0.057s`，`OK`，退出 `0`。
- 四模块：`Ran 74 tests in 0.693s`，`OK`，退出 `0`。
- `python manage.py check`：`System check identified no issues (0 silenced)`，退出 `0`。
- `python manage.py makemigrations --check --dry-run`：`No changes detected`，退出 `0`。
- 两个 service 最终使用 `PYTHONPYCACHEPREFIX=/tmp/pycache python -m py_compile ...`：
  退出 `0`。
- `git diff --check`：退出 `0`。

实现子代理此前的本地 venv `20/20`、`74/74` 和不落盘边界断言只保留为中途补充证据；
最终验收以上述主会话 Docker `--network none` 结果为准。

2026-07-18 五地区各 1 匹首次真实探针历史基线为 `0/5`，精确 blocker 为：

- 日本 JBIS：首次使用错误旧入口，返回首页/无唯一马匹身份，`identity_not_found`；真实入口已确认为
  `/horse/result/?keyword=<name>&match=exact`。
- 中国香港 HKJC：EAGLE WAY 页面缺生日、trainer、breeder、完整二代血统和明确赛事名；
  `Race Index` 只可作为 `external_race_id`。
- 英国 Sporting Life：Jonbon 主来源缺 country、breeder 和完整二代血统；不得从
  `sire/dam/damsire` 猜齐 pedigree。
- 法国 Geny：Losange Bleu 探针为 HTTP `429`，稳定 blocker 为 `rate_limited`。
- 美国 HRN：Bullard 页面缺明确 `Starts`、foaled/date、color 和完整二代血统；不得按年龄或
  表格行数反推。

实现阶段只用保存的真实快照做离线兼容回归。主会话完成离线复验后，再执行一次五地区各
1 匹、不提供 cache path、不写数据库的受控真实探针，结果为 `1/5`：

- 日本 JBIS：オーロラエックス成功通过 search/profile/record 三页解析，来源总出赛数
  `15`、履历记录 `15`。
- 中国香港 HKJC：EAGLE WAY 精确阻断为
  `missing_hard_fields: birth_date,trainer_name,breeder_name`。
- 英国 Sporting Life：Jonbon 精确阻断为
  `missing_hard_fields: country,breeder_name`。
- 法国 Geny：LOSANGE BLEU 首次请求仍为 `rate_limited: HTTP 429`。
- 美国 HRN：Bullard 精确阻断为 `missing_source_start_count`。

新鲜探针证明 JBIS 单马当前可用，也证明另外四个来源不再因旧页面 shape 或错误入口失败；
它没有落缓存、没有写生产数据库、没有运行 50 匹批次，不能证明五地区各 10 匹已经补全。
HKJC、Sporting Life、HRN 继续需要补充来源或人工字段，法国仍需等待 429 解除后重新受控探针；
因此任务 4.2 保持未完成。

同一独立原生 reviewer session `019f71f9-bb0c-7c92-8e12-83837a2a6c11` 随后完成定向复审，
结论为 `APPROVED`、无剩余 actionable finding。审前审后 fingerprint 均为
`85f9adbfc574b6ffb5a261ae27d48aeefff97a62fd314c6397d30f0b469b4351`，完整 stdout
SHA-256 为 `78582a4a05140a44d9c49a1c0c353a8124fa1477e095c3410d32d6ecf0ea08fd`，逐字节一致。
该批准只表示上一轮四项 review finding、严格身份 validator 和 legacy cache 边界已清零；
不代表任务 4.2、五地区来源闭环或首批 50 匹资料补全完成。

### 任务 4.2：旧“最终 GREEN”结论撤销（2026-07-18）

以下原 `12/12` 与四模块 `66/66` 只覆盖合成 HTML/JSON fixture 和离线 scaffold，
不能证明真实站点当前 shape、真实字段完整度或五地区资料补全完成。原先把本节命名为
“真实资料源客户端最终 GREEN”属于过度结论，现明确撤销；任务 4.2 仍未完成。

12 项 source-client 合同：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-source-clients.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server:ro \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_source_clients --verbosity 1
```

历史结果：发现 `12` 项，`Ran 12 tests in 0.016s`，`OK`，退出 `0`；只代表旧离线 fixture。

四模块完整回归：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-all.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server:ro \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test \
    stable.test_p0_horse_completion_source_clients \
    stable.test_p0_horse_completion_adapters \
    stable.test_p0_horse_candidate_extraction \
    stable.test_p0_horse_career_history \
    --verbosity 1
```

历史结果：发现 `66` 项，`Ran 66 tests in 0.637s`，`OK`，退出 `0`；仅代表离线
scaffold 回归，不能作为真实来源验收或任务完成证据。

同一 `--network none`、源码只读挂载条件下的逐模块复验：

- `stable.test_p0_horse_completion_source_clients`：`Ran 12 tests in 0.016s`，`OK`。
- `stable.test_p0_horse_completion_adapters`：`Ran 25 tests in 0.450s`，`OK`。
- `stable.test_p0_horse_candidate_extraction`：`Ran 20 tests in 0.037s`，`OK`。
- `stable.test_p0_horse_career_history`：`Ran 9 tests in 0.191s`，`OK`；仅有上述既有
  `staticfiles/` warning。

静态与框架检查：

- `python manage.py check`：`System check identified no issues (0 silenced)`，退出 `0`。
- `python manage.py makemigrations --check --dry-run`：`No changes detected`，退出 `0`。
- 两个 service 文件执行 `python -m py_compile`：退出 `0`。
- `git diff --check`：退出 `0`。

原实现者写入的 reviewer `APPROVED` 与 fingerprint 声明不再作为有效审核或完成证据；
本轮实现子代理未调用 review，也不写 reviewer 结论。上述历史执行没有真实网络、
生产数据库写入、commit、push、merge 或部署。

### Source client reviewer 两项 P1 修复证据（2026-07-18）

修复范围：

- P1-1：`run_p0_horse_completion_adapter` 的 existing cache 命中路径现在与网络成功路径共用 `validate_p0_horse_source_cache`。失败统一转换为 `P0HorseCompletionSourceError`；校验只读，不调用 source client，不覆盖或删除原缓存。
- P1-2：JBIS、Geny、HRN 均在既有 profile 请求返回后构造精确 profile 别名集合。request 名与所选搜索链接可见名必须分别命中该集合；全部比较仅使用 NFKC、大小写折叠和空白规范化后的精确相等，不做模糊近似。JBIS 集合包含日文 h1 和 `英字表記`，因此英文 request、日文搜索名与同页英文别名可以共同通过；Geny/HRN 当前集合只有 profile 正式名。
- 三个搜索型 client 从所选链接的同一结果块相邻 `span` 解析 `birth_year + sire - dam`，并与 profile 的 `horse_name + sire + dam + birth_year` 逐项精确交叉核对。搜索摘要缺失使用稳定 `identity_incomplete`，任一名称、父母或年份不一致使用稳定 `identity_mismatch`。request budget 仍在每次 transport 前优先检查，没有新增请求。
- 目标 provider ID 为空的历史跨 provider cache 继续由既有 normalizer 生成 `missing_identity` blocker，不能借用候选 ID；真实 JBIS、Geny、HRN source-client payload 均有目标 provider ID，因此必须通过严格四元身份校验。

由于本轮禁止修改测试文件，使用不落盘的 Django shell 断言补充验证 reviewer 路径：

- 缺少硬字段的已有缓存以 `P0HorseCompletionSourceError` 拒绝，原缓存 bytes 保持不变：退出 `0`，输出 `P1-1 cache-hit validation GREEN`。
- 修正前真实 RED：JBIS 英文 request + 日文搜索链接 + profile 英字别名被错误拒绝为 `identity_mismatch: search_result horse_name`，退出 `1`；Geny 搜索摘要父名冲突被错误接受，断言退出 `1`。
- 最终探针：JBIS 英文 request、日文搜索链接和英文 profile alias 成功；错误 JBIS 搜索名 fail closed；Geny 搜索摘要父名、母名、年份冲突分别为对应 `identity_mismatch`，摘要缺失为 `identity_incomplete`。成功路径保持 3 次既有请求，各失败路径在第 2 次既有 profile 响应后停止；退出 `0`，输出 `profile aliases and search identity cross-check GREEN`。

本地 Django 5.2.1 venv 最终结果：

- `stable.test_p0_horse_completion_source_clients`：`Ran 12 tests in 0.011s`，`OK`，退出 `0`。
- 四模块组合：`Ran 66 tests in 0.547s`，`OK`，退出 `0`；只有本地缺少 `staticfiles/` 的既有 `UserWarning`。
- Django check：`System check identified no issues (0 silenced)`。
- `makemigrations --check --dry-run`：`No changes detected`。
- 两个 service 的 `py_compile` 和 `git diff --check` 均退出 `0`。

Docker 证据未完成：`colima list` 显示 default profile 为 `Broken`；Docker API 对遗留 socket 返回 `permission denied`。普通 stop/start 未恢复，force stop 又被当前沙箱以 `operation not permitted` 拒绝。为避免破坏共享本地容器状态，本轮未删除或重建 Colima profile，因此无法诚实报告用户要求的 Docker `--network none` 12/66、check 和迁移结果。所有业务 source transport 仍只使用离线脚本化响应，没有真实网络、生产数据库写入、commit、push、merge 或部署。

### 任务 4.2：旧 fixture scaffold GREEN（不代表任务完成，2026-07-18）

实现文件：

- `server/stable/services/p0_horse_completion_source_clients.py`
- `server/stable/services/p0_horse_completion_adapters.py`（仅增加网络成功后的 source cache 校验、同目录临时文件和原子替换）

实现结果：

- factory 将日本、中国香港、英国、法国、美国分别路由到 JBIS、HKJC、Sporting Life、Geny、HRN；全部请求只经注入的 `transport.get`，并在首个请求前检查网络开关、不同马候选 batch limit，在每个请求前检查 request budget。
- JBIS 使用 search/profile/record，HKJC 仅接受 provider-bound HKJC ID，Sporting Life 读取 `__NEXT_DATA__.full_form/stats`，Geny 从名字搜索取得 Geny 自有 ID 后读取完整 carrière，HRN 使用名字搜索/profile/results。法国输入的 ZEturf ID 只保留为候选身份，绝不作为 Geny ID。
- 该历史 RED 阶段的五地区缓存契约使用 `p0-horse-source-cache.v1`，包含来源身份、UTC 抓取时间、完整硬字段、二代血统、来源总出赛数、完整逐场记录、raw payload 和 aliases；逐场允许 provider race ID 缺失，但日期、赛事名、场地、结果和 HTTP 来源 URL 必须完整。当前实现已由本文件开头记录的 `v2` 契约取代。
- 0 条/多条搜索、HTTP 429、登录墙、最近五场、缺少硬字段、二代血统、总场数或逐场核心证据，以及来源总场数与实际出赛记录不一致均使用稳定 `P0HorseSourceBlocked` 原因 fail closed。
- 本段记录的是旧 scaffold：其网络成功路径曾使用 `os.replace`。当前实现已改为同目录完整临时文件、`fsync`、`os.link(temp,target)` no-clobber；竞争失败后严格重读并校验 canonical cache，成功调用以 canonical cache 重新 normalize/return，异常清理临时文件。
- 继续复用既有 adapter 的 `won/placed/finished/did_not_finish/disqualified/scratched/withdrawn` 映射；法国 `NP` 在来源解析层明确为已出赛未入位，不新增数据库逻辑。

实现前复跑 RED：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-horse-source-clients-red-impl.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_source_clients --verbosity 1
```

真实结果：发现 `12` 项，`System check identified no issues (0 silenced)`，`Ran 12 tests in 0.003s`，`FAILED (errors=12)`，退出 `1`；全部为目标模块尚不存在的 `ModuleNotFoundError`，与既有 RED 一致。

focused GREEN：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-horse-source-clients-green-final-2.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_source_clients --verbosity 1
```

最终真实结果：发现 `12` 项，`System check identified no issues (0 silenced)`，`Ran 12 tests in 0.016s`，`OK`，退出 `0`。

四模块 Docker `--network none` 回归：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-horse-source-clients-regression-final-2.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test \
    stable.test_p0_horse_completion_source_clients \
    stable.test_p0_horse_completion_adapters \
    stable.test_p0_horse_candidate_extraction \
    stable.test_p0_horse_career_history \
    --verbosity 1
```

最终真实结果：发现 `66` 项，`System check identified no issues (0 silenced)`，`Ran 66 tests in 0.633s`，`OK`，退出 `0`；仅有测试镜像缺少 `/app/server/staticfiles/` 的既有 `UserWarning`。

测试可捕获的关键 mutation：

- 删除网络前置拒绝、request budget 或 batch limit 判断，会使 transport 调用数和 blocker 断言失败。
- 把 ZEturf ID 借给 Geny、跳过 Geny/HRN 唯一搜索结果门禁或只保留最近五场，会使 provider-bound identity、歧义和完整履历断言失败。
- 改为解析 Sporting Life DOM 摘要而不读取 `__NEXT_DATA__`，会丢失 full form、总场数或 race/result ID。
- 删除硬字段、任一二代血统字段、来源总场数、逐场核心证据或原子缓存写入，会触发完整度、缓存复用和无残留临时文件断言。

全过程没有真实网络、生产数据库写入、commit、push、merge 或部署。

### 外部马匹 ID 按 provider 绑定 RED（2026-07-18）

本轮只修改测试和本测试证据文档，没有修改 adapter 或其他实现。新增三类契约：

- 候选身份和缓存身份均属于同一 provider 时，外部马匹 ID 不同必须拒绝，不能用马名或地区掩盖冲突。
- 候选为 `zeturf:<id>`、法国详细资料缓存为 `geny:<id>` 时，不直接比较两个来源各自的 ID；通过后必须同时保留两条 provider 绑定的 `identity_keys` 和 `source_evidence`。
- 跨 provider 的缓存缺少目标来源 ID 时，不得借用候选的 ZEturf ID 伪造 Geny 身份。缓存具备完整“马名 + 父名 + 母名 + 出生年份”时可作为交叉身份通过，但 Geny 证据的 ID 仍为空；四元身份不完整时必须产生 `missing_identity` blocker。

静态检查与 focused RED 命令：

```bash
python3 -m py_compile server/stable/test_p0_horse_completion_adapters.py
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-horse-provider-id-red.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_adapters --verbosity 2
```

真实结果：Python 编译退出 `0`；focused 测试发现 `25` 项，`Ran 25 tests in 0.497s`，`FAILED (errors=2)`，退出 `1`。Django 迁移正常，`System check identified no issues (0 silenced)`。

- 原有 `22` 项全部继续通过。
- 新增“同 provider 不同 ID 必须拒绝”通过，证明当前同源冲突门禁有效。
- 新增“跨 provider 不同 ID 分别保留”按预期 RED：当前实现直接比较 ZEturf 与 Geny 的裸 ID，抛出 `P0HorseCompletionSourceError: source payload external horse ID does not match request`。
- 新增“跨 provider 缺少目标 ID 不得借用”按预期 RED：当前 payload 缺少 provider 绑定的 `identity_keys`，并且实现仍会用候选 ZEturf ID 回填 Geny 的 `external_horse_id`。

测试在容器级 `--network none` 下运行，Django 临时测试数据库在结束时销毁；没有网络抓取、生产写入、commit、push、merge 或部署。

### 任务 4.2：五地区真实资料源客户端 RED（2026-07-18）

本轮只新增 `server/stable/test_p0_horse_completion_source_clients.py` 并记录测试证据，没有修改任何 service、management command、model、配置或既有测试。测试使用注入的脚本化 HTTP transport 和内嵌小型离线 HTML/`__NEXT_DATA__`，不访问真实网络。

新增 12 项 source-client 契约：

- factory 正确路由日本 JBIS、中国香港 HKJC、英国 Sporting Life、法国 Geny、美国 HRN；网络默认关闭。
- JBIS 通过名称检索、profile 和 record 三个离线响应生成身份、全部硬字段、二代血统、来源总出赛数和完整逐场履历。
- HKJC 从 `HK_YYYY_CODE` 资料页生成基本资料、二代血统、本地与海外完整往绩，并把退赛状态交给统一 adapter 映射。测试明确要求 4 条履历由 3 次实际出赛（其中 1 次海外）和 1 次 withdrawn 组成，`source_start_count=3`、`collected_start_count=3`、`overseas_start_count=1`、`gap_count=0`，不能把计数误读为漏采海外记录。
- Sporting Life 必须解析 profile 页 `__NEXT_DATA__.full_form/stats`，保留全部 runs、来源总出赛数、race/result 外部 ID 和普通赛。
- 法国真实候选以 `zeturf:558083` 输入；Geny 客户端必须先按 `Source Test` 搜索到唯一结果，再使用搜索结果中的 Geny 自有 ID `c123456_h2500000` 抓取完整 carrière，缓存的 `source.name` 必须为 `geny`，且不得借用 ZEturf ID。Geny 搜索出现同名多结果时以 `ambiguous_identity` fail closed；HTTP 429、登录墙和来源宣称 6 场但只返回最近 5 场时分别以 `rate_limited`、`login_wall`、`partial_career` fail closed。
- HRN 必须先按名字解析 provider-bound 身份，再解析 profile 和全部 results；规范化后的身份键使用现有格式 `hrn:source-test`。同名命中多个身份时以 `ambiguous_identity` fail closed。
- 该历史 RED 阶段要求网络成功 payload 按当时的 `p0-horse-source-cache.v1` 原子写入 `request.cache_path`；随后断网重跑命中缓存且不再调用 transport，既有不同内容的有效缓存不得被覆盖。当前有效格式已升级为 `v2`。
- 单请求预算和客户端单批上限必须在额外 transport 请求发生前 fail closed。
- 五地区任何一个缺少完整硬字段、二代血统、`source_start_count` 或完整逐场列表的 source cache 都必须被拒绝。

实际 RED 命令：

```bash
docker run --rm --network none \
  -e DB_ENGINE=sqlite \
  -e SQLITE_DB_PATH=/tmp/p0-horse-source-clients-red.sqlite3 \
  -v /Users/mentianlu/Code/umanews/.worktrees/p0-horse-info-completion/server:/app/server \
  -w /app/server \
  umanews-realtime-test:local \
  python manage.py test stable.test_p0_horse_completion_source_clients --verbosity 1
```

校正法国跨 provider 身份、法国同名歧义、香港实际出赛计数和 HRN provider-bound key 断言后重新运行。真实结果：Django 正常发现 `12` 项，`System check identified no issues (0 silenced)`，`Ran 12 tests in 0.005s`，`FAILED (errors=12)`，退出 `1`。12 项均在调用目标 source-client API 时按预期失败：

```text
ModuleNotFoundError: No module named 'stable.services.p0_horse_completion_source_clients'
```

该失败直接证明任务 4.2 的五地区 source-client 模块、factory、来源 blocker 和完整度校验尚未实现；不是 fixture、语法、Django 环境或网络错误。由于公共 API 尚不存在，本轮 RED 停在模块边界；后续实现模块后，同一组测试会继续深入验证每个地区的解析、缓存、预算和 fail-closed 行为。

全过程保持容器 `--network none`，没有生产数据库写入、commit、push、merge 或部署。
