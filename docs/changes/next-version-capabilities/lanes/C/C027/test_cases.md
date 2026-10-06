# C027 真实本地演示与最小修复验证

固定主线6e6aded2，不重写U01/U02。合成数据与SQLite、内存cache/email/broker专属隔离，无出站/worker/Beat。

- 真实浏览器首页：今天起七天最多四场，七天内第五场与七天外重点场不回填；未知时刻不显示00:00/伪时刻；1440px与390px真实截图。
- 真实日历：G1查询与卡片G1/Jpn1集合一致；缺地方体系可信profile的Local G1不能提升为国际G1；德国G1按region过滤为单场。
- 真实详情/返回：从grade+region+year列表点击详情，返回后条件与集合保持；原view/template/CSS不改。
- 发现SQLite新HTTP线程第一次compile公开时间表达式连接未打开，真实GET返回500 AttributeError，计技术RED。新增一个完全独立的in-memory SQLite wrapper，在未连接状态编译并执行实际SQL；date-only/known-clock结果分别正确。mutation删除ensure_connection应失败。先运行该回归RED，再仅修as_sqlite初始化、同例GREEN、同URL真实200及全演示浏览器复验。PG代码不变，不重跑旧整组。
- 发布边界：QQ默认False/发送guard/终态skip/Beat删除/Compose删除逐项只读盘点；本地关闭仅属于隔离演示，不是生产QQ下线批准。
