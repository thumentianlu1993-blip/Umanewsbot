# 2025 分级赛参赛马补全与生产导入 Rollout

## 当前检查点

- worktree：`/Users/mentianlu/.codex/worktrees/minimal-release-b-identity/umanews`
- branch：`codex/complete-2025-graded-horse-data`
- baseline：`origin/main@8256b7047d2319e9842b4cf7765382ce4a7367b7`
- 主工作区属于其他线程且有大量未提交改动，本 change 不触碰。

## 冻结 artifact

- run：`31269803408`
- final artifact：`31269803408-1-finalize-0` / ID `9025592068`
- digest：`sha256:ef8bbc107379413aa2e2ca8ed0dc144759fb7b3578b4d15746b421b923477535`
- outcome：`partial`
- races/participants/horses：`1063/9292/4965`
- AU/DE/Middle East：`classification_incomplete`
- required English missing：`3905`
- profile resolved/not found/ambiguous/unresolved：`920/3998/32/15`

## 生产只读基线

- 2025 G1/G2/G3：`1065` events、`9292` results；地区为 France `191`、Hong Kong `19`、Japan
  `139`、UK `305`、US `411`。研究 artifact 少两场的差异必须在新 census 中解释。
- HorseProfile：`53526`；completeness 为 empty `45350`、profile_only `6054`、
  complete_pedigree_2gen `3`、complete_profile_full `965`。
- 状态：draft `43496`、ready `24`、published `8852`。
- 2025 赛果 `source_refs` 已保存 Japan horse ID、UK Sporting Life horse slug/race ID、HK horse URL
  等 provider evidence；身份映射应使用这些内部证据，不依赖公开 horse search。

## 已完成实现

- 证明赛果行纯拉丁马名被旧 finalize 忽略，取得 RED。
- `build_horse_name_record()` 现按 `original_name` 后 `horse_display_name` 接受纯拉丁英文证据；混合
  Han/Kana 不放行。
- tool policy 升为 `year-region-status-name-v2`，禁止旧 checkpoint 静默复用。
- collector/hurdle/integrity 聚焦测试 `102/102` 通过。
- 新增严格七文件离线 gap census；固定 fixture `4/4` 通过，当前 artifact 的逐文件 SHA 与
  `1063 / 9292 / 4965 / 15854` 交叉计数一致。
- 生产只读差集确认英国多出的两场为 `Towton Novices Chase` 与
  `Silviniaco Conti Chase`：均为 2025-01-11 G2 障碍赛、`draft + incomplete`、赛果 `0`。
- 官方源探测确认德国、巴林为服务端表；ERA/JCSA 页面声明的同域 AJAX/API 返回完整赛果。
  已新增六地区 URL policy、请求预算、严格离线 result parser 与 manifest-bound checkpoint runner。
- TJCIS 2025 整本 327 页在逐页释放 parser cache 后完成解析：AU `312`、DE `42`、Middle East `47`
  （UAE `33`、Bahrain `2`、Saudi `12`）；France/US 两项 declared-count 冲突保持显式阻断/审批路径。
- P0 candidate artifact 已支持八地区、`year=2025`、`actual_starts_only=true`，并输出四类生产映射
  disposition。
- 首轮独立审查的五项 P1 已修复：官方结果保留并列与非完赛实际起跑状态；确定性 checkpoint 不可
  resume 重抓；cache path 必须精确绑定 race/output root；TJCIS 同页多国家按页首/页脚布局切分；
  census 赛事身份保留规范化完整 URL/query。
- 修复后组合回归 `110/110`，研究侧 `112/112`，workflow contract `16/16`；2025 TJCIS 官方整本
  回放仍为总计 `1491`、AU `312`、DE `42`、Middle East `47`。同一独立 reviewer 对最终 symlink
  反例及全部旧 finding 复核后给出 `APPROVED`。

## 门禁

- 当前仍为本地实现：未 commit/push/PR，未部署，未扩大外部网络，未写生产。
- 下一次人工停点是完整实现和独立 review 后的 G2；若在此之前需要执行外部全量网络，按 G3 提交
  精确 provider/host/year/request budget 包。
