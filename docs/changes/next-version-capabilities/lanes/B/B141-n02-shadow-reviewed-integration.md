# B141：已审 N02 shadow 普通副本本地集成与测试登记

2026-10-14，仅本地固定候选，待原R集成窄审。独立codex/b141-n02-shadow-reviewed-integration准确从PR250 head d065b62efde24821f7f3501ef4d279ea5df456c1创建；该parent**未合并main**。实时PR250 open Draft/head d065/base1dd5e0a508957672bcddd1c33e454fbbef1b75c1，main同1dd5。未更新PR250、push、触发CI或另建PR；旧d065正式CI只属于旧对象，不能移作新adapter证据。

## 精确来源与范围

逐blob/bytes/SHA从获审B140 76a7eb3f35105f25f13f9c5d962820a904b7ba04导入**5个文件**：content_review_shadow.py、test_content_review_shadow.py、B139 contract.md/test_cases.md、B140交付doc。两functional blob完全逐字，未夹入未审实现。B138 plan仅引用固定fc5d33a24原件，不导入另一方案分支实现。原R代码审250bdbdfd1a13c00c62b6839e00cf89112521ed2/SHA d84f1246b8b47075c32226144c0fd58d812d3ac0a988c2c8dcab2a8551dde69d及receipt SHA5c0815035e0d1dd023927eb108d91a64ca730f74520a8fe671e9d240c8337678已核；R62+7wire/alias为获审对象事实，不替本候选formal收集。

只额外修改tools/test_impact/rules.json与catalog.json登记service exact path→news_translation，test label stable.test_content_review_shadow→同领域/profile django；以及本文。相对d065共8路径（5导入+2mapping+本文）。kernel/N01、源tasks/ingestion/hook/model/route不改；未改ROOT台账/A080/C/PR251/B137证据。短时OS flock包裹本线shared mapping登记，OS退出自动释放，receipt另存，不用裸lock。

catalog仅news_translation列表追加该label、tests单条、profiles单条；rules仅追加exact service path。删除这四delta后parsed JSON与d065完全相等，所有旧domains/labels/dependencies、high-risk、symbols、module_initialization_full、skip/批次规则保留；不因本模块无DB而缩旧覆盖。13个受保护原blob/hash（核/N01/源调用链/worker/runner/workflow/source-binding）逐字保持。

## 真实profile与有限验证

新test实际import原international parser/normalizer、models枚举和原kernel，不能当独立stdlib文件。登记**django**与既有N02一致。固定worker.setup先verify source binding、清env、isolated_environment、django.setup；execute django profile实际要求PG16 SELECT version/probe及DiscoverRunner。即使python profile也先setup Django，但本片不以切python绕过既定django probe，不改profile/runner/framework。新TestCase自身不需业务DB，**本地**用B135既有最小Django/venv wrapper，全suite从setup前拒DB.ensure_connection/socket.connect，不等于正式PG/隔离runtime证明。

本候选一次必要本地回归：新27+旧kernel23+旧N01 trace12=62PASS/0FAIL/0ERROR，0.138秒测试体。mapping合同scripts.tests.test_test_impact/test_impact_git/test_impact_evolution=39PASS，exit0，3.998秒。mapping log中的validation-only/missing release evidence是既有unit fixture输出，不能当本候选计划或正式delivery判断。未执行native collector/full app/真实源/SDK/provider/paid/本地PG/Docker/VM，未重复旧CI或读取镜像。

真实select_changes核8个具名路径：新service、新test和旧kernel各targeted core+news_translation=27human labels，含new shadow/kernel/trace/content boundaries；原international/base/article_content/text/models仍full330。这是现显式路径/领域依赖覆盖，并未新建通用Python reverse-import图；既有dependencies图逐字保留。unknown sentinel单独或与models high-risk合并仍unmapped fail-closed，不转空/全量成功。

## 静态全集与身份边界

main旧全集328labels，PR250 parent329，候选**330human labels**，旧labels均保留，差集只有stable.test_content_review_shadow。候选标签profile分布django256/python71/release-postgres3；catalog模块profile条目另为django239/python71/release-postgres3，分母不同不混用。领域全集266；10条allowed skips原内容/原因/profile/review_by2026-10-16不变，不延期。真实native ID/count/batches/profiles/RUN/实际skip/镜像/ownedCID cleanup尚未采集，不能猜成6886+27。

原planner scripts/impact_ci.py --scope affected按固定Git完整whole PR差异（base实时main1dd5、head本候选、test=head）生成full静态old+new计划；另以d065 parent作base生成integration slice计划。test=head只是本地静态单对象身份，不是实际GitHub test merge；新候选尚无PR test merge/run。控制paths20，两个mapping控制blob更新，其余控制原件保留，不新增workflow/runner/control供应。最终HEAD/tree/plan source refs/控制blob/digest实数见runtime收据，不手写虚构merge。

只有fixed普通副本candidate-only shadow：两flagfalse、unknownmanual、缺context blocked；没有真实capture/policy/profile issuer、新鲜度/质量认证，也未封旧发布链。正式native/CI、本对象原R集成审和真实caller接入继续未完成；fullN02/F02/TC-N01/I2=false。

交ROOT/原R只读集成窄审；通过后由ROOT另派精确更新现PR250和正式CI，保持旧对象证据。通用门禁只引用根AGENTS.md，无merge/deploy/生产或额外PR授权。runtime /Users/mentianlu/.codex/runtime/b141-n02-shadow-reviewed-integration-001保存5导入pins、13保护pins、实时引用、lock、mapping/path checks、local logs、固定计划/commit/receipt/seal。
