# Release Report: 重赏导入马术语别名与赛事关联

## 发布信息

- **发布日期**: 2026-08-01
- **分支**: `graded-horse-aliases-and-event-links`
- **Commit**: `89928466`
- **PR**: #59
- **生产镜像**: `umanewsbot:prod` (`ccf28ce6c850`)

## 执行摘要

已完成两项生产批量修复：

1. 为 3,518 个带国别后缀的重赏导入马 `TermEntry` 添加了基础英文名别名。
2. 通过启发式匹配将 4,085 条 `HorseRaceRecord` 关联到已有 `RaceEvent`。

## 部署步骤

1. 将分支推送到 GitHub 并创建 PR #59。
2. 通过 `git archive HEAD | ssh ... tar -x` 更新 `/opt/umanewsbot` 服务器源码。
3. 执行 `docker compose -f docker-compose.prod.yml build web` 构建新镜像。
4. 重启 `web` / `worker` / `beat` 容器。
5. 运行别名命令和赛事关联命令。

## 生产执行结果

### 别名命令

```text
找到 3518 个需要添加基础名别名的马术语
[batch] 3518/3518 updated=3518 skipped=0
已更新 3518 个马术语的基础名别名（跳过 0 个）
```

### 赛事关联命令

```text
已索引 9828 个赛事
待关联记录：51698
[batch] 51698/51698 matched=4085 unmatched=47613 skipped=0
已关联 4085 条记录到赛事，未匹配 47613 条，已跳过 0 条
```

## 生产验证

```text
conflict_terms: 3612
with_base_alias: 3612
linked_records: 4085
total_records: 51698
```

- `healthz` 返回 200。
- 所有容器 (`web`, `worker`, `beat`, `db`, `redis`, `nginx`) 正常运行。

## 回滚点

- 别名：清空对应 `TermAlias` 与 `TermEntry.aliases_ja` 中的基础名。
- 赛事关联：执行 `HorseRaceRecord.objects.filter(source_refs__has_key='theracingapi_race_id').update(event=None)`。

## 已知限制

- 赛事关联率约 7.9%，主要原因是 `RaceResultSourceIdentity` 中 `the_racing_api` 仅 1 条，启发式匹配依赖日期+马场+赛事名+出马表马名，保守阈值下仍有大量记录无法确认。后续可通过扩展 `RaceResultSourceIdentity` 或放宽匹配策略提升覆盖率。
- `import_graded_horses_to_profiles` 已同步支持在创建新记录时自动尝试关联赛事。
