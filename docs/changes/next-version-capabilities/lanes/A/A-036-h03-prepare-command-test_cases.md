# A036：prepare-only 命令 RED 测试设计

固定已审方案 A035 `72f82102409bd9d7c6e200fb57a565ed9d23059b`；ROOT 通知原 R `01bcc0879e8c83312d686cf056090810ea44c06e` 已关闭唯一措辞 finding / APPROVED_PLAN_ONLY。本卡只准备测试、独立合成 fixture 和可导入的无写 stub，未执行 RED，更未 GREEN。人工门禁只引用根 AGENTS.md；当前本地测试准备已授权，官方执行必须等精确资源 allocation。

## 测试接口与责任

唯一新 command `horse_basic_profile_from_cache` 默认 prepare-only，正常可发现/导入；stub 只解析参数并输出 JSON `status=not_implemented/reason=prepare_not_implemented`，不读原件、DB或写文件。未知apply/commit参数不能注册。测试文件 `stable.test_horse_basic_profile_from_cache_command` / class `PrepareCommandTests(SimpleTestCase)`，databases=set()。唯一fixture是 A032仓库合成原件的独立bytes副本，不代表真实来源/审核授权。A032/A034服务、shared adapters/writer/models/settings/migrations/catalog/B/C均不改；无需subagent。

可信绑定由调用方分别给 `--expected-input-sha256`（整个packet）及 `--expected-source-sha256`（原cache）；不能从packet内容自算替代独立预绑定。`--input-root/--input` 明确允许根/相对packet，packet的source_file同根相对；`--output-root/--output-dir`明确私人根/全新相对目录。packet严格schema `h03-prepare-input.v1`，含snapshot/cache_ref/source_ref/entity_versions/as_of/max_age_seconds/profile_baseline；不含reviewed/reviewer/authority/apply。单profile:1、单HKJC原件、单H02候选；baseline只是producer快照，不认证实时数据库。

验收stdout为一行JSON：status prepared、reason local_pending_review、reviewed false、七字段basic_profile和artifact_dir；拒绝输出applied/service写入成功。输出 `combined_candidates.jsonl` / `review.csv` / `review.xlsx` / `manifest.json`。JSONL复用canonical正常化并加未审标记/来源绑定（不是production artifact）；CSV原_review_row审批列全空；manifest local_pending_review，input/source SHA及H02摘要/idempotency_key，仅阅读，不填reviewed_input_sha256/生产authority审批。工作簿实际消费该JSONL，keyword调用原函数；只展示摘要，七字段stdout/JSONL查看。

## 六个精确 canonical IDs 与 mutation

统一前缀 `stable.test_horse_basic_profile_from_cache_command.PrepareCommandTests.`，以下方法直接定义，禁止整类/继承展开：

1. `test_prepare_real_pipeline_pending_outputs_and_visible_seven_fields`：正向原件实际adapter→H02→canonical normalizer及现有workbook预检通过，真实命令应prepared/七字段与源一致、输出原件摘要/单candidate/unreviewed CSV和实际xlsx。spy仅wrap真实helper，绝不替换结果。stub正常输出not_implemented使prepared断言业务失败；UnknownCommand/import/setup/fixture/helper异常均不算RED。mutation：命令无消费/绕开H02/不调真实workbook、漏字段/丢原件/伪造已审状态。
2. `test_cli_startup_and_workbook_have_zero_database_access`：真实Django CLI子进程，setup前BaseDatabaseWrapper.connect/ensure_connection/cursor/_cursor及socket all-alias tripwire；default和replica均存在，普通/生产样式DB配置及任意DATABASE_URL均不查询。setup成功marker和zero trips独立断言，完整prepare/workbook输出还必须存在。mutation：ready/import隐式查询、迁移/系统checks、用DB补profile/事先试连。
3. `test_parser_rejects_apply_and_commit_without_database_access`：已通过正向preflight，然后实际run_from_argv/Django CLI拒--apply/--commit，exit2+unrecognized arguments、setup marker/zero trips、没有输出目录。mutation：注册write模式/先执行checks或handler再拒。
4. `test_trust_hash_identity_and_freshness_fail_closed`：独立packet/cache SHA缺失/错配、verified身份退役/冲突、cache过期/partial/源ID错配及越权approval字段，固定原因码CommandError且无产物、原件不变。mutation：SHA自填/名称回退/refresh候选直接复用/把parse complete当已审批准。
5. `test_path_and_json_limits_fail_closed_without_overwrite`：相对逃逸、packet/cache/root/父目录symlink、非普通源、已存在输出、源>128KiB、packet>128KiB、JSON重复key/非有限/过深/额外字段；不覆盖或清理他人目标、不泄漏原文/路径。mutation：check-then-open/symlink跟随、无界读取/自动覆盖、非严格JSON、复用不可信目录。
6. `test_display_canonical_separation_and_downstream_failure_cleanup`：公式/控制字符合成文本，经真实adapter/normalizer，canonical保持原字符串、CSV/workbook公式文本安全、stdout无裸控制字符；目录0700/文件0600、重投existing_output而非applied；真实workbook路径的模拟IO失败固定artifact_build_failed且只清自己的输出，无部分prepared。mutation：用display escaping污染canonical、公式执行、输出权限宽松、失败报成功或残留半成品。单IO异常模拟属于故障注入，正常workbook必须实际调用。

后五方法先有真实helper preflight；负向即使stub提前拒绝也不称保护已验证。静态声明不等于方法/子例已执行。prepared output mutation不能与真实approved source混淆：合成fixture内来源count/authority只是raw声明及canonical阅读内容，不能升级成数据库/生产审核授权。

## 零DB、路径及恢复的验证限制

父类SimpleTestCase禁止全部alias业务查询；另在命令调用范围加BaseDB连接/游标tripwire及网络/writer guards，worker本身PG16基础查询在测试前的正式执行器内，不能算command查询。子进程使用sys.executable、固定本仓库manage.py和30秒timeout，guard安装在django.setup之前；dotenv禁读，marker报告setup完成、alias与trip计数。helper/writer guards禁止网络runner、source client fetch、A032 apply、race writer和自动publish；不patch adapter/H02/normalizer/workbook成功结果。

路径负向是定向symlink/覆盖/有界输入测试；check-then-open race需要将来实现时核sameFD/dirfd/O_NOFOLLOW代码，不能仅由symlink测试声称完整TOCTOU证明。下游失败、半成品清理和重投不会提升到写入幂等。无模型迁移/事务/celery/部署行为；原A03225方法不重复列成新增，后续回归仅由ROOT/C按实际依赖选择。

## 最小 RED 申请

申请**仅第1个ID一次**，现有runner profile `django`：Django setup/实际adapter校验与normalizer/model enum导入、openpyxl/workbook均需正式Django环境；SimpleTestCase databases=set不建业务fixture库，但官方worker仍初始化隔离PG并查PG16版本，这是基础设施，不能跳到宿主Python或私有runner。新模块未改catalog，ROOT/C可绑定官方精确batch计划，不能用unknown空集。

拟复用既有官方镜像 `sha256:fcf8cdaf63af51b1b8a6e30e3d2fdf871d127c3c1461bfd00c9fc6d610eab905`、八既有controls（run_test_plan/test_plan_worker/run_bounded_stable_tests、git_input/core、entrypoint/Dockerfile/requirements），必须ROOT重新核绑定。1container/network none/2CPU/4GiB/256PID/tmpfs3GiB/nonroot10001/ROsource/control/NNP/cap-drop ALL；600秒总窗含60秒cleanup、540秒止测。第一ID无子进程，预期不超过普通Django窗口；后续子进程每个<=30秒，正式组由ROOT另分配。禁build/pull/newdriver/hostPG/实网，owner/FD锁/heartbeat/source SHA/image/actual IDs/rawlog/lifecycle/cleanup/PID和receipt证据沿用官方机制，未allocation不启动。

首例须实际preflight成功+命令正常not_implemented→prepared assertion failure，1 failure/0 error；其他结果先排技术原因，不把helper/import/timeout异常标RED。RED后才能在同一已审范围实施GREEN，原独立测试的断言不因方便而放宽。A034/A035候选冻结。
