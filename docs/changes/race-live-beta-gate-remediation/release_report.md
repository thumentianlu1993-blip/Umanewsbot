# 准实时公开 Beta Gate 修复发布报告

## 结论

`2026-07-20` 已发布授权冻结版本。coupled runner 身份、rollback bundle、四层
maintenance CAS、current revision CAS 和 legacy identity 冲突门禁已进入生产；
event `924` 保持同一暂定赛果公开。法国真实重验不再出现
`racecard_schema_invalid`，但因 `racecard_not_found` 整批 fail-closed，未初始化法国或
扩大其他地区。

## 发布身份

- Fingerprint：
  `231f8a68707f4b946daf1d355f5848cd107e13bbfa6c1ed856a0de2a31b22b4d`
- Approved content hash：
  `90380f6bd31e9eb980242772fa77f565d297f7ed01a72a9c4f412c57b239773f`
- Commit：`58f00961f2cd9750d1285f7d6229494903e975a5`
- Tree：`de529e244a3ad21a1c6d72fc50b254d37e080e20`
- Source archive SHA-256：
  `1209353f4949c1fed7cbf58756e75e54f08c6bc0a8bdec996a7d1a2c78c43b08`
- AMD64 image：
  `sha256:f9681a60f5072c39ae7cc66bad9881e719a7d24698050b4ae57858f94b310eef`

## 恢复与演练证据

- 数据库备份：
  `/opt/umanewsbot/backups/db/pre-race-live-gate-58f00961-20260719T161644Z.dump`
  - bytes：`205411102`
  - SHA-256：
    `1aa9fc306a5a5039f835f873224f5c768be95265d8bd85674bba311f320404f1`
  - `root:root 0600`，`pg_restore -l` 通过
- 环境备份：
  `.env.backup.pre-race-live-gate-58f00961-20260719T161644Z`
  - SHA-256：
    `e24208729cfba44fd71d9b2ed343dd93d3437d3f6fb80f3f459759523158b566`
- 旧 image：
  `sha256:4c40ae1946dd9ac85a368917fe3de64269e6cf848737e24253f0d0996403eda6`
  - tag：
    `umanewsbot:rollback-pre-race-live-gate-58f00961-20260719T161644Z`
- Filtered env SHA-256：
  `cda13ce08c6a6d03ffcb4812cf1e1bc1d56fa7eae2244d7cf72330869811062e`
- Rollback manifest SHA-256：
  `e6e3e1ef848009903ab2a62ea77eba2a4e3d9289a8d93759eb9c9de7dd4609f5`

maintenance dry-run/apply 成功，公共 read 临时隐藏。绑定同一 candidate image、filtered
env 和 manifest 的 `validate -> restore-policies-coarse -> validate ->
restore-policy-event` 全部成功，最终 validator 通过。event `924` 恢复后：

- `visible=true / public_read_allowed`
- current/provisional revision：`2 / 2`
- legacy results：`7`
- tracking disabled、next poll null、token 为空
- lock version：`39`

## 上线验收

- `stable.0048` 已应用，无 migration drift。
- web、worker、race-live worker、Beat 均运行发布 image/revision。
- Django check、collectstatic、HTTP 本机与公网 healthz、首页、赛事日历和 event `924`
  详情通过。
- scheduler/monitor=false、enabled regions `[]`、active claim `0`、race-live queue
  `0`。
- 近期相关 app 日志无 traceback、critical、exception 或 integrity error。

## 法国重验

成功 run：

`/opt/umanewsbot/runtime/race_live_racecards/production-racecard-france-733-735-gate-fix-20260719T163001Z`

- 请求：today/tomorrow 各一次，共 `2`
- requested events：`3`
- matched events：`1`
- blocker：`racecard_not_found`
- `racecard_schema_invalid`：未出现
- report SHA-256：
  `f81cf27666f8e026db4dd30d107f500205366d96ef3c45bf373879e68d22d517`
- requests SHA-256：
  `8c0a80775253b32ff6e3caa1d1e31244786c531116d5dad478d303977e197246`

整批没有 manifest，未运行 initializer。events `733–735` 没有 tracking、projection
control 或 enabled allowlist；法国和其他新地区继续关闭。当前公开面仍只有 event `924`
的暂定赛果。
