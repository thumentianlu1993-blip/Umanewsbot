# 修复设计

沿用 `parse_hkjc_observation → attach_multisource_observation → historical claim → 正式赛果投影`。
不绕过强身份、完整名单、writer owner、来源策略或人工锁。HKJC 领域规则限定于 `hkjc/hong_kong`：

- Actual Wt. 按磅记录；Win Odds 保留原十进制值，不由赔率推算热门排名。
- LBW 是距头马差距；转换 `7-3/4`、`N/HD/SH` 等来源记法，保留原值，`---` 归缺值。
- WV/WV-A/WR/WX/WX-A 为退出，TNP 为未出赛，FE 为跌倒；无正整数名次时不生成完赛名次。
  未知符号继续拒绝整场，VOID 不冒充完赛。
- 赛果投影写回赔率及单位；已有 runner 只在官方值一致且无字段锁时补单位，状态尊重行锁/字段锁。
- 赛果表补负重，HKJC LBW 标注“距头马”。仅从赛果创建的香港 runner 标注“参赛记录（赛果来源）”，不冒充赛前卡。

字段解释依据：[JRA 对 HKJC 官方页面的字段说明](https://www.jra.go.jp/keiba/overseas/website/hkjc/)。
赔率口径同时核对官方完整结果的 Win Odds 与每 HK$10 的 WIN 派彩，数值原样保留，不作投注推算。

`repair_hkjc_race_fields` 只回放固定包。manifest 绑定政策摘要、赛事及投影基线、原文文件/URL/SHA；
全包持有事件行锁并在一个事务内处理，默认结束回滚。既有六行中文 runner 仅使用已存 HKJC horseid、
场次和号码对账，来源映射后仍保留原 runner 文本；不能凭马号或近似名称绑定。

六场官方页标题登记为当届来源名称，先验证所属已批准 series 与跨 series 无冲突，然后走正常身份解析。
七项数据动作包括六场完整结果和历史卡表赛时、香港杯清空未获来源支持的16:40并补距离单位证据。
未来七场预览候选、206条报名、现有来源policy、43场日本绑定均不改。

幂等以 OperationLog 的 manifest 摘要回执判断。已登记、基线漂移、人工锁、关联旧结果的马匹记录等情况停止，
不自动覆盖。当前生产首场六行的 horse_records/horse_p0_sources 只读计数均为0；执行时再次检查。
