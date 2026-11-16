# 东京城市杯字段展示与 Turf Monster 收口

## 已核实范围

用户要求核实 Turf Monster 日期和举办状态，并修复东京城市杯页面“无分级／待核实”。当前生产为 PR #325 候选 `3df2065b`。两场都保留原 ID 和公开地址；本次不创建赛事、出马或赛果。

- Turf Monster：TOBA 2026 官方表明确 `not run`；2026-09-18 署名 Parx Racing 的公告说明计划 2027 回归。493 的来源已保存 `us_not_run`，公开页 HTTP 200、显示“本年度未举办”，日期为空是正确状态。上一轮覆盖盘点只看通用 `scheduled` 字段，将它误报为日期待核。本次同步旧年度目标 74817：`not_held/ready`、event=null、名单和赛果 not_applicable；493 本身保持当前数据和公开说明。
- Tokyo City Cup 2025：TOBA 2025-06-23 公告（TDN 翌日报道）因距离由12化朗改为8化朗，明确为 Non-Listed Black-Type。不是 G3，也不是 Listed。显示精确改为“黑体赛（非表列）”，不进入 G1/G2/G3/L 筛选。
- 东京 20884 页面当前状态实际为“已完赛”；顶部“待核实”属于距离，`1m` 缺少 mile 单位说明。补明确来源单位后显示“1英里（约1609米）”。八条名单/赛果的 `8-6` 等负重补 stone_lb、赔率补 fractional 单位说明；原字段内容、马名、名次、冠军和完赛状态不变。赔率属于 Sporting Life 分数报价，不冒充美国官方派彩或人气。

## 来源

- [TOBA 2026 官方年度表](https://toba.org/graded-stakes/2026-races/)
- [Parx Racing 公告转载](https://paulickreport.com/news/the-biz/parx-turf-course-will-be-installed-monday)
- [TOBA 分级公告报道](https://www.thoroughbreddailynews.com/tokyo-city-cup-to-run-as-non-listed-black-type-race-in-2025/)
- [Sporting Life 四匹完整赛果](https://www.sportinglife.com/racing/results/2025-10-25/santa-anita/886826/race-2-tokyo-city-cup-stakes)
- [Santa Anita Press Box 赛后稿](https://pastthewire.com/privman-finds-second-wind-in-tokyo-city-cup/)

原件、实时只读快照及精确修复清单保存在专用运行目录 `/Users/mentianlu/.codex/runtime/tokyo-turf-display-20261116/`。TOBA 与 Parx 公告的直接HTTP下载403不记作原件获取；浏览查询已取得正文，来源事实摘录和原有已校验TOBA缓存分别保留。

## 实现与验证

只新增明确 Non-Listed Black-Type 标签和带显式 stone_lb 单位的换算。`8-6` 无单位仍待核，磅余数>=14或尾随垃圾拒绝；不扩大自动单位猜测。距离和赔率使用已有解析器与结构化来源单位。

先取得三项真实 RED，再验证解析、SQL等级筛选和公开页面。对生产形状快照进行干跑、应用、重放、漂移/人工锁拒绝和精确恢复演练；独立只读审核及固定范围CI后生成发布包。

## 待交付

尚未生产写入。人工交付遵守根 AGENTS.md G2/G3，上一包授权不覆盖本次新发布包。发布包须绑定新提交、镜像、数据清单及来源 SHA，列明六应用重建、无迁移、配置仅版本身份、原有开关和额度不变；锁内停 Beat/排空 worker、备份目标和配置、执行精确清单、核对两公开页及八行原始字段守恒后恢复调度。失败只恢复本包修改字段与原镜像，不删除任何赛事或赛果。
