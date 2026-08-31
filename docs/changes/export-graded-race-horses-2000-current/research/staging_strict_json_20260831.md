# materialization 与 External staging 严格 JSON

日期：2026-08-31

## 风险

targeted batch、run、materialization、normalized export 与 response wrapper 都使用 SHA/size/marker 内容寻址，但部分
loader 仍采用 Python 默认 `json.loads`。默认 decoder 接受重复 key 与 `NaN/Infinity`；操作者若同步重算 member、
manifest 与 marker SHA，可以得到字节自洽但在不同 parser 下含义不同的 artifact。

## 修复

- `materialize_racing_api_targeted_batch.py` 的 `_read_json` 统一拒绝 duplicate key 与 non-finite constant，覆盖 batch
  manifest、content pool manifest、seed run manifest、compact normalized 与 seed source；
- `racing_api_horse_staging.py` 的共享 `_load_strict_json` 覆盖 run manifest、response wrapper、normalized export 与
  materialization manifest；
- 既有 SHA、size、路径 containment、symlink、exact member set、COMPLETE marker 和 transaction rollback 门禁保持不变；
- 不提供 legacy ambiguous JSON fallback，需从冻结 provider response/cache 重建 canonical artifact。

## 验证

- batch manifest duplicate key/`NaN` 且重算 COMPLETE 后，materializer 在创建 output 前拒绝；
- run/materialization manifest duplicate key、normalized `NaN` 且重算全部 SHA 后，staging 在 dry-run/DB 前拒绝；
- materializer `5/5`、staging `10/10`；
- 完整 research `574/574`、change test IDs `333/333` 唯一；
- approval 相关 service 链 `87/87`、Django check、migration drift、`py_compile`、`git diff --check` 通过。

本轮无生产网络、数据库写、共享锁、Beat、registry 或 race-live 操作。
