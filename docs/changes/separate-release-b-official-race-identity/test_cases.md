# 测试用例

## RED / GREEN

1. 相同受审 HKJC provider、URL、内容 SHA、客观字段和 runner/result，只有 catalog provenance 与
   赞助商展示名不同：旧实现摘要不同；新实现摘要相同。
2. 两条均为受审 official 证据但 URL 不同：摘要必须不同。
3. 嵌套 official marker 没有唯一 approved source/content SHA：回退完整 `source_refs`，摘要必须不同。
4. 既有“不同赛事名”“不同上游身份”“非 tombstone”“多余 canonical link”等拒绝测试继续通过。

## 验证

- `stable.test_historical_calendar_release_b` 全模块；
- Django `check` 与 migration drift；
- `git diff --check`；
- 独立只读代码审查；
- 生产部署后只读生成全新 census，并确认 12 组 identity SHA 各自收敛；
- 旧 artifact 不得复用。
