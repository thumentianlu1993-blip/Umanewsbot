# 修复设计

## 逐组处理

|组|数量|问题与处理|
|---|---:|---|
|1|1|马匹快照升级回执 target_type 长于 32；使用短且明确的升级类型，不扩字段，不改原收据查找和事务边界。验证一次升级、重放和无半成品。|
|2|5|历史首批验收误遍历新增澳洲枚举；明确 Japan/HK/UK/France/US 五地区常量，仍为 45 个目标，新增枚举不扩大老批次。|
|3|5|TRA 名单来源合同不匹配；最小复现定位具体拒绝条件。若 fixture 缺现有合同属性则补合法 fixture；若规范化/持久化丢字段则修该点。来源身份、名单摘要、registry 摘要、允许字段仍严格校验，补直接负例。|
|4|1|PG 耦合马号类借用了 setUp 却丢了类装饰器；显式复制所需 override_settings，仍验证同号不同来源马不会覆盖。|
|5|1|只读审计误认为 PG 不支持索引检查；按数据库 vendor 断言，同时保持业务表无写入。|
|6|1|翻译异常文案过期；精确断言当前占位符拒绝语义，不能只断言任意异常。|
|7|1|测试末段用真实今天判断已固定日期策略；全链统一固定 NOW，保留独立过期拒绝用例。|
|8|1|测试外部马 ID 超长；缩短合成 ID，保留同一文章中仅确认出现位置被改写的断言。|
|9|1|并发 stub 未接 responses 参数；透传现有参数，保留真实 PG 两连接、一应用一重放断言。|
|10|9|测试依赖未入库 tmp runner；迁往正式工具，见下方覆盖映射，测试不得仍依赖个人目录。|
|11|2|fixture 依赖 cwd；从 __file__ 或 BASE_DIR 定位，仓库根和 server 下均可执行。|
|12|1|子进程动态装载 runner 丢同目录模块路径；显式加入正式 tools 目录，仍用真实子进程验证共享 host 锁和间隔。|
|13|3|通过非法写法造漂移，提前触发身份/不可变/外键约束；用合法业务入口造同义漂移，禁止禁用 trigger、约束或保护。|
|14|3|年份与日期不一致；fixture 使用同一日期来源；查询数仍按现有预算验证，不为通过任意上调。|
|15|3|格式用例触发当年审批门槛；格式/五地区样例用历史年，当前年安全门槛由现有 descriptor 正反例覆盖。|
|16|1|迁移测试把旧 0068/0070 当可发布状态；重复参数解析与当前 0078/0079 状态检查分层测试，不恢复旧 schema 发布路径。|
|17|3|地区筛选已退役，仍期待 200 过滤结果；断言规范化 301、保留其他查询参数、全站文章不重复分页。|
|18|2|网页地区标签已退役；验证网页不泄露标签且关联数据仍在，QQ 的主/关联顺序继续检查。|
|19|4|马匹资料页/索引缺少公开提示；复用模型公开标签，未完整统一“资料补全中”，完整显示“完整马匹资料”，无中文名提示“中文译名待补”，不展示内部空壳/基础等级。|
|20|1|部署 wrapper 增加只读 nginx -t；精确允许这个命令且仍要求 --rm/--no-deps，保留锁合同。|
|21|1|持久目录引入可配置根；验证默认值、变量及容器目标/rw 语义，不要求过期字面量。|

## 临时脚本测试迁移

原 9 项的旧 ID 全部保留在 inventory，替代 ID 实施时逐项填写，不以删除抵消失败：

- 三项失败 URL 重试审计：直接运行正式 `historical_race_calendar_cache_state.py` 的
  begin/finish，验证成功 URL 不重抓、失败 URL 重试、原尝试记录保留、最终完整集合。
- TOBA 网络保护：测试正式 cache 工具的三重网络开关及 before_network_request / write_source_cache 的预算、间隔、磁盘限制，
  mock fetch，不运行 Docker/真实请求。原临时 Docker 命令本身已无可维护入口，明确不声称仍覆盖该 wrapper。
- 两项 parse 身份重用/重建：测试正式 prepare 工具对 selection/catalog/request/cache 摘要篡改的拒绝，
  以及生成产物 manifest 的实际身份绑定；旧 wrapper 的自动归档不再作为现存功能。
- classified 旧 cutoff：正式 classify 结果绑定实际输入与 cutoff，变化必须生成不同身份/分类结果。
- HK 两阶段同 cutoff：正式 build 与 prepare 的 request-manifest/cutoff 匹配正例及不一致拒绝。
- HK 旧 bootstrap：正式 source catalog 校验拒绝缺失 cutoff 适用的覆盖策略，保留旧输入不修改；
  明确不宣称已不存在的自动归档链得到复原。

迁移会缩小对已丢失 wrapper 的宣称，不能缩小现存正式工具的安全边界。若正式工具缺少上述
保护，先建立 RED 再补最小校验；不新增自动抓取或自动入库入口。

## 有界验证与 CI

版本化清单映射原 50 项到修复后 ID；runner 在 setup_databases 前展开并拒绝重复、缺失或 >200 项。
每批输出清单与 JSON（SHA、时间、环境、失败、跳过、已执行名称）。本任务失败项不得跳过。
使用专用本地 PG 临时实例和合成凭据；清空继承环境，禁用 dotenv，阻断外部 socket，
Celery memory/eager，cache 本地，邮件 locmem。Linux CI 再验证平台敏感与发布合同。

原 workflow 增加 workflow_dispatch validation_scope=full/known-failures，默认 full；
known-failures 仅运行本次分组与既有发布合同，明确跳过全量和基线比较。PR 使用 [skip ci]
防止原自动全量，随后手动触发绑定同一分支 SHA 的有界工作流；不能伪造通过或忽略必须检查。
必要检查不支持本入口时先解决配置/证据问题，不运行用户禁止的全量。

不把 50 项修复通过解释为所有 5682 项重新验证通过。CI 记录只称有界回归。

## 第一轮独立审核修订：第10组明确映射

正式工具均位于 runtime/tools；替代测试在 stable.test_historical_calendar_runner_helpers 中。
不建立旧产物复用入口：prepare_calendar_inputs 每次重新解析，atomic_publish_directory 拒绝已有输出目录。
原 tool identity 保护改为验证“解析器改变时新输出使用新解析结果、旧输出拒绝覆盖且保持字节不变”，
不能把只检查输入摘要称为解析器身份验证。

|旧测试后缀|新测试后缀|正式入口与关键断言|
|---|---|---|
|parse_artifact_reuse_requires_exact_selection_catalog_and_tool_identity|prepare_recomputes_with_current_parser_and_binds_inputs|prepare_historical_race_calendar_inputs.prepare_calendar_inputs；同输入新输出使用当前 parser，manifest 绑定输入|
|toba_fetch_uses_guarded_docker_network_stage|cache_cli_enforces_network_budget_interval_and_disk|cache_historical_race_date_sources.main → before_network_request → write_source_cache；只替换最终 HTTP 响应，三开关缺失不请求；预算耗尽不请求；实际小间隔记录；磁盘不足没有成功缓存|
|standard_cache_retries_only_failed_urls_and_preserves_attempt_audit|standard_cache_retry_preserves_success_and_attempts|historical_race_calendar_cache_state.begin_cache_retry/finish_cache_retry；成功和失败 URL 守恒|
|toba_cache_retries_failed_url_and_preserves_attempt_audit|toba_cache_retry_preserves_failed_attempts|同上；TOBA 失败后成功，旧失败审计仍在|
|parse_rebuilds_successful_artifact_without_current_execution_identity|prepare_refuses_existing_output_without_modifying_it|prepare_calendar_inputs → atomic_publish_directory；旧目录无 execution identity 仍明确拒绝复用，原文件不变|
|classified_reuse_rejects_old_cutoff_identity|classifier_recomputes_for_new_cutoff|classify_current_year_race_due_checks.classify_due_checks；同输入两个 cutoff 新输出，结果与 manifest 随 cutoff 变化，旧输出不改|
|partial_cache_retries_failed_url_and_preserves_attempt_audit|partial_cache_retry_failure_remains_auditable|begin_cache_retry/finish_cache_retry；再次失败仍在最终账本和摘要，成功 URL 不重试|
|hong_kong_runner_binds_same_cutoff_and_request_manifest_to_both_stages|hkjc_request_and_prepare_require_identical_cutoff|build_historical_race_calendar_requests.build_calendar_requests、prepare_calendar_inputs；一致通过，不一致拒绝无输出|
|hong_kong_runner_archives_and_rebuilds_pre_cutoff_bootstrap|hkjc_pre_cutoff_catalog_is_rejected_without_mutation|historical_race_calendar_common.load_catalog/hkjc_coverage_policy 经正式 prepare；旧无 coverage catalog 拒绝，输入原字节保留|

正式网络测试不得 mock budget/cache 保护函数；为稳定复现磁盘边界可替换 disk_usage 的测量值，
保护判断仍真实执行。原 Docker wrapper 和自动归档已不存在，不恢复也不声称覆盖，正式入口安全失败显式验收。

## 实施定位补充

第3组已用隔离PG复现：source.valid_until 为 2026-09-27，reconcile 却读取真实日期；
统一测试时钟后五项通过，不改生产来源合同。第13组 current revision 漂移实际缺少同步推进
next_result_revision_no，修复合法版本计数而非添加无关来源字段。部署命令清单还包括两项
现存只读 schema preflight wrapper，按精确命令断言补齐。

最终有界回归清单见 regression_batches.json：501项，四批122/141/147/91。
包含额外33项名单字段/来源拒绝回归；不运行无改动关联的 opt-in 1250目标性能压力用例，
它保留原测试定义，不被计入本次覆盖或通过数。所有入选用例必须零跳过。
