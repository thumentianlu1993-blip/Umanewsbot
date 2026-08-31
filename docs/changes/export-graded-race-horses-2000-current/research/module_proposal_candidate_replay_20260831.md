# module proposal candidate replay 完整性

日期：2026-08-31

## 问题

module proposal 已绑定 `review-rows.jsonl`、manifest 与 marker SHA，但旧 loader 只验证这些 artifact 彼此自洽和行数。
若 review row 的推荐摘要被修改后连同所有 SHA 一起重算，publisher 在真正批准前不会重新证明该摘要来自 frozen
candidate。后续 research build 虽然仍会读 candidate，却无法补偿 reviewer 当时看到的输入已经漂移。

## 修复

`racing_api_horse_module_review.py` 现在：

1. prepare 与 load 共用 `_module_proposal_manifest`，避免生成规则分叉；
2. load 对每行按 `candidate_path + candidate_sha256` 重新读取候选；
3. 重跑 profile、pedigree、career、target scope、source URL/response SHA 与完整性规则；
4. 重新生成并排序 review rows；
5. 要求 stored rows 与整份 deterministic manifest 精确相等后才允许 publish approval。

module loader 对全部 JSON/JSONL 使用 duplicate-key 与 non-finite constant rejection；identity proposal、reviewer
decisions 与 approval artifact 也补齐相同的 non-finite rejection，避免 `NaN/Infinity` 或重复 key 让同一份 SHA 字节
产生多种解释。

global review aggregate 使用同一 module proposal loader，因此最终聚合也会再次执行 replay。没有提供忽略 candidate
漂移或仅信任已重算 SHA 的兼容旁路。

## 验证

- 新测试把 `recommended_decision.confidence` 改为 100，并同步重算 rows、manifest 与 marker；publish 在 approval
  output 创建前以 candidate snapshot drift 拒绝；
- duplicate-key 与 `NaN` manifest 即使重算 SHA/marker 也在 publish 前拒绝；
- module 专项 `14/14`；
- identity 专项 `25/25`；
- candidate/identity/module/global 相关 service 链 `87/87`；
- 完整 research `574/574`，change test IDs `333/333` 唯一；
- Django check、migration drift、`py_compile` 与 `git diff --check` 通过。

全部验证均为本地 synthetic/filesystem/SQLite test evidence，无生产网络、数据库、共享锁、Beat、registry 或
race-live 操作。
