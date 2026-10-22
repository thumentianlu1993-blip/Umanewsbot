# B107 R01 字符串归并增长前收费返修

任务 `B107-R01-STRING-PRECHARGE-REPAIR-001`。完成批准合同内技术返修与本地验证，等待原 R 同上下文复审、ROOT PG；不代表 M03 完成或发布。父候选 `0e6d99e65b6367a98194c6546df74538d090c9ab` / tree `e767fac0f89b755a170b3da5a1ea6124b042b3dd`。新 commit/tree、文件和 evidence SHA 在新 runtime prepare 中绑定。

原 R `6e6405841ff869048f001d6fc88cb496854e16e1` 为 REVISE，仅一项 P2 R01。报告 SHA `b2a3e3a6ff31589ef2310b9eca8f0b239e6be41b5f72d925443abf347c4c48a6`；receipt SHA `09e06958c9fb1c4310a51cd19a0bd5e9a44d77a21368405060a7a0cebd04f54d`。问题是英文归并先 `capture_list(chain(...), budget)` 物化普通 collection，随后字符串 helper 才核独立 string 界；总账有界不能替代字符串增长前合同。

## 修复与收费语义

`terms.py` 中四类字符串字段 external_horse_ids/evidence/entity_evidence/conflict_flags 的生成、归并、复制，直接把 tuple/原列表/生成器/chain 传入原 `capture_strings` / `capture_unique_strings`，移除 43 处 `_make_entity` 参数或属性赋值中的普通 `capture_list` 预物化。涵盖英文 external 追加、formal 同 span 归并及 entity_evidence 复制，并一致处理日文与其他语言 `_make_entity` 参数。

helper 的实现语义保持：每个去重输入先 string 收费，重复输入也收费；唯一输出追加前仍 string 收费，seen 集合原 collection 收费；每字符串 list 64、累计 string1024/128KiB 和总账保持。移除了中间普通 list，因此没有该 list 的 collection 插入；没有把不存在的中间复制当作增长。未增加双账机制或改变原上限。`capture_budget=None` 仍返回原顺序原输出。拒绝不退款，不返回部分竞争者。

尝试额外对每个字符串输出统一收 collection 账的第一实现使原40同span用例在归并前超额（stage-01 保留）；该尝试已撤销。最终修复只移除预物化，不添加额外收费类别；原40实际 ORM 候选完整参加归并成1的检查通过，最终 receipt 8192 界仍独立。

## RED 与 GREEN 证据

专用 runtime `/Users/mentianlu/.codex/runtime/b107-string-precharge-repair-001`：

- `old-r-reproduction.log`：在未修复父候选上执行原 R 脚本，确实先消费65、插入65 collection，随后 read_terms_limit。原脚本及原 JSON 复制保存，原 R runtime 不改。
- `actual-english-old-red-final.log`：先新增真实 ORM-preloaded 英文路径测试，在旧实现跑两方法，8个 item/byte subtest FAIL、0 ERROR，重复 evidence 顺序对照 PASS。旧测试源码另存 `old-red-test-source.py`；更早 fixture 开发运行日志亦保留，不能把它们说成最终RED。两 Formal TermEntry 与两 ExternalHorseAlias 均真实入库，原 index、resolver、helper 全部实际执行；observer 仅在真实归并点设置边界预算并记录输入消费，未供应成功 resolution。
- `new-r-call-shape-result.json`：从修复后的真实英文 existing.external_horse_ids 赋值 AST 提取表达式执行65项输入；item1024/byte128KiB分别第一项拒绝，collection插入0、余64不消费。这是原R问题的新源码调用形状复现；原脚本硬编码旧嵌套模式，在新 helper 上仍会复制65，不能把不改调用表达式的旧脚本声称修复GREEN。
- `sqlite-final.log`：原20+17与新增2测试共39 PASS。新真实英文路径覆盖 existing external IDs、primary external IDs/evidence/entity_evidence/conflict_flags，分别耗尽item与byte，10组都消费1、collection growth0、目标字段不变。真实重复 evidence 输入 `strong_horse_context` 出现2次，收费spy观察3次（2输入+1唯一输出），顺序与 None 完整解析相等。
- `prior-resolver-equivalence.log`：d583原 terms 对照282 key集合等价与6组prior/current None/current budget完整解析等价通过；纯preloaded scalar，不代表registered业务或PG。第一次命令误写 settings module 的 invocation error 已保留，纠正为项目原 `app.settings` 后通过，没有新 settings 文件。

最后功能测试后只展开五条归并赋值的格式；静态 AST 等价核验与源码审计记录在 `static-checks.json`，行为未再变。最终计划按提交后新SHA/tree绑定。

## 继续挂账

六组/B105 R01/R02全部义务保持。原 exact2 GREEN、五条 PG boundary、PG Cast/Substr、slot/inflight/unknown、cached source/grant/deadline/version及read期间 fence、删除恢复、checkpoint免费apply/final重投、双消费者/锁后截止、legacy/corebudget/fullterms/high_risk正式CI仍待 ROOT 授权窗口。两个PG测试模块、step/consumer、decoder/loader和固定 controls 原字节不动。原 B107、B106实际RED及R材料只读保留。

新 runtime prepare/plan/boundary-plan 只做静态绑定，无 PG/Docker、collect、资源分配、生产/外网/付费调用。请原 R 在原上下文对固定新候选复审后交 ROOT 安排实际 PG。
