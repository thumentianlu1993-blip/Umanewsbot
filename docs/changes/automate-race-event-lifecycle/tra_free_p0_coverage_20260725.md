# The Racing API Free 对 P0 赛事覆盖审计（2026-07-25）

## 1. 结论

截至 `2026-07-25T09:12:34Z`：

- 生产库 2026 年共有 `231` 场 `priority=P0` 赛事；`2026-07-25` 起仍有 `113` 场。
- Free racecard 只允许查询 `today/tomorrow`。当前两日窗口内共有 `3` 场 P0，实际命中
  `1/3 = 33.3%`。
- 命中的是英国英皇锦标：API 返回 Ascot、当地 `15:35 +01:00`、9 匹出赛马、骑师和闸位。
- 两场美国 P0 均未命中；`region_codes=usa` 请求 HTTP 200 但 racecard 为 0。
- 地区代码已用 Free `/v1/courses/regions` 核对，`usa/gb/fr/hk/jpn` 均存在；美国空结果不是
  本次过滤代码拼错。
- 以“现在即可读取全部剩余 2026 P0 racecard”为口径只有 `1/113 = 0.9%`；这主要反映 Free
  端点只开放 today/tomorrow，不能解释为未来赛事到临场时仍不覆盖。
- Free 无法支持 P0 的 T-21/T-14/T-7 赛前准备窗口；它最多适合作为 T-1/T0 的补充来源。

## 2. 生产分母

| 地区 | 2026 P0 总数 | 2026-07-25 起剩余 | 剩余等级 |
|---|---:|---:|---|
| 美国 | 87 | 50 | G1 50 |
| 英国 | 60 | 19 | G1 19 |
| 法国 | 38 | 24 | G1 24 |
| 日本 | 37 | 19 | G1 13、JPN1 6 |
| 中国香港 | 9 | 1 | G1 1 |
| 合计 | 231 | 113 | — |

当前 today/tomorrow 分母：

| 赛事 | 地区 | Free 结果 |
|---|---|---|
| BING CROSBY S. | 美国 | 未命中 |
| COACHING CLUB AMERICAN OAKS INVITATIONAL S. | 美国 | 未命中 |
| KING GEORGE VI AND QUEEN ELIZABETH STAKES | 英国 | 命中 |

## 3. 受控请求证据

- 只读使用生产主机既有 `0600` secret；未输出凭据或原始响应。
- registry SHA-256：
  `7aca49ff1df7573ebfe6a9e403eefca5c9e64d8ee18d8d3be383d67803db550a`。
- 固定 host：`api.theracingapi.com`；TLS、DNS 公网地址、无 redirect、15 秒 timeout、
  2 MiB 响应上限、至少 1.05 秒间隔。
- 有效请求：
  - `usa today`：HTTP 200，125 bytes，0 racecards；
  - `gb today`：HTTP 200，238169 bytes，43 racecards；
  - regions：HTTP 200，55 个 region。
- 本地先因代理 DNS 映射为保留地址而 fail closed；该次在网络访问前停止，不计 API 请求。
- 生产 `race_live_worker` 当时为 exited；本次使用无数据库连接、只读文件系统、限制内存/PID 的
  一次性容器，不启动 worker、不改 Beat、不写业务数据库。

## 4. 结构性覆盖判断

供应商公开资料称 Core 完整覆盖英国、爱尔兰、香港，并覆盖全球 Group 级赛事和部分 handicap；
North America 完整覆盖需要 add-on。生产剩余 P0 中英国＋香港共有 `20/113 = 17.7%`，这是
相对稳定的地区候选占比，不是本次逐场实测覆盖率。

法国 24、日本 19、美国 50 合计 `93/113 = 82.3%`。这些赛事是否落入 Free 的全球 Group
选择、JPN1 是否被纳入、以及美国 racecard 是否需要 add-on，均不能从公开地区总量推导为逐场
覆盖。今天两场美国 G1 的实际 0/2 说明不能把“全球 Group 结果库”当成 Free 当日美国 racecard
可用性。

## 5. 字段覆盖

已命中的英国样本证明 Free 当前可提供：

- 赛事身份候选、赛场、当地 offset 时间；
- field size、runner 列表；
- jockey；
- draw/barrier；
- race status（样本为 `declared`）。

本轮没有证明：

- 退赛/临时退赛的稳定事件语义；
- 延期后的旧时间撤销；
- provisional 与 official 的显式 marker；
- 法国、日本、中国香港字段完整率；
- 赛后结果延迟，因为三场样本在审计时尚未完成。

## 6. 对生命周期方案的影响

1. 阶段 A 不依赖 TRA，保持不变。
2. Free 不能承担阶段 B 的提前 21/14/7 天刷新。
3. Free 可保留为英国/香港临场 racecard 与部分全球重点赛的 supplemental source。
4. 美国若要稳定覆盖，优先比较 North America add-on 的一个月 proof 与 Equibase/企业报价。
5. 要得到全年逐场覆盖率，需要在每个地区至少选择 10 场 P0，并在 T-1/T0/赛后分别采样；
   或购买允许未来日期查询的 plan 后一次性做候选匹配。不得用供应商地区总结果数冒充逐场覆盖率。
