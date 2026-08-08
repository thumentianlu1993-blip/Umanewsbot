# Release B 官方结果身份修复生产发布证据

## 结论

PR `#77` 已合并并安全部署；新 v2 census 证明 12 对 HKJC duplicate boundary 的官方身份 SHA
全部收敛。生产数据库尚未执行 Release B 数据 apply，2025 `full_network` 尚未启动。

## 发布

- merge commit：`55d41b5f84f072e11862fa14213cecc027708719`
- production image：`sha256:c9f0a89fbb3a28f135a0dd32546b609164b89d845c6181483eb553ddbd249ef4`
- preflight canonical artifact SHA：
  `09262ebbdb2ffad4ca46112b19d972cf725754d4d6fae1156c946b5b5828f602`
- backup SHA：`629a5495010d564da6c8233e887becebdb08d7d31d73ea0503bb48cdd381de70`
- postflight：Django check 通过，migration plan 为 0，HTTP healthz 与 Celery ping 通过，全部历史
  writer/network flags 为 false，claimed review 为 0，部署锁不存在。

## 新 v2 census

持久目录：
`/opt/umanewsbot/backups/release-state/release-b-census-official-identity-20260808T164124Z`

| 文件 | bytes | SHA-256 |
|---|---:|---|
| `manifest.json` | 16329022 | `85978b9bed6ff75742d1eed4cb0ad1e4f6105c9ebc82146e3c05efdff1682a13` |
| `census.json` | 16328522 | `4902f3b89f43d6d82cc809ccd755fba8a7b1329c229348273ec05490677a4472` |
| `review.template.json` | 965 | `937c4cf399c3882f3af2f0df0efe8836d4631e5a4404c01283269e605ebc30bc` |
| `summary.json` | 292 | `41a1c116cd3501d72e54214c3f25de1bbbfcccac5b4685e13bdc8a29689d2552` |

守恒为 `14 series actions / 81 mismatch / 12 duplicate boundaries / 0 unscoped / 0 executable`，
action scope SHA 仍为
`a324261fc68bc166345b08196d85bc40d08361d4cd6dec8ebd448196be811665`。

## 待确认的完整数据决策包

12 对 duplicate 均已具有相同官方身份 SHA。推荐 survivor/duplicate 如下：

| series | survivor | duplicate |
|---|---:|---:|
| 5964 | 2093 | 1838 |
| 5980 | 2101 | 1846 |
| 5988 | 2103 | 1848 |
| 5989 | 2104 | 1849 |
| 5990 | 2105 | 1850 |
| 5998 | 2107 | 1852 |
| 5999 | 2108 | 1853 |
| 6000 | 2123 | 1871 |
| 6001 | 2124 | 1872 |
| 6003 | 2126 | 1874 |
| 6004 | 2127 | 1875 |
| 6015 | 2133 | 1881 |

每对均保留自然年/届次正确的原记录，duplicate 进入 detached draft tombstone，后续错位链按 ledger
修正 public year、edition、target 与 path。另保留 `series-5963` 的 edition 2020 / natural year 2019，
以及 `series-6501` 的 edition 2015 / natural year 2016。该完整包须经用户 G3 确认后才能生成 reviewed
manifest、approval 并写入生产。
