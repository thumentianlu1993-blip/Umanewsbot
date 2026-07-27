# 2026 重赏前五名 Wikipedia 可续跑研究发布记录

## 发布范围

- 提交：`703c262bb54b68c15643727b2ca9ea9f2fbd2ef8`
- 分支：`research/2026-graded-top5-wikipedia`
- PR：[#24](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/24)，OPEN 草稿
- 冻结内容 SHA-256：
  `275957760e0ba787c3d3308cfb1a4573db20ba1ddec6c8c031b3ccb965f44e75`

本次只发布研究脚本、离线测试、GitHub Actions workflow、研究说明和 durable artifacts。
未合并 `main`，未部署生产，未写 Django model 或生产数据库。

## 本地验证

- 聚焦测试：`27/27` 通过
- `py_compile`：通过
- workflow YAML：11 jobs
- `git diff --check`：通过
- 独立代码 review：最终 `VERDICT: APPROVED`

## GitHub Actions

PR synchronize 在观察窗口内没有自动生成 run，因此按用户授权手动触发：

```text
workflow_dispatch
ref=research/2026-graded-top5-wikipedia
full_network=false
```

- Run：[30240664640](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/30240664640)
- Head：`703c262bb54b68c15643727b2ca9ea9f2fbd2ef8`
- Tests job：成功，11 秒
- 公网 jobs：races、profiles、merge_profiles、wikidata_search、merge_search、
  wikidata_entities、merge_entities、score_horses、merge_scores、finalize 全部 skipped
- 唯一提示：GitHub 将 Node 20 actions 强制运行于 Node 24 的弃用 warning；不影响本次结果

## Artifact 验收

- 名称：`30240664640-1-synthetic-checkpoint-0`
- Artifact ID：`8643122587`
- 大小：`21697` bytes
- 到期：`2026-08-10T05:45:48Z`

下载后核验：

- 包含 `run_manifest.json`、`safe_stop.json`、stage items/index、races progress
- 包含 7 个最终文件：
  - `race_top5_2026.csv`
  - `horse_wikipedia_mapping_2026.csv`
  - `wikipedia_review_queue_2026.csv`
  - `source_manifest.jsonl`
  - `summary.json`
  - `errors.json`
  - `README.md`
- `safe_stop_evidence_present=true`
- 恢复结果与不中断基线 item SHA 相同
- `byte_equivalent=true`
- synthetic summary：2 场、2 行、2 匹马、1 个 resolution error、5 次请求

## 未发生事项与下一门禁

- 未执行 `full_network=true`
- 未采集完整 456 场/1540 匹真实范围
- 未合并 PR
- 未登录或修改生产服务器
- 未部署、迁移或写生产数据库

完整公网研究运行必须取得新的明确授权，不能从本次离线 artifact PASS 推导。
