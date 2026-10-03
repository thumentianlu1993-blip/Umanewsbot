# C003-P2-01 返修证据

日期：2026-10-03（Asia/Shanghai）。按原R在`ca7ce4e553a106321da7df2ec7fff800eb3f66e6`的C003-P2-01返修，不扩大业务范围，不改共享规则。

## 真实RED

固定测试提交`e534ccf664836131d158042e5edbb45f1d56462b`。真实GET公开马匹页，关联published赛事Grade 2/G2、历史记录GIII；context已准备G2，模板等级标签实际重新解析成G3。隔离SQLite单例退出1，唯一failure为`AssertionError: 'G3' != 'G2'`，无fixture/权限/数据库错误。

## 最小修复与GREEN

grade标签优先消费已经准备的`public_display.grade`，缺少投影才调用纯`event_grade_field`；不读event属性、不触发关联查询、不force其他字段。事件两展示flag仍通过既有U01回归，马匹记录复用现有prepare_context的published关联来源选择。

新增真实页面回归涵盖published关联G2与记录GIII显示G2、draft关联回落记录G3；检查已准备标签查询数0、整个GET无INSERT/UPDATE/DELETE及原始字段不变。另测试未缓存event的历史记录，调用标签查询数0且关联缓存仍未填充。

宿主隔离SQLite两个模块39项通过，测试体0.355秒、退出0：`stable.test_race_information_display_pages`、`stable.test_race_information_display`。未访问生产或外部服务。此证据不是Linux/PG16交付收据；仍待共享Linux窗口与受审策略控制提交。

返修提交后固定最终head交原R复审，并保持clean冻结；审核结论等待R，不能自行标finding CLOSED。
