# C008 / Q02 UI与旧action实现提测（待原R）

2026-10-03 Asia/Shanghai。受审方案`7e3f70c22c2a83558b0b7623711a6fba70760afc`，原R C007 APPROVED@e97406d7。固定本卡base同方案head，依Q01已审924a；本线之前C006 f910与F04报告保持。受测行为head `370c20936641f1474341acf0ce9bbc0c7e1c0060`，最终报告head由交接绑定。

## 已实现范围

- false时NewsArticleAdmin动态去列表/readonly/fieldset的push链接，get_actions先调用super保留权限过滤，再仅去PUSH_READY旧动作；直接callback重新guard、伪造POST不改status/workflow/publication、不入队。各getter复制声明不改共享类属性；true既有链接/动作保持。
- 历史PUSH_READY/PUSHED/PUSH_FAILED在列表明确标历史QQ状态，status表单加停用/历史说明，数据枚举及旧值不改；其它内容状态照常显示，列排序仍status。历史模型/inline及staff查看保持。
- QQ停用窗口详情去重跑和发送预览链接，提示只读历史；直接预览保留qq_channel_disabled原因，隐藏预计QQ文章且零选择器/网络/写入。publish与true QQ的控件继续存在，原Q01端点guard不改。
- 地区生产保留历史计数与最近窗口，明确QQ停用，未发送不叫等待运营；空列表也有停用说明。true原计数文案维持，公开/抓取/翻译/术语业务不改。
- 改动仅admin.py、三个console模板、三个views上下文、既有tests_legacy和C文档。五旧task已具备审计，直接复用，tasks.py零改动。不改settings/Compose/部署、Q01 gateway/CAS、模型/迁移/数据/权限体系；专属依赖退出仍交root/operations与O06。

## 真实RED / GREEN

固定 `faf3b62cb0429edd12fc4da2a7fabc55770fb548` Git archive中9个初始case：5行为FAIL、0error/skip（另外4项旧权限/CSRF/历史注册/true合同原本正确）。捕获Admin链接未藏、旧action改写、QQ窗口控件仍在、预览及地区缺停用呈现。首次测试ArticleStatus导入遗漏已修，不用含error日志当RED。

Admin阶段3例GREEN后完成模板/context；空历史列表与历史PUSH状态各取得额外宿主1例/1行为failure/0error，然后实现。两条补充RED是当时工作树诊断，单列日志，不冒充初始固定9项Git证据。11个新专项与相关5label集最终固定 `370c20936641f1474341acf0ce9bbc0c7e1c0060` archive：62/62 PASS，0failure/error/skip，1.159秒；实际精确62 IDs已离线collect并写manifest。没有PG/lease/事务/schema的新行为，不占LinuxPG窗口、不重复已审PG76，也不迁移旧PG收据到本实现。

runner来自既有runtime local-run.py，清继承env/禁dotenv，SQLite memory、memory broker、locmemcache/mail，OneBot全mock；不会访问生产DB/Redis/真实队列/provider。宿主固定Git证明为开发专项，不是network-none Linux收据/actual CI/full/生产零发送证明。

相关label：QQRetiredUITests、QQShutdownTests、MultiRegionNewsProductionTests、QQWindowServiceTests及SingleQQDeliveryTests。覆盖新UI/action、邮件/网页解耦、区域/窗口、true兼容、匿名/非staff/CSRF/缺对象/requirePOST；history DB值及Admin注册/inline保留。测试设计与mutation见本线test_cases.md的C008段。

## Formal阻塞与精确mapping proposal

最终base→行为head执行impact_ci.py affected fail-closed，仅unknown为views.py三符号region_production / production_window_detail / production_window_preview。Q02-impact-mapping-proposal.json提议每个符号精确映射既有module:stable.tests_legacy及module:stable.test_multiregion_rollout_change，保留权限、UI与区域通知消费者；不加path通配、不改catalog/profile/dependency、不缩full分母。admin/templates/tests已有路径归属未报unknown。新增11 IDs位于已登记tests_legacy，无新增模块路径；实际full需root collection验证，不以此免除验收。

本线没有修改共享rules/catalog，没有自行full或降低风险策略。原R审核本实现及提议后root负责集成映射、候选及actualfull，C008不自标完整交付。

## 证据与交接

runtime `/Users/mentianlu/.codex/runtime/q02-ui/`：red-source/final-source固定archive、red-fixed-faf3.log、green-fixed-370c.log、final-ids.json、diagnostic-manifest.json；red-empty.log/red-history-state.log及中间日志保留；affected-final-blocked.log记录正式未映射。
- red-fixed-faf3.log SHA256：`e65c35d326814f532f84e45a915740142bf49792bbdf46c117ed63a59bd396d7`
- green-fixed-370c.log SHA256：`57098e9f8fdd3184a1477dd989a82ff3150a7520a29471bb87365be5cbe6a0b3`
- final-ids.json SHA256：`40d024a26dd5693cd442a3c7f2045ed6f509fe0f1fb2bfe23ab7b80a69eb4f7a`
- diagnostic-manifest.json SHA256：`89ceb3579b1b1942990886b1cad08f32376ed64cfc0e305385cea397a4042b30`

本卡准备原R独立代码审核；root不应把单此UI提交当作Q02专属运行依赖已退出。生产flags/各进程SHA/在途切点/真实OneBot容器和卷/健康告警/零发送账本均未核，O06补齐精确包。本线无合并/发布/重启/批量写库/真实发送；无长期进程留存。
