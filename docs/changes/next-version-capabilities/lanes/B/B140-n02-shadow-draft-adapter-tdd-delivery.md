# B140：N02 draft shadow adapter 有限本地 TDD 交付

2026-10-14。已实现/本地有限验证，待原 R 代码审；未登记正式影响映射、未push/PR/合并/发布，完整N02/F02/TC-N01/I2仍false。父对象4742db60b8adbace7dd00f89b2b55550a33e56b1准确含原已审内核与B139合同。B139入口由原R c6019f279dbfdb8a4d1f75d6f268b5db6c3ddbb2确认，ROOT在既有candidate-only范围明确授权本地实现/测试；根AGENTS.md仍为唯一门禁来源。

## 最终行为与范围

仅新增services/content_review_shadow.py、stable/test_content_review_shadow.py和本文。所有关键参数必传，无生产profile或copy限额默认。普通snapshot/context逐字段与独立expected/site/URL/ID/容器hash/full trace/body匹配；canonical只诊断。先固定六copy_limits支持检查，再对逻辑frame作exact builtin/祖先cycle/depth/每次出现nodes/容器长度/UTF8与JSON转义字节预算；两遍有限复制，第二遍重检、共享输入子对象复制成独立可变对象。拒浮点/子类/custom对象/自定义metaclass equality hooks，不先deepcopy或整体JSON编码，不截断。

合法副本仅调用原kernel公开review_candidate，源内核的profile、完整trace/decision和digest验证照旧；无私有核helper、无新digest/cleaner/证据算法。输出完整envelope再限额与隔离；失败只有固定adapter_gaps/None或原核blocked，无旧body fallback/partial delete。仅固定无用户内容adapter错误响应豁免过小payload cap。unknown保护合法verdict为manual，known仍candidate-only，两flag恒false。

模块只import re、原kernel和原normalize_whitespace，无DB/模型/抓取/SDK/provider/任务/storage/runtime写入口。复制不是来源认证，也不是并发原子快照；caller单次同步期间不得并发改输入，expected/capture/policy/profile的真实发行责任仍由独立可信caller承担。没有真实context时blocked；真实策略/模板新鲜度、质量阈值、retry/cost仍缺口，没有旧publish全路径封堵证明。

## 真实RED→GREEN证据

原HRN parser→normalizer生成actual CanonicalNewsDraft的三eligible普通投影；独立TEST_ONLY expected/context/profile固定。控制先1PASS，socket.connect与DB.ensure_connection从django.setup前贯穿suite被禁止，未连接DB或实网。现成venv与B135原wrapper复用，没有新runner/框架/安装/PG/Docker/VM。合成fixture不能当真实源/capture/法国freshness或全N02验收。

| 组/合同case | 实际RED/应捕获mutation | 同例/有限GREEN |
| --- | --- | --- |
| S01 | 最小可调用no-op，assertIsInstance(review,dict)真实1FAIL/0ERROR/exit1，缺候选结果 | 同例1PASS/exit0；A+C/manual/B精确diff/两false/输入不变 |
| S05及S03–S12接缝 | 新source_article_id与重算合法verdict仍背离独立expected，真实1FAIL/0ERROR/exit1，捕获忽略来源绑定 | 11PASS/exit0；shape、TDNFrance discovered/canonical、URL/capture/body/trace、保护/attempt/profile/stale、异常不假成功 |
| C01/C02及C03–C10 | 无copy preflight使None limits、N−1 wire cap仍成功，2FAIL/0ERROR/exit1 | 19PASS/exit0；限额/UTF8转义/非法unicode/cycle/custom类型/早停/alias/输出预算/原kernel两层cap |
| C06 metaclass hook | 类型membership比较调用type equality hook，1FAIL/0ERROR/exit1，捕获customhook执行 | 改为is身份比较后全新module GREEN；不改核算法 |
| C04/C05/C11、输出copy/R组 | 精确手算nodes/depth/items、DAG重复出现、二遍受控测试注入、输出field/node/depth/对象、输入与核参数引用隔离 | 最终新27+旧kernel23+旧N01 trace12，共62PASS/0FAIL/0ERROR，exit0，0.129秒测试体 |

完整命令/exit/log和每组固定测试树/两源码blob/SHA见runtime tdd-stages.json。阶段tree由保存原字节与固定parent重建，不冒称阶段run时已有对应branch commit；S01最初stub/tests本地commit c3eab0385，后续dirty阶段完整原件保留。copy-green测试是已执行19例的保存prefix，从后来仅追加测试前的原件提取、无重写oracle。无setup/import ERROR计为RED。

一处确定性测试oracle修正单列：kernel packet_bytes=1先触发原container_invalid而非byte_size_limit；改测试cap为100精确针对byte边界，原失败日志copy-green.log保留，未改kernel。之后回归绿；这不是新增功能RED或隐藏错误。最终bootstrap copy_limits先type/len=6再遍历keys，防无限配置遍历。最后增加known-empty保护/键盘及进程异常传播/dataclass拒绝后执行有限62项完成回归；没有无理由重复full。

B139的27case对应27个新test methods（含fixture control及组合/subcases），部分case共享方法而非逐个方法同名：S02/S12合并keepall/repeat/no-fake-error；S09–S11组合保护/attempt/profile/stale；C04/C05组合node/depth/shared/cycle，C06另metaclass/类型方法；C09输出budget/资源probe，C11二遍受控注入；R01旧相关回归，R02静态imports和动态guards/hidden-parser sentinel，R03各输入前后/核参数mutation，R04失败无partial。并非复刻旧23项核测试。

## 固定交付与剩余工作

11个原件逐字与parent相同，包括kernel/test、N01 cleaner/trace、international/base、tasks/ingestion/models、共享catalog/rules。功能受测tree a20389c9b322f2fbcf05601aceea2368ddd8ab76仅两新功能文件；本文属交付记录，不改变受测代码。原R下一步只读代码审，ROOT负责映射/整合及必要正式CI，不自行触发旧PR测试或读取镜像。

Runtime `/Users/mentianlu/.codex/runtime/b140-n02-shadow-draft-adapter-tdd-001`保存8组受测树、完整日志/原件、guard wrapper、原R入口报告与receipt、静态11原blob/hash、最终commit/receipt/seals。无真实SDK/source/network/paid/DB/hook/metadata/route修改，无CIrerun/image下载/merge/deploy；真实caller接入和发布治理属于后续独立范围。
