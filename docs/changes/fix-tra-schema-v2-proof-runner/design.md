# The Racing API schema v2 proof runner 修复设计

## 当前故障

`_read_registry_contract()` 已接受 schema v2，但
`run_the_racing_api_free_proof()` 随后直接读取 `registry["endpoints"]`。v2 registry 不包含
该字段，因此 transport、artifact 和延迟统计均不会发生。

## 数据流

```text
管理命令 --region
  -> secret 文件安全读取
  -> registry SHA/合同/预算校验
  -> schema 分支
       v1: 保留 registry endpoints
       v2: route_specs + 显式 region -> route contract builder
  -> 固定 transport allowlist
  -> 去敏 request metadata
  -> 原子写入 manifest / requests / summary
```

## schema 分支

### v1

保留既有 endpoint 顺序、URL 和 manifest 语义，避免破坏历史 proof 回归。

### v2

- `region` 由命令显式传入；
- 按 today racecard、tomorrow racecard、results today 的固定序列构建；
- builder 校验 region、route、day、limit 和 skip；
- `max_requests` 只构建并执行序列前 N 条；
- manifest 的 `endpoints` 只写实际进入 transport 尝试的 path。

## 失败与证据

- 缺失/非法 region、registry budget 超限：transport 调用数必须为 0；
- HTTP、redirect、content type、JSON/schema 或 transport 失败：停止后续请求，不重试；
- transport 异常统一去敏，禁止把 username/password 写入 artifact；
- completion clock、临时目录、fsync 和 atomic rename 继续沿用既有实现；
- output 已存在时 fail closed，禁止覆盖旧证据。

## 安全说明

测试 transport 全部为 fake；所有声称“非法 URL”的测试必须 mock resolver，并断言 resolver
未被调用，防止 allowlist 演进后测试意外进入 DNS/HTTPS。真实网络 proof 只允许在最新 review
fingerprint 和独立用户授权同时成立时执行。

