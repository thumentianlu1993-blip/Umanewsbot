# 运行与回滚

## 小样本验收

使用独立输出目录，先执行：

```bash
python runtime/research/collect_graded_race_participants.py \
  --stage discover --year 2025 --max-races 10 \
  --output-dir runtime/research/output/graded-race-participants-smoke/2025
```

随后依次运行 `races -> merge_races -> profiles -> merge_profiles -> finalize`。网络阶段应使用较短 time budget，并至少验证一次安全停止后 `--resume`。

## 完整年度运行

每个年份使用独立目录：

```text
runtime/research/output/graded-race-participants/<YEAR>/
```

赛事页与马匹页阶段可按稳定哈希分片。单个 job 应预留 artifact 上传时间，不得把 time budget 设置到 runner 的硬超时边缘。

## 质量门禁

- `summary.json -> quality.english_name_contract_passed` 必须为 true，才满足“非日本/香港英文名必备”的完整数据契约。
- 缺失英文名不会被伪造；对应行保留在 `name_review_queue_<year>.csv`。
- races/profile retryable error 不得静默当作成功。

## 回滚

本任务只新增研究脚本、测试和文档。回滚方式为删除新增文件或关闭草稿 PR；不涉及迁移、容器、服务重启或生产数据回滚。
