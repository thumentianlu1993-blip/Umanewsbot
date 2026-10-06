# B035：N01正文区块/清洗差异第一切片

本地实现、离线测试和三个可读例已完成，等待原R复审；不是N01五地区质量验收完成或已发布。基线为ROOT指定main `6e6aded22764ebee3d6a97f2834f47d4b4baa7bb`，独立worktree `b035-n01-cleaning/umanews` / 分支 `codex/b035-n01-cleaning`。旧B034/B033 runtime与旧B工作树保持。未改views/models/settings/迁移/共用catalog/他线树。

## 可见结果

[三个清洗前后实例](B035-n01/examples.md)，以及可机器复核的[完整输入/结果JSON](B035-n01/examples.json)。正常正文保留首尾、引语、列表；导航广告污染被删除但赔率/专名/事实保留；没有可信容器的宽main明确报selector_not_found，不用非空网页框架充当正文。

样例仅开发fixture/合成，不是原始完整网页、F02 gold或生产证据。现有HRN fixture无法确认真实抓取时间，仓库最后记录为2026-07-24（9fded052）；不把提交时间冒称capture时间。两合成样例参照现有Sporting Life容器结构；演示生成于2026-10-06。没有模型调用、网络抓取或生产读取。

## 变化

`article_content.py`仍用现有结构/来源/CTA/促销/首尾规则；原规则与文本输出不扩大。新metadata保持原removed_count/removed_rules，附trace_version、捕获正文HTML SHA、before_text/after_text及区块。每块有绑定source+正文捕获SHA+逻辑位置+原文的确定性block_id、original_text/text、kept/modified/removed及原因。结构噪声定位为删除前DOM路径；paragraph[n]为结构噪声去除后、语义清理前的逻辑段落序号，原文为DOM规范化文本而非HTML源码。没有跨捕获持久身份或通用区块框架；scripts/styles不额外复制可执行源码进文本证据。原始HTML仍沿现有SourceArticleDetail.original_content_html字段传递。

清洗规则的局部行为与计数复用旧helper；trace跟随每个段落发生位置，不通过文本匹配抢占重复段落。正文重建与所有保留block text拼接相同。同词导航和正文可分别删除/保留。metadata是既有adapter输出的一部分，可沿现有metadata消费者保存；本轮无DB写入，未验证生产持久化。

`SportingLifeAdapter`去掉宽article/main后备，只保留现有`[class*='Article__ArticleBody']`与`article .article-body`。缺可信容器时沿原selector_not_found路径报缺口；可信容器清完为空沿原empty_after_cleaning。其他来源选择器不变，不新增正文长度规则/自动发布门禁/模型审查。仅正文提取失败行为变化属于已委托的G1范围，G2/G3现场或主线交付未授权。

## 测试与实际界限

测试设计[见本片test_cases.md](B035-n01/test_cases.md)。使用仓库tdd fallback；按ROOT当前“先固定小切片提交、后原R复审”的指令，本线测试设计自检后直接RED/GREEN，没有冒称实现前独立review已通过。

- RED：5tests/6 assertion failures，实际exit1；区块证据不存在和宽article/main仍误判ok。原始日志`/Users/mentianlu/.codex/runtime/b035-n01-first-slice-001/red.stderr.log`及red-exit.json。
- GREEN：独立SimpleTestCase 10tests/exit0，含七个固定基线fixture逐字正文/status/removed_rules对照、block重建正文、重复文本、同词nav、空结果、可信边界、引语/表格/图片说明、TDN/Sponichi规则、nested noise。原始green日志/exit保留。
- Django仅在测试进程配置内存SQLite及必要apps，不建库/不连接；SimpleTestCase禁止DB，socket.connect被拒绝。没有Redis、队列、外部模型/API调用。
- 合成1000段烟测输出1000个block、末段保留，约0.13s，metadata约380KB，仅本机诊断，不是生产容量/费用证明。证据`size-smoke.json`。
- impact planner实际阻断：`ValueError: catalog drift: server/stable/test_article_content_trace.py`，未产自动计划；未为绕过此项编辑共用catalog或启动旧全套/Docker runner。新测试模块的既有catalog/profile最小登记需ROOT/R处理后，才能有自动交付证据。本地10tests不能替代该流程。
- git diff --check通过。最终提交SHA及证据hash由包外handoff-receipt.json绑定。

## 剩余及风险

本轮只有代表模板/开发样例；五地区现有启用来源模板、完整F02取数与独立gold污染<1%/关键误删0、模型检查、UI消费及生产验收仍待完成。新trace增加metadata体积；尚无真实语料费用/容量结论。Sporting Life仅宽容器的旧模板现在会报缺口，不能声称覆盖所有线上版本；后续用真实样例核可信选择器。其他来源仍有旧宽回退，本片未扩改。

正文output文本保持但body_cleaning metadata新增字段，旧历史repair manifest若绑定整个解析metadata摘要可能触发输出漂移fail-closed；不复用旧批准结果或自动重处理历史数据。保留已合并后台/QQ代码，不做下线或回滚。

交ROOT后原R只读复审业务切片与精确提交；测试登记和五地区质量缺口分别记账。没有push、PR、合并、部署、外发或生产计数。
