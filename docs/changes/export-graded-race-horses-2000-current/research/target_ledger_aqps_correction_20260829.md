# 四地区目标总账 AQPS 语义修正

## 结论

TJCIS 法国页面中的显式 `AQ` 行代表 AQPS 平地草地赛事，不得继承页面相邻的 jumps 上下文；页面末尾
独立 AQPS 信息段也不得计入法国主表声明总数。修正只改变 88 条 AQPS 行的 discipline/surface/scope
语义，没有增加或删除事实行；总账仍为 12,047 行、26 个声明冲突、9 个本次范围 blocker，状态仍是
PREPARED。

## 当前产物

- target root：`/Users/mentianlu/.codex/umanews-target-aqps-evidenced-20260829.dn99Jz`
- ledger SHA-256：
  `88313a59972196ddd6a275c22a09f7c9c7b8ae9b23efc5f67045a34076961a49`
- manifest SHA-256：
  `b507d21d0f7bc5eef9785cb9a230200bbdbdb81a63686f5f63476a26add1ec5d`
- blocker canonical payload SHA-256：`dedf39df…d9d1`，未变化。

独立 correction audit：

- root：`/Users/mentianlu/.codex/umanews-target-aqps-evidenced-audit-20260829.MeRRx8`
- manifest SHA-256：
  `0d233501231ac0120ec7499d26fe820691a770affba4d909b9db9ecdee956630`
- 变化：88；事实新增 0、删除 0。

AQPS 修正后的 2026 官方赛历 audit：

- root：`/Users/mentianlu/.codex/umanews-official-calendar-aqpsfix-2026-20260829.5y4PTf`
- manifest SHA-256：
  `2e78d352b1da3bf240d5b48e7d122dd7a6ca6b31e9f75bbf60f8df8aec81071f`
- 守恒：375 source、373 candidates、124 target issues。
- 法国 18 个 issues：15 个 AQPS flat、2 个 jumps（Pau/Nice）、1 个 flat（Penelope）。

此前 series-key 修复产物和绑定其 SHA 的 official-calendar audit 已被本修正取代，只能作为历史差分证据，
不得继续生成 runnable seed 或授权 TRA 请求。
