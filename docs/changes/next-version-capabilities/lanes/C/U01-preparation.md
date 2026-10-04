# U01 独立准备及协调决定

日期：2026-10-03，Asia/Shanghai。方案基准 `2919dd3558950466e18a8886ec8bc7f85a119f5a`；本附件仅补充准备，不开始行为实现。

协调者消息确认：F05@6fd64c87 原R APPROVED，F05-M-01 CLOSED；F04真实计时仍待测。U01产品/架构决定：可信等级投影在现有展示开关两状态保持筛选/标签一致，其他单位与无关展示不受影响；未证Local G1不升级国际G1，香港明确国际G1保留；不把离线空字段fixture说成德国六对象的生产字段；SQL/Python须等价且分页前完成，不能等价先报告协调者，不自行全表后过滤或新增schema。

[U01-offline-cases.json](U01-offline-cases.json) 准备33个合成场景，每例在开关True/False下核对code、label、family。涵盖规范G1/G2/G3、原文/空规范字段、Group罗马数字、全角字符、Jpn/JG、冲突/未知/地方体系、Listed/Open/普通赛事类别；用于后续原方案批准后的真实RED及等价性fixture输入，当前未执行测试，不能报告RED或通过。

进一步只读调查发现必须覆盖的既有语义：`test_race_information_display.py StrictParserTests.test_jra_grade_suffix_is_only_removed_with_matching_name_and_source` 及 `race_information_display.event_grade_field/_catalog_meter_profile` 允许在已核验的2026 JRA官方目录profile下移除**匹配赛事原名**后缀；无来源或错原名则待核实。SQL表达式仅识别“完整裸等级字符串”会漏该已支持样例，故清单加入可信/无来源/错名三例，R需审查完整源上下文等价性。此时没有证据证明SQL已可等价，也不能先简化语法实现后再称完成。

预计验证复用已有 `test_race_information_display.py`、`test_race_information_display_pages.py` 和 `test_historical_race_calendar_integrity.py`。DB表达式实现前应先明确同源语法、Unicode/NFKC和源上下文映射边界；如必须改变源信任规则或需要物化字段由协调者/A安排。当前不新增测试模块，不修改parser/model/query，不重采F05页面，不开启生产动作。

本轮验证仅JSON解析、ID唯一与场景数量校验、链接检查、diff检查。等待原R对2919dd35及本附件的方案结论，再由协调者派行为实现。

协调者补充本地测试资源：后续每条容器命令显式 `DOCKER_CONTEXT=colima-umanews-impact-ci`，不能改默认context；按固定SHA、现行 `run_test_plan --build` 执行，缓存镜像不代替交付证据。三线共享先最多两个执行批次，长full需先向协调者报SHA与运行目录。此处为协调者交接信息，C本轮未启动容器或独立核验daemon；实施获派后才按运行前规则核对资源与周额度。
