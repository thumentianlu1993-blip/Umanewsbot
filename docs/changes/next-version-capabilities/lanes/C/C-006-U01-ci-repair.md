# C-006 / U01 首批CI日期窗口回归返修

2026-10-03，Asia/Shanghai。首批PR235固定head `6d58d0685e70579a5e8ec5302d003a79a5668a2f`，实际CI run37058080085/attempt1失败。协调者原始账本6236tests/41batches中只有batch020本测试FAIL；本线读取batch020.json/log核得1failure、0error。并未在本线重新执行全部6236项。

## 定位与最小修复

旧fixture helper `_make_event(normalized_grade="")` 写 `grade_text=normalized_grade or "G1"`，因此“无级别今日”原始字段实际是G1。U01已批准的可信等级语义应把明确原始G1纳入G1家族，7/27出现是正确筛选；错误在测试对象名称与数据不一致。没有依据修改已审查询/业务语义或删除7/27实际G1。

修复只在既有 `test_grade_filter_scopes_window` 内将无级别对象的grade_text与normalized_grade均置空，保留其它helper消费者；添加G2(7/29)、G3(8/10)非匹配日期及卡片排除断言。原G1(8/8)日期轴唯一、正文卡片及aria/今日样式断言全部保留。不是改期望来放过错误，也不是skip/免测，不改日期窗口/公开资格/筛选规则。

独立fix提交 `f910d671b275c616ea628975b13fd2a919eecc0c` 仅修改 `server/stable/test_race_calendar_default_date_window.py`（11增1删）。root可精确cherry-pick该提交，不要合入本线Q01/F04历史；后续报告另提交。生产/共享集成树/PR235无本线操作；未pull/switchmain、未占B预留PG。

## 真实RED与GREEN

- 固定 `6d58d0685e70579a5e8ec5302d003a79a5668a2f` 树外Git archive，宿主隔离SQLite、固定单label真实RED：1test/1failure/0error/skip，实际日期轴含7/27和8/8，原期望只有8/8。red-6d58.log保留；初次bc9b同内容定位运行单独存red-5d2.log，不冒充固定6d58。
- `f910d671b275c616ea628975b13fd2a919eecc0c` 固定树外Git archive，模块label `stable.test_race_calendar_default_date_window`：41test全部PASS，0failure/error/skip，覆盖等级、地区、时态、默认窗口、cursor、year/q、隐藏/duplicate、40卡片及查询预算。green-f910.log为固定证明；提交前同文件41PASS另存green-bc9b.log，不替代固定收据。
- runner清空继承env/禁dotenv、`:memory:` SQLite、memory broker、locmemcache/mail，不接真实生产DB/Redis/队列/第三方。Django5.2.1；宿主SQLite专项不冒充PG或正式full。
- diffcheck PASS；没有新增测试模块，原full分母/登记不缩。协调者将本提交增量交原R后更新PR235候选并重跑actualfull；本线不宣称CI已恢复或完整交付。

## 证据

运行包 `/Users/mentianlu/.codex/runtime/c006-u01-ci/`，含两个固定archive、诊断manifest、RED/GREEN日志。
- red-6d58.log SHA256：`f4255825e162750aa18bd7407141a567d08e8dc204986000c8f80922cf44cc52`
- green-f910.log SHA256：`c2c2c90a7722fbf44e91949c81c15247740a036fbc14419e9a61889553efbc86`
- diagnostic-manifest.json SHA256：`15b571c7d3533d92bfc516dd692e1dbdae62e1ddfca9f7be477cdee9dbd486fb`
- 原CI batch020.json SHA256：`5e6bc641e4070dee3666751e5b5027d9c79926c2a1e89f5a19c7529de4773c94`

当前仅已修复/专项验证，待原R增量复审和root实际full；无新的G1产品分支，G2/G3未执行。
