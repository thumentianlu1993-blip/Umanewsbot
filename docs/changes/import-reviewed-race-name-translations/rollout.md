# 已审核赛事中文名统一导入预演交付与发布边界

## 在途边界

- 工作目录：`/Users/mentianlu/Code/umanews/.worktrees/translate-collected-race-horse-names`
- 分支：`codex/translate-collected-race-horse-names`
- 本轮复用既有五区审核任务，不影响其他 worktree、历史详情 runner 或赛事直播任务。
- 现有未提交文档和审核产物属于本任务，禁止清理或覆盖。

## 安全检查点

1. 输入文件 SHA、行数和原始 Markdown 身份列逐行锁定；日本修订前基线 SHA 固定，修订后只允许序号 64 的一个译名单元格变化。
2. 方案审核通过。
3. 本地测试取得 RED 后实现并转 GREEN。
4. 生产只读快照前确认权威服务器和现有 web 容器；只用 `docker exec`，并保存查询前后全字段摘要。
5. 生成新时间戳目录，保留 manifest、before、dry-run、rollback 和 Excel 报告。
6. 最终原生只读 review 发现香港 Event 改绑未同步 HistoricalRaceEventTarget 的 P1；已把 target `49052` 纳入三模型完整行 CAS、同步改绑、唯一性检查、rollback 和独立 verifier，旧候选失效。
7. 连续复审进一步发现日本单格修订、工作簿同字节解析、Markdown 分组摘要、让赛清理、完整 XLSX 布局、回滚审计键、备份字节数、rollback bundle 身份绑定、范围外公开 Event 96 遗漏和 JSON 数值词法丢失问题；均已修复。日本最终表改为原 XLSX 包单点 OOXML 修订，回滚 artifact SHA 与回滚后聚合 SHA 分别记录和验证，中文名同时隐藏中英文让赛标记且不误删 `H. Allen`；Event 96 以全字段精确 allowlist 纳入，生产快照分块传输并保留 `1.0` 等数值词法。
8. 最新复审发现 commit 数量门仍要求 8663、rollback verifier 会拒绝 artifact 精确恢复的旧让赛名、Event 96 在 marker-free 名称漂移时可能静默遗漏三个 P1；已分别改为 1300/8664 固定门、仅 applied 模式执行让赛零残留检查、固定 Event ID 始终分类，并补齐 already-applied/conflict/missing/rollback 回归。当时生成候选 `unified-import-preview-20260720T001537Z`，后被下一轮内存 finding 判为失效。
9. 后续复审关闭上述三个 P1，但发现三份大型 JSON 同时展开令 CLI RSS 超过 500 MiB 的 P1，以及 `（Handicap）` 留空括号的 P2。执行/验证现只展开紧凑 plan，完整 rollback 保持归档；before 全行 SHA、稳定字段 SHA、restore 值和整批聚合 SHA 共同维持 CAS，metadata 再以四个大文件原始 SHA 绑定 bundle index。
10. 对候选 `T005755Z` 的复审进一步发现 219 场同系列原文回退 Event 未随 Series 翻译，以及 verifier 只按稳定 batch ID 选择日志。现已把这 219 场逐场纳入地区/系列/锁保护的补充动作，并把日志的八项 bundle/artifact SHA 与当前 index/metadata 逐项绑定。
11. 对候选 `T012707Z` 的复审发现事务只锁动作 IDs、lossless 重建未重算双层 SHA、snapshot 后未复核运行时元数据。现已在 plan 冻结 `1301` 个系列下完整 `8885` 场 Event，事务锁父系列与全量子行，生成器重算逐行/整体 SHA 并对 snapshot 前后 metadata 做精确比较。当前唯一候选为 `unified-import-preview-20260720T020815Z`，目标计数 `1300/8883/1`。
12. 对候选 `T020815Z` 的复审继续发现非动作父 Series 未做完整行 CAS、非 allowlist 独立中文名边界不严和 supplemental seriesKey 漂移未阻断。三项已修复并补负向测试；两次重生成均因生产 SSH banner/metadata 连接超时 fail closed，未形成新 artifact，旧候选继续失效。
13. 用户审核 dry-run 后更正“京成杯秋季赛”并授权继续；受审内容改变，必须重新生成、复审，并在最新成功 review 后重新取得发布授权。
14. 正式 apply 前从审核后不可变提交取出确定性 bundle 归档，先核对 archive SHA，再解包并在宿主/容器/每个执行阶段校验同一 bundle-index SHA。
15. 正式 apply 前创建并验证 current custom-format 备份；先 verify-only，再单事务 commit，再独立 verifier。

## 失败与恢复

- 输入、结构、身份、manual lock 或生产快照任一不符：保留失败报告，`apply_ready=false`，不尝试修补生产数据。
- SSH/容器/数据库查询失败：不使用旧快照冒充当前 dry-run；报告 blocked。
- 运行中断：旧产物目录保持只读，使用新 run ID 重跑。
- 香港 Event/历史目标任一缺失、身份不一致或目标系列/年份冲突：单独列出事实并停止整个批次，不降级为仅写中文名或只改一侧。
- 任一 CAS 漂移、锁、唯一约束或 OperationLog 失败：整个数据库事务回滚，禁止拆批续写。
- 写后业务 verifier 失败且全部目标仍等于本批 after：使用受审 `--rollback-commit` 做对象级单事务回滚，再运行独立 rollback verifier。
- rollback after-state CAS 漂移：禁止强制覆盖，保留 bundle、日志和备份，转入人工事故处理；整库恢复前必须停写、再做事故现场备份并评估备份以来的其他合法数据。

## lowcost custom-format 备份与恢复

权威目录 `/opt/umanewsbot`，Compose 文件固定为 `docker-compose.prod.lowcost.yml`。从 `.env` 读取数据库名/用户但不打印凭据；备份在宿主机私有目录创建，先写 `.incomplete`：

```bash
set -Eeuo pipefail
umask 077
backup_dir=/opt/umanewsbot/backups/race-name-translation
mkdir -p "$backup_dir"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
partial="$backup_dir/pre-race-name-translation-$stamp.dump.incomplete"
final="${partial%.incomplete}"
db_container=""
container_partial="/tmp/race-name-translation-$stamp.dump.incomplete"
cleanup() {
  rm -f "$partial"
  if [ -n "$db_container" ]; then
    docker compose -f docker-compose.prod.lowcost.yml exec -T db \
      rm -f "$container_partial" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT
docker compose -f docker-compose.prod.lowcost.yml exec -T db sh -lc \
  'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-privileges' \
  >"$partial"
test -s "$partial"
backup_size_bytes="$(stat -c '%s' "$partial")"
printf '%s\n' "$backup_size_bytes" | grep -Eq '^[1-9][0-9]*$'
chmod 600 "$partial"
test "$(stat -c '%a' "$partial")" = "600"
pg_dump_version="$(docker compose -f docker-compose.prod.lowcost.yml exec -T db pg_dump --version)"
pg_restore_version="$(docker compose -f docker-compose.prod.lowcost.yml exec -T db pg_restore --version)"
printf '%s\n' "$pg_dump_version" | grep -Eq 'PostgreSQL\) 16([.]|$)'
printf '%s\n' "$pg_restore_version" | grep -Eq 'PostgreSQL\) 16([.]|$)'
backup_sha256="$(sha256sum "$partial" | awk '{print $1}')"
test "${#backup_sha256}" -eq 64
db_container="$(docker compose -f docker-compose.prod.lowcost.yml ps -q db)"
test -n "$db_container"
docker cp "$partial" "$db_container:$container_partial"
docker compose -f docker-compose.prod.lowcost.yml exec -T db \
  pg_restore -l "$container_partial" >/dev/null
docker compose -f docker-compose.prod.lowcost.yml exec -T db \
  rm -f "$container_partial"
mv "$partial" "$final"
trap - EXIT
printf 'backup=%s\nsize_bytes=%s\nsha256=%s\npg_dump=%s\npg_restore=%s\n' \
  "$final" "$backup_size_bytes" "$backup_sha256" "$pg_dump_version" "$pg_restore_version"
```

脚本按原样以 fail-fast 方式执行；任一命令非零、文件为空、字节数不是正整数、权限不是 `0600`、版本不是 PostgreSQL 16、SHA 未记录或目录校验失败都会触发 trap 清理宿主和容器临时文件。只有 `.incomplete` 上的全部验证成功后，最后一步才原子改名为正式恢复点；输出的 `size_bytes` 与 `sha256` 必须原样传给 apply 的 `--backup-size-bytes` 和 `--backup-sha256`，`.incomplete` 永远不得作为恢复点。

对象级 rollback 是当前批次的首选恢复。只有其 after CAS 不能安全执行、且人工确认必须整库恢复时，才进入事故恢复。恢复前必须 fail closed 完成写入者清场：

1. 在停止服务前保存 `celery inspect active` 与 `reserved`，两者必须为空；有任务时先撤销/排空并复核。
2. 停止 Compose 的 `web/worker/beat/race_live_worker`，并按 `docs/project_overview.md` 所列独立历史 runner 逐个确认 PID、容器或 systemd 单元后停止；禁止假定它属于 Compose project。
3. 枚举宿主 `docker ps`、systemd、`ps` 中的 Django/Celery/historical/importer/one-off 进程，任何未归类写入者均阻断。
4. 仅保留 `db`，从数据库容器查询 `pg_stat_activity`；目标库除当前检查/恢复连接外的会话数必须为零。发现 application、one-off/importer 或未知连接时先终止来源并重新核对，不能边恢复边写。
5. 再做事故现场 custom dump，核对待恢复文件 SHA/`pg_restore -l`，在隔离数据库完成试恢复与对象核对，并明确备份以来合法数据的处置。
6. 最后才执行 `pg_restore --clean --if-exists --no-owner --no-privileges`。恢复后运行迁移一致性、目标对象、OperationLog、`/healthz/` 和页面检查，再按清场清单逆序恢复服务。

## 未来 apply 门禁

正式写入必须完成：

- 当前 manifest/before 指纹复核；
- 最新成功代码 review 后的用户明确发布授权；本轮 review 前的概括授权不替代该门禁；
- 审核 fingerprint 对应内容完成 staging transition 并形成不可变提交；生产 bundle 归档必须来自该提交，archive SHA 与 receipt 必须匹配；
- 当前数据库 custom-format 备份、SHA-256 与 `pg_restore -l`；
- 宿主、容器、verify-only、commit、verifier 全部复算同一 bundle-index SHA；
- apply 前 compare-and-swap；
- 串行原子写入；
- 独立 verifier；
- 网页与移动端抽检；
- 可验证的回滚路径。
