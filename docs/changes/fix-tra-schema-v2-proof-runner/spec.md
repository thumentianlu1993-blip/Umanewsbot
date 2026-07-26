# The Racing API schema v2 proof runner 修复规格

## 背景

来源 registry 已升级为 schema v2，使用 `allowed_region_codes` 和 `route_contracts` 描述受审
路由；现有一次性 proof runner 虽能校验 v2 registry，执行阶段仍读取 v1
`registry["endpoints"]`，因此在 transport 前抛出 `KeyError`，无法取得任何真实来源证据。

## 目标

- schema v2 proof 必须显式指定一个受审地区，禁止隐式默认英国；
- 从 v2 route contract 确定性构建最多 3 个只读请求；
- 保留 schema v1 proof 行为；
- 缺失/非法地区、超预算、registry 漂移必须在 transport 前失败；
- artifact 只记录本次实际尝试的 path，不记录凭据、原始正文或未执行请求；
- 修复和测试阶段不得联网，真实 proof 需要独立用户授权。

## schema v2 请求合同

固定顺序：

1. 目标地区 `racecards_free(day=today, limit=500, skip=0)`；
2. 目标地区 `racecards_free(day=tomorrow, limit=500, skip=0)`；
3. `results_today_free(limit=50, skip=0)`。

`max_requests` 从序列头部取值，范围为 `1..3`，且不得超过 registry 的
`max_requests`。results API 当前没有地区过滤参数；传入 region 只用于确认调用者选择的是
registry 已审核地区，不得把 results 响应描述为该地区完整覆盖。

## 硬性门禁

- registry SHA-256、身份、terms、evidence 新鲜度、有效期和 network permission 继续校验；
- URL 只能由 `build_the_racing_api_route_url` 构建，并继续经过 transport 固定 allowlist；
- HTTPS host 固定，禁止 redirect/retry，超时 15 秒，响应上限 2 MiB，请求间隔 1.05 秒；
- secret 必须是绝对路径、当前用户所有、普通文件、权限不向 group/other 开放；
- 唯一 output 目录不可覆盖；成功和失败均只保存去敏元数据。

## 非目标

- 不修改赛事、赛果、新闻或 lifecycle 数据；
- 不启用 race-live scheduler/worker；
- 不证明 The Racing API 的地区覆盖率、实时性或 official authority；
- 不修改 provider registry、生产 secret、Celery 或数据库；
- 本轮不执行真实网络请求。

