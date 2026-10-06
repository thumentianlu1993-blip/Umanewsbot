# B039：已验证结果检查点 RED 测试合同

状态：原14个方法保留，新增16个，共30个；首轮准确3项在ROOT专属PG窗取得真实业务RED，现实现与新增边界均尚未运行GREEN。依据B038已审方案a7d5a056；原R审批由ROOT反馈30f8ec70 APPROVED_PLAN_ONLY。RED准备时没有业务占位；现已按ROOT授权实现，但未取得GREEN证据。

## Fixture与首轮最小RED

新模块 stable.test_translation_result_checkpoint。继承既有B037 TranslationClaimFixture（只有fixture，无父类测试方法），使用现有article_for_retry、selector截获delay取得准确envelope、真实consume把run变executing；不发broker。mock clock固定NOW、provider结果替身、通知/send_mail/automation均patch。所有模块/符号已静态查存在；AST不是实际导入/DiscoverRunner或正常fixture成功证据，须ROOT窗口确认。生产service/models/tasks/settings未改。

首轮只3 IDs、单一官方django诊断batch，按固定SHA运行一次：

| 方法 | 当前未改业务代码应产生的目标失败 | 捕获mutation |
|---|---|---|
| TranslationResultCheckpointRedTests.test_validated_result_survives_exit_before_terminal_commit | mock provider返回完整已恢复中文后，在确切run.status=success的save抛测试专用BaseException；真实终态atomic回滚，run仍executing且缺完整checkpoint，assertIn失败 | 删除独立checkpoint提交；把checkpoint放入终态同一事务；只存metadata.raw或丢metadata |
| TranslationResultCheckpointRedTests.test_same_envelope_resumes_committed_result_without_provider | fixture直接写合法拟定checkpoint到确切executing run；现入口already_consumed跳过，translated=True断言失败 | 重投不恢复；重新调用provider/解析；恢复用raw代最终文本；unknownusage归零/丢审计；重复回调 |
| TranslationResultCheckpointRedTests.test_two_postgresql_replayers_commit_one_terminal_result | 两真实独立PG连接屏障后同envelope任务；基线两次skip，成功者数量0而非1 | 双成功或无成功；错误不原子fence；恢复调用provider；重复派发 |

首例崩溃用BaseException穿过现有except Exception，不模拟OS杀进程，不代表broker会重投。终态save拦截不依赖未来helper名字，基线存在且会走到，故不借缺import/signature当RED。第二/三例的checkpoint由测试直接seed，是未来持久合同输入，不声称基线已有写能力；回写必须走真实task/数据库，不能由fixture代实现。

并发仅第三例要求postgresql，非PG明确failure而非skip；最多主连接+2workers=3连接，一容器。Barrier(3)释放后真实两个backend PID，输出日志并断言两个独立PID、2个result、1translated/1skipped、run success、一次automation替身，finally关闭两worker连接、限时join，检查无残线程。此例证明两连接业务竞态，不冒锁等待或生产吞吐实测。首轮不执行超限大JSON子例。

## 后续边界（11方法，尚未执行，不承诺都应在基线上RED）

| 方法后缀 | 可检验边界/mutation |
|---|---|
| terminal_save_failure_keeps_checkpoint_for_later_local_resume | checkpoint先提交；终态run保存RuntimeError→article/run回滚，checkpoint保持；同envelope本地重投成功。删原子/把checkpoint同事务会失败 |
| resume_keeps_current_manual_fields_and_complete_metadata | 当前编辑body保护，translated_body用结果，完整metadata保持；不能重算术语或取raw |
| persisted_suppress_policy_cannot_be_enabled_by_replay_argument | 持久True、重投False仍派发0；禁止从任务新参数取策略 |
| persisted_allow_policy_is_not_replaced_by_replay_argument | 持久False、重投True按原策略登记一次回调；执行策略不被重投改参替换 |
| original_deadline_at_and_after_cutoff_cannot_resume_or_extend | 精确截止/之后两个subcases只skip且article/run/原deadline原样，provider0 |
| source_changed_cannot_resume_or_use_another_claim | 源字段更改，旧结果不可回写；前后文章字段/run快照不变 |
| old_checkpoint_cannot_resume_after_stale_recovery_and_new_claim | 真实stale/new claim后旧envelope不动新状态，不借latest run |
| invalid_checkpoint_never_falls_through_to_provider_or_mutates_rows | JSON可持久非法合同：错article/run/claim/source/deadline、版本/布尔冒int、空/非字符串正文、metadata/terms/tags形状、reserved keys、2MiB超限/深度34、坏container/hash；每次digest按内容重算以避免只测试hash拒绝；provider/回写/派发0 |
| unreconciled_usage_can_resume_locally_without_zero_cost_invention | 空/非账单repr/负token/末次token报告各自保留unreconciled，无cost=0字段，恢复零provider；末次数字不当整轮known |
| executing_without_checkpoint_still_skips_without_new_provider | 保留B037已消费无结果的fail-closed，不重新调用 |
| fresh_provider_metadata_cannot_supply_internal_checkpoint_keys | 首次执行的provider替身metadata注入reserved result key，不能当合法checkpoint或写正文、计失败/发通知；只返回明确skip |

边界里期限/源绑定等基线可能已PASS；这些是mutation防护与将来GREEN验收，不伪报全14RED。unknownusage子例重置同一fixture状态仅用于分别输入合法JSON审计，不是实际跨claim恢复/费用证据。异常/保留键都为正常Django可序列化fixture，不把PG拒绝NaN当目标RED；循环、非有限数等锁外编码输入案例后续在确定生产codec接口后补，当前不制造缺接口或DB编码error。

## 验证层与缺证

当前可做AST、符号存在、源指纹对照、git diff --check；不执行django.setup、collector、DB或manage.py test。首轮ROOT需先明确固定RED SHA/准确3 IDs及新窗口。基础设施/setup/fixture异常立即停止并报告，不记RED，不自行重跑。首轮结果回ROOT后才决定是否实施，不先实现GREEN。C034 collector独占资源，B不得复用。

现有B037锁等待跨原deadline 6子例证据不能证明新的checkpoint保存/恢复helper；将来GREEN前仍需新增这两阶段的真实行锁等待观察（article/run两锁、PG blocker）、原执行与恢复者交错、checkpoint写失败、普通/force兼容及现有回归，不能拿本次3RED代整片验证。完整预算/outbox、跨claim/术语版本复用、deadline后恢复、自动保证重投均不属本片。测试资源只用ROOT既有隔离runner控制及准确窗口；formal catalog/impact/full分母不改。

## 首轮实际结果

固定e44f0636、ROOT窗口B039-FIRST-THREE-RED-PG-WINDOW-001下原3方法一次执行，均在上表预期业务断言失败：checkpoint不存在、重投未translated、两连接成功数量0。3failures/0errors/0skips/complete/exit1；实际backend68/70，worker连接及线程均关闭，正常fixture与导入无错误。原日志、精确IDs和清理绑定独立red-receipt（SHA9e16f68579553345116e6feb58561906088717955736f5d16eca6bbf956a8851）。其余11方法尚无运行证据；没有实施或执行GREEN。

## B039-GREEN-IMPLEMENT-PREP-001 补齐断言

ROOT核三项真实RED/清理后授权实施；当前仍未取得新的测试窗，未运行GREEN。原e44f0636所有fixture/RED/边界class的AST逐字相同，只有新imports和以下16方法追加；原3RED反例及raw证据不修改。新codec接口形成后添加的测试属于边界验收，不借接口不存在制造RED，未声称已在旧代码失败。

| 新测试类 | 方法数与明确反例 |
|---|---|
| TranslationResultCheckpointFailureTests | 5：首次suppress=True终态退出后真实检查点恢复、重投False仍派发0；checkpoint独立save失败不得进provider失败计数、同消息重投provider0；原worker保存checkpoint后暂停让另一个真实PG连接恢复胜出，原worker仅skip且dispatch一次；late error不能覆盖已存成功checkpoint；不同摘要不能覆盖首份结果 |
| TranslationResultCheckpointLockDeadlineTests | 3方法/6subcases：保存、resume入口、resume终态三个阶段分别article/run锁；实际pg_stat_activity Lock及精确pg_blocking_pids owner后才推进固定clock到精确deadline或之后1秒；状态前后相同、claim_expired、provider分别1/0/0、零dispatch/notify；主连接观察不增加第三连接 |
| TranslationResultCheckpointCodecTests | 8 SimpleTestCase（无DB）：Unicode/canonical hash/独立snapshot/unknown报告；NaN/±Inf；dict/list循环；非内置类型/非字符串键/自定义hook；精确UTF-8编码字节2MiB及+1、不截断；深度32及33；timestamp/usage report漂移/假known/凭空cost；bool或int子类冒run_id |

新接口无外部调用：build/decode为严格JSON与TranslationResult重建；prepare复用锁后clock、claimed消费或executing读取；save独立atomic持久；finalize只接受checkpoint成功输入或旧错误终态，provider异常与本地写错误分开。新codec数据源是明确非法Python/JSON类型，不通过先写PG非法JSON求数据库编码错误；SimpleTestCase禁止DB。

拟准确受影响 **77 IDs**：新module30 +原B037 claim-fence25 + recovery22。原M01 mock19保留此前未受影响证据（translation.py/Responses/settings/factory/test未改，不调用新helper）；不是本轮复跑，也不降低formal/full分母。一个官方django诊断batch，max3PG（已有消费并发及新双恢复需主+两worker），新增锁等待与原worker竞争为2连接；单容器资源/控制保持。ROOT另给新窗前只AST/指纹/diff，不collector或DB。A034独占期间不竞争资源。

仍待：准确77在候选固定SHA上的GREEN、实际6锁观察/原worker竞争、同R独立review、ROOT/C formal catalog/impact/full。完整M02预算/outbox/自动恢复保证不由这些断言证明。
