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
