# The Racing API Free 来源 proof 报告

## 结论

`2026-07-17` 已完成首个受控、只读、业务数据库零写入的 The Racing API Free proof。HTTP Basic 认证有效，三个 Free 端点均返回 HTTP 200；当天出马表返回 10 场，地区表返回 55 条，当天赛果在该观察时刻返回 0 场。

这次结果只证明 Free 认证、端点可达、出马表 schema 和空赛果 schema 可用。它不能证明赛果覆盖率、暂定/正式标记、完赛后更新延迟、改判能力或任何地区的正式 shadow 门槛。当前没有证据支持购买 Basic。

## 合规与执行边界

- 官方文档：`https://api.theracingapi.com/documentation`
- 官方条款：`https://www.theracingapi.com/terms-of-service`
- 自动化许可依据：用户已在本专项明确确认可直接使用来源。
- registry：`source_registry_the_racing_api_free.json`
- run02 使用的 registry SHA-256：`3e55a018f0b4b459334484494b6a4e8ab126d6706f78bc451ee89acd45dd7d37`
- 当前自动化 registry SHA-256：`1d801e95b2770c741503a75dbcba93aca407a6cd681f3471813f1e7d5586fa32`；按 2026-07-17 当前官方文档把 racecards/results 上限从 proof 时的 `10/10` 修正为 Free 默认 `500/50`，权限、host、请求数、1 RPS 和证据有效期未放宽。
- 凭据只从仓库外、当前用户所有且不可被 group/other 读取的 secret 文件注入；报告和 artifacts 不记录用户名、密码或 secret 路径。
- runner 固定 HTTPS host 和三个 Free endpoint，最多 3 个请求，相邻请求启动间隔至少 1.05 秒，单请求 timeout 15 秒，响应上限 2 MiB，禁止 redirect 和自动 retry。
- 只保存响应 SHA、状态码、耗时、大小、集合数量和字段集合；不保存 raw body、马名、人员名、评论、评级或其他实体值。
- 本轮没有导入 ORM、连接生产、写业务数据库、启动 Celery、购买订阅、部署或开启公开开关。

## RED -> GREEN

新增 `stable.test_race_live_source_proof` 共 9 项，先取得目标能力缺失产生的 `5/5` RED；随后针对 manifest 完整性、错误 schema 和原子 artifact 再取得 `1 error + 2 failures`，针对条款证据 registry 再取得 1 项 registry contract RED。代码 review 又发现一次性 proof 错误依赖长期 automation 许可；新增 `automation_allowed=false + proof_network_allowed=true` 的 proof-only RED，精确得到 `PermissionError: source automation is not permitted`，再解耦两种权限。

限定复审后又记录两个非阻塞质量建议，并主动补 RED：proof success 因不接受独立完成时钟产生 `TypeError`，未知 result status 实际被改写成 `did_not_finish`。现已在请求结束后记录 timezone-aware `finished_at`，拒绝无效/倒退时钟且不留 partial artifact；未知状态保持 `unknown` 和原始值，只有明确的非完赛代码使用对应客观状态。后续 review 要求把时钟契约完整自动化，已覆盖 naive、倒退、非 datetime、clock exception、无正式/临时目录残留，以及 clock 严格发生在最后一次 transport/sleep 之后。

GREEN 覆盖：

- secret 类型、owner 与权限门禁；
- registry 精确 schema、SHA、许可、证据时间和有效期；
- host/path/HTTPS/request budget；
- 请求间隔、timeout、大小、redirect/retry；
- endpoint schema fail closed；
- 异常脱敏；
- 临时目录写入、fsync、原子 rename 与失败清理；
- service 不访问 ORM，测试使用 fake transport。

独立复跑结果：

- proof + 全部准实时：`126/126`；
- proof + 准实时 + latest-main 相邻历史回归：`262/262`，`1 skipped`；
- 两次均使用隔离测试镜像和 `--network none`，Django system check `0 issues`。

## 真实执行证据

### run01：本地代理 DNS 被安全阻断

本地代理 DNS 将目标 host 解析到 `198.18.0.0/15` 范围。runner 在首个请求前按非公网地址 fail closed，生成 `completed=false` 的脱敏审计，没有弱化 SSRF 门禁。

- manifest：`a95cf7afa38ccfec65b7d216132e9f746ce7da0de79234d730f8f7752777ccd4`
- request ledger：`8ce67bc7edb2cadf21a623b01dcacd7ba25334b8f45f61075d6472ccee4abbd6`
- summary：`73ed13589fed42c73d0506483c913d961923db6758cbca2df4c20a1f63915ac2`

### run02：固定已审计公网地址的本地 proof

使用独立公共 DNS 核对到 The Racing API 的公网地址后，仅在一次性本地容器中把批准 host 固定到该公网地址。runner 仍执行自身 TLS hostname 校验和 allowlist；该临时映射不是生产配置，也不会写入 Compose。

| endpoint | HTTP | 耗时 | bytes | 集合数量 | response SHA-256 |
| --- | ---: | ---: | ---: | ---: | --- |
| regions | 200 | 1422 ms | 2275 | 55 | `4c1ffea9f904d865ec81e28ee6013b75870003bf6f8cedd67cacefa13e4eaa1d` |
| racecards today | 200 | 1485 ms | 48006 | 10 | `4345caeef4934a1d6b230836d53644808dea29f79c0a6cf10012bf759f6b7bf2` |
| results today | 200 | 1069 ms | 104 | 0 | `98dd9ce73b39718febab9213d740b332ec547e7f714db5257ed7623d557f9ee2` |

run02 artifacts：

- manifest：`4a1ea74d7af5c48b1ac6a4e02c3abcfe273f802e1d7fdf7c05842df3ffdbd62c`
- request ledger：`6d8ee04e3ac4dc5f2e972635d9e19fcec93d00bc8994997a3e869deb2b7eccf1`
- summary：`ab9d344571eba1cb781e63093e5f647a4c521c514890c9473fb906be49e9ddc1`

runtime artifacts 保留在本地忽略目录 `runtime/race_live_source_proof/`；durable 报告只记录脱敏指标和 SHA。

run02 由修复前 runner 生成，因此其历史 summary 的 `finished_at` 与 `started_at` 相同；不回写或伪造已生成 artifact。后续窗口使用修复后的独立完成时钟，才能把执行区间纳入延迟证据。

### run03：本地代理 DNS 再次被安全阻断

当前本机和普通 Docker 网络均把 API host 映射为非公网保留地址 `198.18.1.15`。安全 transport 在首个 `regions` 请求处以脱敏 `transport_error` 终止，`request_count=1 / completed=false`；没有业务 DB 写入。该结果只证明 DNS/SSRF 门仍 fail closed，不作为来源不可用或凭据失效结论，也不为重跑 proof 放宽公网地址检查。

## 未满足门槛与下一步

1. 至少四个真实赛日继续各运行一次相同低频 proof。
2. 必须取得已完赛样本，验证 result runner 字段、非完赛状态、同着、DQ、退赛以及暂定/正式可区分性。
3. 对每场记录上一成功轮询、首次观察、来源时间（若存在）和公开 apply 模拟时间，形成 p50/p95；当前 0 场赛果不能计算延迟。
4. 同赛事以 BHA/HKJC/JRA/NAR/France Galop/美国官方来源作只读人工或获准自动化复核；第三方网页只查漏，不作为稳定实时 API。
5. 达到四赛日、每地区 10 场候选且至少 3 场正式重点赛事之前，不生成 Basic 购买建议，不进入 shadow。
