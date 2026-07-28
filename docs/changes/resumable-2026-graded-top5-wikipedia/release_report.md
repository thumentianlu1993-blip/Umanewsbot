# 2026 重赏前五名 Wikipedia 可续跑研究发布记录

## 发布范围

- 最终代码提交：`c7cb5d7da5f528384d90bcdbeeab37dabf7f01dd`
- 分支：`research/2026-graded-top5-wikipedia`
- PR：[#24](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/24)，OPEN 草稿
- 受审 fingerprint：
  `90fd66533ab5bf5a673d620868e04ac79d6e5abee5f1a067f79f585c0647f301`
- 受审 content hash：
  `6d05bbf912d9176785a258f53723fc64fa31a2d2f844b8fea4e1395e589e0f26`

本次只发布研究脚本、离线测试、GitHub Actions workflow、研究说明和 durable artifacts。
未合并 `main`，未登录或修改生产服务器，未部署、迁移或写生产数据库。

## 修复与本地验证

原始可续跑实现提交 `703c262b` 的首次完整网络执行暴露了已完成 races checkpoint 被重试、
导致上游 index SHA 漂移的问题。最终修复增加 `source_stage`，按前缀恢复 source artifacts，
并执行以下门禁：

- 已完成 stage/shard 的字节和身份验证通过后 no-op；
- 只有 safe-stop checkpoint 可从原进度继续；
- commit、tool identity、输入、上游 SHA、item hash 或同覆盖 progress/index 漂移时 fail closed；
- crash window 只接受可证明严格领先于旧安全进度的 index，完整 index 缺 progress 不得续跑。

验证结果：

- 聚焦测试：`32/32` 通过
- `py_compile`：通过
- workflow YAML：11 jobs
- `git diff --check`：通过
- 独立只读代码 review：两项 P1 返修后 `APPROVED`，无剩余 actionable finding

## 正式 GitHub Actions 运行

### Run 1：新提交起跑并安全停止

```text
workflow_dispatch
ref=research/2026-graded-top5-wikipedia
full_network=true
source_run_id=
source_attempt=
source_stage=
```

- Run：[30352874692](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/30352874692)
- Head：`c7cb5d7da5f528384d90bcdbeeab37dabf7f01dd`
- races、4 个 profiles shard、merge_profiles 成功
- Wikidata search shard 2 成功；shard 0、1、3 按预算退出 `75` 并保留 checkpoint artifact
- 该状态属于设计内 safe-stop，不推导为完整成功

### Run 2：精确 checkpoint 续跑

```text
workflow_dispatch
ref=research/2026-graded-top5-wikipedia
full_network=true
source_run_id=30352874692
source_attempt=1
source_stage=wikidata_search
```

- Run：[30358779591](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/30358779591)
- Head：`c7cb5d7da5f528384d90bcdbeeab37dabf7f01dd`
- 结束时间：`2026-07-28T13:15:33Z`
- 结论：`success`
- races、profiles 和已完成的 search shard 2 验证后 no-op
- 其余 search、entities、score、merge 和 finalize 全部成功

共使用 2 次正式 workflow run，未达到最多 6 次的上限。

## 最终 Artifact

- 名称：`30358779591-1-finalize-0`
- Artifact ID：`8689425746`
- 压缩大小：`289782` bytes
- 到期：`2026-10-26T12:24:04Z`
- 联合身份验收 artifact：`30358779591-1-races-0`（ID `8687898901`）

包含 7 个最终文件：

- `race_top5_2026.csv`
- `horse_wikipedia_mapping_2026.csv`
- `wikipedia_review_queue_2026.csv`
- `source_manifest.jsonl`
- `summary.json`
- `errors.json`
- `README.md`

联合下载 final artifact 与 races stage artifact 后验收：

- races stage artifact 的正式 run manifest：schema `2`，`base_commit=c7cb5d7d...`，
  456 个输入赛事 URL，
  `tool_version=26b4ffd32470d30a75b4625687e017cd33304458f787df362f89aced23c5c08f`
- races：456 processed / 422 success / 34 failed / 459 requests
- 最终范围：422 场、2110 条前五名记录、1490 匹唯一马
- 地区赛事：日本 74、中国香港 19、美国 190、英国 70、法国 69
- Wikipedia：14 exact、4 probable、0 ambiguous、1136 no_page、336 resolution error
- 状态总和：`14 + 4 + 0 + 1136 + 336 = 1490`
- review queue：1476 条且 horse key 唯一
- source manifest：422 条唯一 URL，全部 HTTP 200 且包含 64 位 SHA-256
- `errors.json`：1484 条；1450 `entity_not_found`，34 races `RuntimeError`
- 常见 GitHub token、AWS key、private key、API key 和 password 模式扫描无命中

本 artifact 的覆盖基线是 UmaFans 当前公开且 `data-quality-complete` 的赛事页，不是对外部
全球赛事目录的独立全量证明。34 个赛事抓取失败和 336 个 resolution error 均作为结构化证据
保留；不得把它们写成成功或猜测映射。

## 发布边界

- PR #24 保持 OPEN 草稿，未合并
- 未部署生产
- 未运行 Django migration
- 未写生产数据库或业务模型
- 未修改生产服务器

该 artifact 是研究输出，不构成生产发布授权。
