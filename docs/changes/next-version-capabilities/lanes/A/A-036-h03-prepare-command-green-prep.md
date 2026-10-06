# A036：prepare-only 命令实现与六例窗口申请

任务 `A036-GREEN-IMPLEMENT-PREP-001`，已审A035方案 `72f82102409bd9d7c6e200fb57a565ed9d23059b`；ROOT已验收固定测试/stub `ef72bcab9004350886066391242ea9e3e344729a` 的首个有效业务RED。原run只执行唯一正向ID，真实adapter/H02/canonical normalizer/真实workbook build+readback前置成功后，正常command stub在not_implemented!=prepared失败，1 failure/0 error/skip、lifecycle complete。runtime `/Users/mentianlu/.codex/runtime/a036-first-one-red-window-001` receipt SHA `9e700f6b395a0deb7c0c26c49b3e605eb47daca35a1c7525c9c8818ad0f0e538`，12 seals；PG仅正式worker基础探测，owner61034/runner61046及组gone、flockfree/Docker0/23source指纹不变，已释放。其他五方法此前未运行。

## 本片实现边界

仅把本卡新 `management/commands/horse_basic_profile_from_cache.py` stub替换为prepare-only；新增本A报告。原六方法/CLI bootstrap/fixture/test_cases与RED逐bytes相同，无测试技术修复、无放宽原断言。A032/A034/shared writer/adapter/H01/H02/normalizer/workbook/models/settings/migrations/catalog/B/C不改。独立A036树，A03572/A034a19冻结。既有授权覆盖本地实现；G2/G3无执行动作，门禁仅引用根AGENTS.md。

1. packet与原cache各有独立CLI expected SHA；同一个打开的普通file FD有界读取和hash，不按名称重开。输入root从`/`逐组件O_DIRECTORY/O_NOFOLLOW，根/相对文件/父目录拒symlink、..、绝对相对混用、控制字符和非普通file，O_NONBLOCK避免FIFO阻塞。两个输入均<=128KiB；packet duplicate keys/NaN/Infinity/浮点/深度>32拒绝，严格字段和UTC baseline，仅producer快照，不验证数据库当前状态。
2. 延迟调用现有真实 `adapt_hkjc_source_cache` → `plan_cache_reuse` →原香港canonical normalizer。唯一单profile已有/私有unpublished、唯一reusable候选/版本/ref，身份/过期/冲突/partial不能回退；候选源原bytes保留，不造source client或网络runner。canonical保持原raw/count/authority声明，仅加reviewed=False，声明不升级成真实来源/人工审核授权。
3. `manifest.json`是h03_local_pending_preview/read_only/local_pending_review，含独立packet/source SHA、H02 digest、候选幂等key/version/baseline及阅读horse索引；无reviewed_input_sha/approved batch/reviewer/生产authority/release审批。CSV取原_review_row、审批列空，字符串独立Excel-safe；JSONL取原_jsonl_bytes/serializer，canonical真实值不被显示转义修改。
4. 显式output-root必须当前UID/0700，input/output两根分离；安全root/parent FD下mkdir排他创建全新0700目录，存在即output_exists、不覆盖。文件0600独占临时名→同目录rename/fsync。整个目录不是数据库式原子提交：完成前是私人中间产物，发生失败仅清自己文件，不报告prepared；不以文件存在认定完成。FD经系统`/proc/self/fd`或`/dev/fd`的inode/dev复核桥接，原workbook读取/写入始终落到持有目录，拒不支持的桥接环境。workbook `.tmp`预建0600，不改进程全局umask；实际原函数keyword调用/原temp→replace、最终regular-file/0600及目录归属复核。
5. 下游IO失败固定artifact_build_failed；含builder final rename后异常的已知目标也在清理集合，清理只用持有dirfd/本卡声明文件，核同一目录inode后rmdir，不递归清用户路径、不删意外他人文件。已有输出重投固定拒绝，不输出applied/服务写入成功。stdout一行JSON转义控制字符、七字段/prepare实际状态/固定原因码/未审产物路径；不会打印原件全文或异常repr。
6. 正常Django command入口、不注册apply/commit，requires_system_checks=[]/requires_migrations_checks=False，无connection/query/写service导入。启动前零DB的真实CLI测试覆盖django.setup/import/全部alias并毒化普通和production-style DB配置；工作簿必须真实创建/readback，不用mock成功结果。此条是待实测目标，不把静态无query或首RED说成六例GREEN。

## 已做静态检查

command AST解析；原六IDs/源码、CLI bootstrap、fixture相对RED字节不变；shared和八controls固定bytes；命令无DB/writer/publish/networkrunner调用或apply参数；安全FD/大小/深度/明确产物/原workbook消费点静态核对；git diff --check。未运行任何helper/command/workbook/业务测试，本轮无Django import、DB/PG/容器。正式文档suite与正式catalog/core未运行、不标PASS。修改范围仅新command+本报告。

## 首完整六例申请

申请test_cases中原**六精确canonical方法**一次，官方profile django，固定新候选SHA/tree与test/fixture/8control指纹绑定；完整ID与resource request见 `/Users/mentianlu/.codex/runtime/a036-h03-prepare-command-green-prep/request.json`。第一正向已有有效RED，不重复其stub失败；其他五首次真实运行，不预报结果。零DB的SimpleTestCase仍走官方worker/隔离PG16基础探测，不改collector/catalog、不宿主私跑。

拟复用原镜像 `sha256:fcf8cdaf63af51b1b8a6e30e3d2fdf871d127c3c1461bfd00c9fc6d610eab905`/八controls，ROOT重新核绑定；1container/network-none/2CPU/4GiB/256PID/tmpfs3GiB/nonroot10001/ROsource+controls+root/capdropALL/NNP，600秒含60cleanup、540止测，CLI child每个timeout30秒。新签名/测试tree/source/实际ID/rawlog/lifecycle/inspect/owner-heartbeat-FD锁/PID容器释放证据封存。没有allocation不得启动；若import/fixture/CLI环境错误，先如实记录技术失败，不改业务断言或增apply。

六例全部GREEN后才向ROOT/C提出按实际影响的精确旧adapter/H02/normalizer/workbook回归，不复写原A03225或默认扩大全模块；随后独立review，仍不代表发布或真实资料/完整H03/apply闭环。本A固定候选后停待ROOT分配。

## 六例真实 GREEN 与交接（docs-only）

`A036-FIRST-SIX-GREEN-WINDOW-001` 固定 `6d2b7d152d52179bcf5e976c6468319753c9488d` / tree `b4a18f462c5326c4e1178ea445610b4973f23743`，原六canonical实际列表与批准请求顺序/集合/数量一致，6/6 PASS、0 failure/error/skip/expected/unexpected、lifecycle complete/exit0。真实命令七字段/JSONL/未审CSV/真实workbook及setup前CLI全alias零DB、写参数拒绝、摘要/身份/新鲜度/路径/严格JSON/显示转义/IO故障清理断言通过。原runner未逐个打印成功child/subcase receipt，细分结论依据固定源码断言契约加完整方法零error结果；子例不增加canonical数量。没有测试hostile同UID并发文件系统竞态或post-rename builder异常，不把代码设计称这些情形已实测。

runtime `/Users/mentianlu/.codex/runtime/a036-first-six-green-window-001`，green-receipt SHA `c441be8e9f1b4b01680b0a213c12082c69f99cae24d8f0abd82012da8b3d1915` / 12 seals；worker12.068秒/总窗24.013秒，owner74639/runner74650及runner组gone、FDflock重取、Docker0，24source/control唯一指纹与fixedGit前后一致，资源实际释放。ROOT已验收局部六GREEN。只局部证据，不代formal catalog/core/full、真实来源验收或独立review。此回写仅本A报告，command/tests/fixture/shared/八controls与受测6d2逐bytes相同；tested→final docs-only映射封存在handoff runtime的git-state/receipt，不能把最终文档SHA冒称原受测SHA。

## 最小直接影响旧回归 proposal

建议只选下列**三个已有方法**一次，均实际类内直接定义；workbook类虽然继承prepare测试基类，按精确method ID选择，不展开父类或整模块。三个仍待ROOT/R选择与独立allocation，本卡未执行：

| 精确 canonical ID | 直接影响理由 |
| --- | --- |
| `stable.test_p0_horse_completion_batch.P0HorseBatchReviewWorkbookTests.test_workbook_sheets_and_exception_sampling` | 首次将新入口接到原build_batch_review_workbook；核旧阅读消费者sheet/摘要/exception接口，没有改变原batch审批入口 |
| `stable.test_p0_horse_completion_adapters.P0HorseCompletionCareerPayloadTests.test_unlinked_ordinary_races_stay_unlinked_and_count_mismatch_blocks_completion` | canonical阅读中普通赛绩必须继续event/result None，count mismatch仍partial/gap，不把预览当赛事关联或来源完整性升级 |
| `stable.test_horse_cache_reuse.CacheReuseTests.test_fresh_at_boundary_reuses_without_publication_claim` | 已有H02 reusable新鲜度边界及不声明公开状态；与命令新的安全文件I/O分开检查原合同 |

IDs、每项理由、真实源码文件SHA、method AST SHA和声明行见 `/Users/mentianlu/.codex/runtime/a036-six-green-handoff/regression-proposal.json`，profile建议django；workbook方法的既有setup需要隔离测试DB，所以不能仅因其他方法无DB而私跑宿主Python。未改catalog，formal core要求由ROOT/C保留。

**零额外旧回归也有明确技术依据，交ROOT/R裁定**：全部共享reader/adapter/H02/normalizer/serializer bytes未变，新六例已真实调用它们并核zeroDB/CSV与workbook公式安全/故障清理；command没有改变共享settings/umask/global contracts，不写profile/race/binding/publication，旧A032/A034写入口不受新caller影响。因此三个proposal是消费接口附加检查，不声称这些旧方法此前在本A036受测，也不机械重跑A03225/A03423。针对直接batch/adapters测试文件未找到旧独立CSV公式安全方法，已由A036第六例对原serializer加显示转义及真实workbook覆盖；不拿full reviewed artifact writer或production approval pipeline凑CSV回归。

## 可见示例、实际临时产物位置与如何查看

六例真实生成的产物在官方容器内 `/tmp/a036-synthetic-<随机后缀>/output/pending/`，CLI方法还生成同根 `ordinary/`、`production_style/`。每个方法独立TemporaryDirectory；方法cleanup已删除目录、容器已销毁。原log没有保存随机后缀或导出XLSX，**当前runtime只有raw结果/断言/来源指纹，没有可重新打开的实测review.xlsx**；不能把不存在的旧临时路径当交付文件。

本次docs/runtime静态准备了原受测fixture的逐bytes副本和原测试snapshot常量生成的packet（没有执行测试/helper/command/workbook），供后续获分配的受控环境复现。输入位于 `/Users/mentianlu/.codex/runtime/a036-six-green-handoff/example-input/`，空私人output-root位于同runtime `example-output/`，两者0700/文件0600；`example-manifest.json`明确STATIC_SYNTHETIC_INPUT_ONLY并封存来源/test/packet SHA。合成原件 source SHA `2ba3faa4706c64f4da1e8c0967713d51cc5cc776264cfccbc317e4638acec7bb`，packet SHA `111d004d7c886300ceb26c2445fd023e0e6ad4ceaab875c74ee73b1c858dbe26`。这两个是固定仓库合成输入绑定，不是现场真实来源/人工reviewed批准。

下面是**真实命令签名及该静态输入的完整示例，未在本卡执行**。从具备现有Django/openpyxl依赖的固定仓库 `server/`目录运行；在下一官方Linux分配环境中须先把这两组本地目录放入显式允许根，并把两个root绝对路径对应替换，不能让容器读取宿主凭据/其他目录，也不能把宿主系统Python当正式执行器替代。

```sh
python manage.py horse_basic_profile_from_cache \
  --input-root /Users/mentianlu/.codex/runtime/a036-six-green-handoff/example-input \
  --input packet.json \
  --expected-input-sha256 111d004d7c886300ceb26c2445fd023e0e6ad4ceaab875c74ee73b1c858dbe26 \
  --expected-source-sha256 2ba3faa4706c64f4da1e8c0967713d51cc5cc776264cfccbc317e4638acec7bb \
  --output-root /Users/mentianlu/.codex/runtime/a036-six-green-handoff/example-output \
  --output-dir pending
```

成功才打印JSON `status=prepared/reason=local_pending_review/reviewed=false`、七字段及artifact_dir。七字段来自原fixture：country AUS、sex gelding、color brown、birth_date 2020-09-14、owner_name Hong Kong Owner、trainer_name Hong Kong Trainer、breeder_name Hong Kong Breeder；这些是原测试期望值，不是本卡新增运行结果。实际返回的artifact_dir下打开 `review.xlsx` 查看“汇总/中国香港/异常抽样”完整性/来源/异常摘要；看 `combined_candidates.jsonl` 查看七字段、原canonical/raw记录；看 `review.csv`确认reviewed=False/decision空；`manifest.json`查看双输入SHA/H02候选证据。工作簿不展示逐条赛绩/七字段明细，预览不能用作production artifact批准，existing目录重投固定output_exists而非applied。

此卡只docs/runtime，无测试/PG/容器/网络/实网新样本/DB写/资源占用。固定后交ROOT选择旧回归或零额外路径，原R代码审核由ROOT派，本A不启新工作或宣称review通过。
