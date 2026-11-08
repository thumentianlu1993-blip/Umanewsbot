# 日本官方页面回归样本

2026-11-08 有界读取的公开页面，用于离线测试。固定日期只是样本，运行代码不限定赛事ID或年份。

JRA 动态页面使用官网链接中的 CNAME 经 doAction 提交后取得DOM；静态年度/赛果与NAR页面来自公开HTML。NAR报名正例使用测试中明确标注的官网模板结构合成，不能作为已发布真实报名的证据。

一哩冠军赛页面的20匹特别登录与另列1匹地方／外国马分别保留；不能将头部20直接作为页面全部名单数。

| 文件 | SHA256 |
|---|---|
| jra-annual.html | `6cae4d19ca8fafcabb2d278825762aad34df92ecfe04da1a9c66aa20cc3e0f40` |
| jra-card-index.html | `6d2ba275931f30d2b73e22062fb14a10da32709f4c8fd22f188ce4b74e6d467d` |
| jra-meeting-index.html | `8470e2bf0fddd7078697abd51f5928e13620f03c272567c6b8d30ee9665cdb62` |
| jra-mile-registration.html | `fd9085ff3608dc6b94c34b0727e637ca758483927d9825247d9575e2ff5735d1` |
| jra-registration-index.html | `a91c072d6c183f454676393a380d621f26a3c8a8a3f8d6e7e53dbd844bb2db02` |
| jra-registration.html | `e4da838602dabe560ba0b3fd1702fd290132c5d581c4caf6f254c3c4e8954aae` |
| jra-result.html | `4c78e43c33b65fc6a579731763a88f2a6ced7b6d11e360f5e462ede337555864` |
| nar-cancelled.html | `795ca75e9c9058473e343096efd0e33fb611ed348d8293008c56cd25a8709832` |
| nar-card.html | `ddc2f588a84048cf3454f7c0c3cd7a7e2d67cec71420eca1fad04229514bbf9b` |
| nar-introduction.html | `24ed3ae096dee64e419e013c860caf0eb05786f0663319d3833e246497441590` |
| nar-navigation.html | `2c9a0acf1344f6becbcae3a8f09f002339e4cbd86b47992b42cc5ea727ff2320` |
| nar-racelist.html | `24c51081c8ba0611bff2a591d18ae27a46a2533f32431ab2927a699d89d127b5` |
| nar-result.html | `b74a068325efaa94aab459e325bc75b72f99184da457b6d77d4203629bce55d9` |
| nar-topic.html | `27461cbca3da8dde7f5914366402eb4ee212f4e079e7e4d403d07350f0284d1b` |
| nar-upcoming.html | `5de68198acaa1445f67bcaff2cbfd6f0bf182aa30490488f50b045efda9594d2` |

主要入口：JRA `https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dli00/F3`、`https://www.jra.go.jp/JRADB/accessT.html?CNAME=pw03trl00/29`；年度 `https://www.jra.go.jp/datafile/seiseki/replay/2026/jyusyo.html`；NAR `https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/` 与 `https://www.keiba.go.jp/dirtgraderace/2026/`。具体详情URL由测试参数或页面真实链接给出。

带广ばんえい补充：2026-11-08 沿官方月历实际导航取得 2026-11-01 第1竞走；用于验证减量骑手符号与15列赛果格式。

- `nar-banei-result.html`：https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/RaceMarkTable?k_raceDate=2026%2F11%2F01&k_raceNo=1&k_babaCode=3；SHA256 `57fd3051aaccbc9a4fefe74f08181a4b5d047879db5954ac85b5d69e3382eeb6`。
- `nar-banei-card.html`：https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/DebaTable?k_raceDate=2026%2F11%2F01&k_raceNo=1&k_babaCode=3；SHA256 `57c1cd26543e8f456013021eab9ed2c72146c77705901265cd1bbd6d87df01c1`。

仓库HTML回放fixture仅规范化ASCII行尾空白和缩进制表符，以满足仓库静态检查；上表为规范化后的fixture SHA。原始下载字节与原始SHA保存在任务runtime证据包，生产回填仍核验原始页面，不使用规范化fixture替代原始证据。
