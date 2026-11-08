# 日本官方页面回归样本

2026-11-08 有界读取的公开页面，用于离线测试。固定日期只是样本，运行代码不限定赛事ID或年份。

JRA 动态页面使用官网链接中的 CNAME 经 doAction 提交后取得DOM；静态年度/赛果与NAR页面来自公开HTML。NAR报名正例使用测试中明确标注的官网模板结构合成，不能作为已发布真实报名的证据。

一哩冠军赛页面的20匹特别登录与另列1匹地方／外国马分别保留；不能将头部20直接作为页面全部名单数。

| 文件 | SHA256 |
|---|---|
| jra-annual.html | `6218b0c66fc4cffe0e6c022a3e95359c81c62b658c7d9072ba1ea725648492d1` |
| jra-card-index.html | `79710074dc8bc42d3ca987882f2a193da0bde3c662b758e257a5dd5402e12ea8` |
| jra-meeting-index.html | `3a40ec9e5ac1d321c300938212333eff14b9b131b892e1671efd5a556a222b7a` |
| jra-mile-registration.html | `9c374a7e30d2e51903e1625e8c10316ab2304e14cae2171645fddf8060b57573` |
| jra-registration-index.html | `efaa0328d0a63fca7d2deeda1ad870e2b08dd89d1a8e84fbca305b4ad3f4d208` |
| jra-registration.html | `c91f36aed3eb56945a242cfc69d4820f614640a2228edf4b073df6108cd54cc3` |
| jra-result.html | `95cfb29e1c025bd203655a4fdda3598d0d0e1a00db508a47ae72ca5fefc1e803` |
| nar-cancelled.html | `5c7e99fbf6ae7db7d8f7efa9985b6b32a7a47094a38147104dde403dcc22eed0` |
| nar-card.html | `bce779ced2cab4f01a51c8c01bcce4e35dd778a49284e984cffda94395a909fa` |
| nar-introduction.html | `24ed3ae096dee64e419e013c860caf0eb05786f0663319d3833e246497441590` |
| nar-navigation.html | `0ba8f3e93666928b0466276b7441cbcc58277e803f8490667e6c33ba347d0d59` |
| nar-racelist.html | `e549d4130206cfcc6fde3cf2fccc30a58a1e02713e09058f0290e4b6216af0d0` |
| nar-result.html | `5d42aa0ce41bdfbfc2fb05573dc99a635b0c55923c08d344ca8ffee1f4106de0` |
| nar-topic.html | `27461cbca3da8dde7f5914366402eb4ee212f4e079e7e4d403d07350f0284d1b` |
| nar-upcoming.html | `5de68198acaa1445f67bcaff2cbfd6f0bf182aa30490488f50b045efda9594d2` |

主要入口：JRA `https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dli00/F3`、`https://www.jra.go.jp/JRADB/accessT.html?CNAME=pw03trl00/29`；年度 `https://www.jra.go.jp/datafile/seiseki/replay/2026/jyusyo.html`；NAR `https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/` 与 `https://www.keiba.go.jp/dirtgraderace/2026/`。具体详情URL由测试参数或页面真实链接给出。

带广ばんえい补充：2026-11-08 沿官方月历实际导航取得 2026-11-01 第1竞走；用于验证减量骑手符号与15列赛果格式。

- `nar-banei-result.html`：https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/RaceMarkTable?k_raceDate=2026%2F11%2F01&k_raceNo=1&k_babaCode=3；SHA256 `59fdff3ab18dfc59a5216cd2505d9006733b7114e627d5d0c832ba7452028ac7`。
- `nar-banei-card.html`：https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/DebaTable?k_raceDate=2026%2F11%2F01&k_raceNo=1&k_babaCode=3；SHA256 `d03556e1f1c2b9e55b1bac356d320c27dc27750d48040cd63e7cd7737069105f`。
