# C-023 O03 离线交付装配与最小测试接线

任务 `C023-OFFLINE-DELIVERY-ASSEMBLY-GLUE-001`。当前交付：已实施固定main上的逐字节装配与最小测试glue，静态核验通过；业务/collector/Django setup/hostcompile/容器/native/真实网络均未执行，独立实现review与formal full证据仍待ROOT。旧114/625实际GREEN只继承为原冻结fixture与原业务字节的历史证据，不能测试新glue。

## 1. 范围、工作树和固定提交

既有明确派单覆盖本片G1；根AGENTS唯一人工门禁来源。未改变主线或生产，无G2/G3动作；不push/PR/merge/deploy、不写ROOT共享mapping/dispatch_state。不是独占代码库，其他线程和旧C工作树保留。

- 原C工作树 `/Users/mentianlu/.codex/worktrees/bc9b/umanews` HEAD `91c0b0e20f47dbb4f8c60d2f6a6cbb1a5c3fa225` 保持，不merge/rebase旧分支。
- list_artifacts无适用附着worktree；按派单用create_worktree指定固定main创建并附到本聊天。新目录 `/Users/mentianlu/.codex/worktrees/c023-offline-delivery-glue/umanews`，分支 `codex/c023-offline-delivery-glue`。
- base `22e130adf4464fd3c5dd63ccd3f508c4a853d464`。
- 装配提交 `185f7b3375210a0da6f34426918b87c1fb2038a6`，parent=base：23原始路径按C022逐bytes装配，21既有main依赖不变。
- glue实现提交 `49036199a7193421fbc6ae1ee95a267b02180a63`，parent=185f7b；tree `af071f09ed77843c4df654107b34b85b0029def9`。本报告随后另提交，完整final HEAD/tree以专用runtime `delivery-manifest.json` 记录，代码/test bytes不随报告提交改变。

R方案 `5f5c7fb8a8ffdc9e5f65facef0ff022b0b8b2d79` APPROVED_OFFLINE_ASSEMBLY_PLAN_REQUIRED_NEXT_DIFF；报告SHA `4c6f5be445fb1333dfae8a37961ead07f9b5d76a7b5c5c373a7cf4bdb9074ba2`。该意见只批准最小装配/接线边界，未批准本卡实现或formal结果。

专用runtime `/Users/mentianlu/.codex/runtime/c023-offline-delivery-assembly-glue-001`：assembly-original/source-index/mapping-proposal/trusted-base-controls、assembly.diff/glue.diff/final delivery.diff、静态结果与最终delivery-manifest/索引。报告与用例之外不新增重复规格工作流文件。

## 2. 原装配与本轮实际变更

先按C022原source-inventory复制23路径，固定第一提交，再做glue。fixture v1六件/v6七件/C015单件、parser/adapter、两共享模板与原render test均保持原SHA；7v6已显式入Git，原candidate `2ad69d705f55764822ec4dfb52c4d838aba95aecb4529d7170fe60dabaea4968`与v6数据不重签。固定descriptor的历史来源是provenance数据，不读取旧机器runtime。

第二提交最小改动：

| 原路径 | 新路径 / 处理 | 字节关系 |
| --- | --- | --- |
| stable/tests/public_probe_template_support.py | stable/testing_public_probe/support.py | 100%同字节；__file__.parents[1]仍为stable，v1/v6相对fixture根正确 |
| stable/tests/public_probe_template_urls.py | stable/testing_public_probe/urls.py | 100%同字节；原三个URL name/path与禁止HTTP endpoint保留 |
| stable/tests/public_probe_template_settings.py | stable/testing_public_probe/settings.py | 替换为仅供class override的常量；旧全局dummy settings删除，详见glue.diff |
| 无 | stable/testing_public_probe/__init__.py | 空文件，无legacy re-export |
| stable/test_public_probe_template_adapter.py | 原位置 | 全部14裸support imports改同一全名；添加settings常量import与类override；原20测试方法的AST仅ImportFrom.module变化 |
| 无 | stable/test_public_probe_template_glue.py | 新增3个接线/恢复测试；未运行 |

以上均在 `server/` 下。对main最终产品/fixture/test路径25项（23新增+2模板修改），另测试设计和本报告2项；对第一装配提交的glue diff明确含两100%rename、旧settings删除/新常量与测试变化。既有main没有三个旧helper路径，最终不留重复可执行helper。

保持main的21同字节依赖，包括A F01/C013/modules/models/tags/base/include/CSS。明确不改 `server/stable/views.py`、`server/stable/services/race_events.py`、`server/stable/services/race_data_sync_admission.py`、legacy `stable/tests/__init__.py`，也不复制C022排除的146旧分支无关/回退差异。shared rules/catalog/profiles/CI控制均按base逐bytes确认未改。

## 3. class隔离与测试设计

`TemplateAdapterFirstRed` 使用 `@override_settings(**TEMPLATE_TEST_SETTINGS)`，databases=set保持。覆盖仅ROOT_URLCONF、TEMPLATES/filesystem loader、固定race_information library、无context processors、USE_TZ/TIME_ZONE/LANGUAGE_CODE、STATIC_URL、必要DummyCache与展示flag。通过Django SimpleTestCase的class生命周期自动恢复，不用全局settings切换、sys.path、settings.configure、DJANGO_SETTINGS_MODULE环境注入或旧全局SQL/network guards。

正式INSTALLED_APPS/DATABASES与PG16后端保持。SQL禁用由该SimpleTestCase负责，不封锁full中的合法DB测试；正式network-none/非root/PG16能力由ROOT可信runner实际核，不从本片静态结构推断。configuration是普通常量模块，不能把它当独立全局Django settings入口。

新增glue测试只在运行时使用正常unittest.TestSuite/class cleanup，未被本卡执行：

- 标准label加载adapter，只接受同模块类的canonical IDs、无loader errors/重复，并包含旧关键回归；不修改sys.path，不经stable.tests。
- 在外层故意不同的URL/模板/cache/时区/语言/flag环境中运行继承adapter的单一EnvironmentProbe；验证三个reverse、实际模板origin、无context processors、apps/DB不变、cursor禁用。正常结束后全部覆盖键与原cursor包装恢复。
- 同探针先完成全部环境/SQL断言，再制造唯一受控断言失败；内层Result必须有该精确失败且无errors，再验证失败路径class cleanup和外层SQL限制保持。此控制失败不记为业务RED，不能靠任意早期失败冒充恢复通过。

本卡没有top-level导入adapter测试类来造成重复模块收集；glue通过module alias使用父类，局部probe类不被正式collector作为额外top-level测试类加载。标准collector/full仍是profile/alias/legacy污染与全套相邻DB行为的主要真实验证，不以该局部测试代替它。

测试设计：[C023/test_cases.md](C023/test_cases.md)，G01–G06包括标准collection、成功/失败恢复、SQL、旧业务语义、相邻full与交付身份。按仓库TDD技能先写用例再接线；明确派单禁止本卡运行，因此没有真实RED/GREEN，TDD与formal执行均NOT_RUN，不能称完整验证完成。

## 4. 源身份、静态核验和未知项

`assembly-original.json`保存23初装来源commit/blob/runtime SHA；`source-index.json`保存最终46项闭包，含21保留依赖、迁移前后路径、old/new SHA/bytes与glue身份；`delivery-manifest.json`分别固定旧fixture/RED/GREEN/R lineage、base/assembly/glue/final tree、每项blob/SHA、可信base controls与待ROOT映射版本。

自有checker只使用Git/JSON/AST/文件/hash，不import业务或Django、compile、调用collector。静态通过：

- 23原装配SHA与21main依赖；业务adapter/templates/parser/render-test及fixture字节未改；7v6入Git。
- 14全名imports；support/urls字节迁移、空init、旧3helper不存在；fixture根与原URL表保持。
- 正规化导入与新增类decorator后adapter整模块AST等旧装配源；20原方法逐序保持，无删除断言/helpers/案例。
- 没有stable.tests/legacy imports、sys.path读写或绝对机器路径；class override不含DATABASES/INSTALLED_APPS/secret；legacy入口/main排除文件/共享控制未改。
- Python AST语法解析与git diff --check通过；不是Django运行或formal检查通过。

第一次自有checker把旧测试局部`import sys`（算术预算参数使用）误当新sys.path接线拒绝，随后仅收窄检查器为禁止sys.path与legacy入口，业务/test源未为此改动；old checker SHA与修正记录在checker-correction.json。该静态工具问题不计RED，不掩盖实际runtime未知。

剩余未知：新glue的真实Django class生命周期、正式collector实际canonical集合、PG16/full结果、其他合法DB测试的相邻兼容、实际镜像/隔离与远端policy/branch protection。没有allocation，未执行任何作者worker/helper/test/runner，未安装或访问真实服务。

## 5. ROOT所需mapping与正式步骤

mapping-proposal.json列出最终新路径逐项→domain/label/profile；只提案，ROOT独占共享注册：

- public_probe_render → stable.test_public_probe_render，profile python，依赖public_probe_contracts。
- public_probe_template_adapter → stable.test_public_probe_template_adapter + stable.test_public_probe_template_glue，profile django，依赖render+content_contracts；helper/config/URL/empty init、v1/v6与新glue路径均需登记。
- 既有content_contracts→race_timeliness_contracts/public_probe_contracts链与纯叶责任保持。测试模块须登记tests/domain/owner、各canonical profile；docs两路径按既有文档规则处理。两个共享模板已high-risk，新映射未登时full前仍fail closed。

后续建议顺序（本卡全部NOT_RUN）：同原R审核固定490361 glue代码及原装配/最终报告；ROOT注册映射并固定信任版本与新集成tree；可信base static工作流合同/新增Markdown引用扫描；正式collector以标准server路径、Django setup后实际收集所有适用canonical ID；PG16 UTF8/network-none/nonroot全量执行，≤200整类batch和有界并发；原10允许skip逐ID/reason，不扩展或当PASS；独立可信verifier绑定实际test-tree/run/job/attempt/image/collection/execution原件。无需为import/settings-only glue机械重签旧v6身份，正式证据另绑定新Git候选。

旧114/625、32lambda七阶段与原18谓词只保留旧实际收据，formal runner当前验证合同不同，不把这些旧数预填为新full结果，也不增加旧runtime身份算法到正式全套。

## 6. 交付边界与停止点

本片仅离线parser/adapter装配与测试glue；O03整体仍部分完成。可信loader、匿名views/ORM权限、浏览器CSS、source→execution→public SLA/失活、队列外/下一动作/workerBeat/probe自身失效均未包含。无迁移、生产配置、模型/数据动作或公开自动化。

本卡完成固定实现及静态材料即停止，不自开下一卡、不执行检查窗口。额度起始67used/33remain，周期复核仍67/33；上限used68或本卡固定完成即停，未用积分/reset/换模/代理。最终report/head与runtime索引交ROOT，由ROOT安排原R实现审及适用正式资源。
