# B108 Boundary5 实际 PG 失败返修

状态：固定候选技术修复及本地验证完成；原 R 独立代码复审、新 SHA 的 exact2/Boundary5 实际 PG 均待 ROOT。旧 `8dff311ccca7a6bf2de2e1c43d8f01f771f6f950` 的 accepted exact2 只适用于旧对象，本次不继承实际 PG 通过。新提交/tree/源码和证据 hash 在专用 runtime prepare 固定。

任务 `B108-BOUNDARY5-PG-FAILURE-REPAIR-001`，ROOT 另确认最小 `terms.py` producer 修复范围。本次除两 PG 测试 fixture 外，确实含生产值序列化技术修复；没有改业务许可、预算或产品边界。

## 原失败与原因

C093 实际包 `/Users/mentianlu/.codex/runtime/b107-boundary5-host-binding-001`，seal `e7da5639d5e8f9cbb9b681d7b862727dabcab3a5d1a2b6619e11666338e10209`，五方法 0 FAIL / 3 ERROR / 0 SKIP、native exit1/supervisor exit2。日志 SHA `57d85fc83304231b5515883a90f10c78e541498075def619107f576064c891d0`，结果 JSON SHA `248c8d0e13d3e08883e9537aa8309e7e738412289a0be8b37fb6c603b354631e`。ROOT closeout SHA `b88a89a8d1b5e279e29c4c97f88a0e2f25c23e140f4d80b76f473f5f2325b629`，记录 runner/container/owner 消失、FD重获和sealed不变；本线程仅核字节，没有重新操作资源。

1. version 负例直接调用 guarded QuerySet.update；mapping 负例直接调用 guarded step.save。原 ORM writer 正确拒绝普通改账，两个 fixture 在待测 fence 前就 ERROR。改用文件内原有 `models.QuerySet.update(single_pk_queryset, ...)` 的测试单行破坏机制，并要求实际命中1行。重哈希后的 mapping 仍需拒绝 `step_result_invalid`，不合法 version 拒绝 `step_version_changed`。普通 writer 守卫原字节不动，read slot/request/零材料查询断言保持。
2. 删除分支日志显示 provider实际返回长度10/140/11，usage 已由独立控制连接真实对账；随后 consumer model_refused、blocked_fence、无 checkpoint。因此不能当作 provider placeholder/质量拒绝，也不能只换响应掩盖。
3. 生产链 `translation.py:translate` 构造 `recognized_horse_names = serialize_recognized_horse_names(recognized_horses)`；实际 horse resolver 生成 `RecognizedHorseName.matched_span=(start,end)`。原 serializer `asdict()` 保留 tuple。`_save_registered_checkpoint` 的首个 `business_metadata(result.metadata)` 进入原 `_checkpoint_json`，精确 builtin codec 拒绝 tuple，抛 `TranslationCheckpointError(ValueError)`；consumer 映射为 model_refused。人物-only exact2 没有马元数据，所以旧通过不能覆盖。

`actual-metadata-old-red.log` 用实际 SQLite Article/ExternalHorseAlias、原 capture/decode/recognized-horse producer→serializer→business_metadata 复现同一严格拒绝堆栈，0 FAIL / 1 ERROR：最终错误是 `checkpoint value type`，不是 fixture 早停。该小路径不声称 PG consumer/provider 运行。首次开发传了datetime而非ISO read时间的 fixture ERROR另存，不作为目标失败。旧 C093 没有记录 checkpoint 原异常，本次依据生产代码和实际同 producer 链明确 tuple 缺口；新 PG 仍需证明原删除 consumer 完整闭合。

## 最小修复与兼容性

仅 `terms.serialize_recognized_horse_names` 在 `asdict()` 之后，对固定 `matched_span` 的原生 tuple 转 list。其他字段不变；内部 dataclass tuple 不变，既有 list/None 保留，空tuple成为空JSON数组。没有通用任意tuple洗白，没有放宽strict checkpoint、ORM writer、placeholder/长度质量门禁、permissions/admission/cost reconciliation。

调用点检查：生产 `translation.py` 的 metadata 和 `validation.py` 的 details 都用该 serializer；其余是 term-gate batch对照测试。没有生产调用点把序列化后的span当作tuple键或依赖tuple API。普通JSON原本会持久化为数组，本次在producer就明确数组；在实际 ordinary/strict metadata 对照中验证，未只靠 json.dumps 推断兼容。

两 PG fixture之外的测试：

- 实际冻结马实体 producer→strict metadata GREEN，span=[0,12]，内部tuple保留，同时直接strict tuple负例仍拒绝。
- 实际人物-only冻结解析，recognized=[]，strict metadata保持原输出。
- 原 serializer ordinary 边界测试改为验证producer已有list并严格/普通两边输出相等；新增 empty/None/全部其他字段不变、原对象不变。
- 原 finite-json、invalid types/cycle/nonfinite、reserved keys、深度/size、strict tuple拒绝等用例保留；原B107增长前/40归并/映射/材料等回归保持。

本地 `sqlite-metadata-final.log`：原39 + 两项实际材料/metadata测试 + 9项 BusinessMetadataBoundaryTests，共50 PASS；使用已有venv、DB_ENGINE=sqlite、独立内存DB、-B，无PG backend伪装。English context17包含真实validation入口，可应用的serializer兼容回归已实际执行；未称全terms通过。

## 冻结与下一步

专用 runtime `/Users/mentianlu/.codex/runtime/b108-boundary5-pg-repair-001` 保存准确返修diff、原失败hash绑定、RED/GREEN日志、静态检查、新exact2与Boundary5计划。测试对象与计划绑定新SHA/tree；未collect/PG/Docker/分配资源/外网/生产。

原B107、C092 accepted exact2、C093失败、B106 RED和原R包不变。原R代码复审后由ROOT在新host包实际复验，不能用本地50 PASS替代PG。六组/R01/R02、checkpoint免费apply/final重投、legacy/corebudget/fullterms、PG锁并发及high-risk正式CI全部保留；没有降级零材料SELECT、同step/完整删除或实际provider→对账→终态要求。
