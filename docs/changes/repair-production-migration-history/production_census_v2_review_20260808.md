# Release B 生产部署与 v2 census 独立审核

## 结论

Release B schema/code 已成功部署；v2 census 自身完整且内部一致，但 reviewed overlay 门禁
`BLOCKED`。没有生成 approval，没有进入 maintenance、apply 或 verifier，也没有触发 2025
`full_network` workflow。

## 发布证据

- release commit：`4e3ffa8dd0224ae9254b17eda6c42fa11b2c730b`
- production image：`sha256:e2102ff87e465c4904b1db470ddfa3e3679dfe681bd63a405c6922954fe7afe1`
- preflight artifact SHA：`62300fbfdcc4c5ac16505067dad4fa5a68bfddcdb1e22e2ef90ceebdf51bb5f4`
- migration：`stable.0068`、`stable.0069`、`stable.0071` 均已 applied；postflight plan 为 0
- backup：`411796037` bytes、mode `0600`、TOC `1304`、SHA
  `1f6b276bc139377af93709f80cb8b64d6c026022789b2e1c6651adea582b8d1b`

## v2 artifact

生产持久路径：
`/opt/umanewsbot/backups/release-state/release-b-census-v2-20260808T132000Z`

| 文件 | bytes | SHA-256 |
|---|---:|---|
| `manifest.json` | 16329022 | `547d169535580d3948e81f57fb10b474e571d94aa8e1c3a9e1523317246abcdc` |
| `census.json` | 16328522 | `185c470f1a07a68c37c176f807776000b844d2ece54a34184d47968b9ca99037` |
| `review.template.json` | 965 | `937c4cf399c3882f3af2f0df0efe8836d4631e5a4404c01283269e605ebc30bc` |
| `summary.json` | 292 | `41a1c116cd3501d72e54214c3f25de1bbbfcccac5b4685e13bdc8a29689d2552` |

守恒结果：`14 series actions / 81 mismatch / 12 duplicate boundaries / 0 unscoped /
0 executable`。actions SHA 为
`d279b9a65f594287e7aa2cd3add8e8d64ab2fc4301485b3e480636891717fc2f`，action scope SHA 为
`a324261fc68bc166345b08196d85bc40d08361d4cd6dec8ebd448196be811665`。

独立 reviewer 复算了 177 events、261 targets、177 canonical paths、6279 immutable dependency
rows、逐行 SHA、relation count/SHA 与全部 series precondition；未发现 census 漂移。

## 确定性 blocker

12 个 duplicate pair 为：

- `series-5964`: `1838 / 2093`
- `series-5980`: `1846 / 2101`
- `series-5988`: `1848 / 2103`
- `series-5989`: `1849 / 2104`
- `series-5990`: `1850 / 2105`
- `series-5998`: `1852 / 2107`
- `series-5999`: `1853 / 2108`
- `series-6000`: `1871 / 2123`
- `series-6001`: `1872 / 2124`
- `series-6003`: `1874 / 2126`
- `series-6004`: `1875 / 2127`
- `series-6015`: `1881 / 2133`

每对均是同 series、同 local date、同 official HKJC result URL，规范化 runner/result 相同；但相邻
TJCIS season catalog 的 manifest、season label 与 provenance 不同，导致完整 `source_refs` digest
不同。现有 validator 对 `equivalent` 确定性拒绝；标成 `distinct` 又会把同一场赛事保留为两个产品
事件。因此不能通过手填 overlay 绕过。

`series-5963`（香港跨自然年届次）与 `series-6501`（英国 Finale Juvenile Hurdle）本身没有 ledger
损坏，但 overlay 必须覆盖全部 14 actions，不能越过上述 12 个 blocker 单独 apply。

## 下一门禁

新 change 应把稳定官方赛事身份与 catalog provenance 分层：至少以 official result URL、核心赛事字段、
runner/result 判断同赛，season-catalog 差异进入独立审计 ledger。完成测试、独立 review、发布后必须
重新生成 census；本次 manifest/summary/template 只作不可执行证据，禁止复用为 approval。
