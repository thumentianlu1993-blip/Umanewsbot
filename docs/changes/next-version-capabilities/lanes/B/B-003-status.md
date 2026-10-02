# B-003 转存wrapper/verifier状态

日期：2026-10-03，Asia/Shanghai。父候选15b293ce已由协调者转述原R@5ee68b5c APPROVED：B002三P2 CLOSED，transfer方案APPROVED，仅本地实现阶段。
本次固定SHA由阶段消息绑定；新代码尚待原R review。根AGENTS.md仍为唯一门禁来源。

## 已完成

- 新增scripts/f02_transfer.py：独立host verifier、capsule/self SHA、metadata/content完整来源链与计数预算校验；private regular/no links、固定文件allowlist、0600/0700、无正文输出。
- 注入probe/copy编排；源承诺先落盘，copy前后身份/hash校验；source_lost的完整/部分包分别处理；unknown不盲copy；same-package幂等、不同或损坏包冲突不覆盖。
- 独占OS flock自动释放并留owner/liveness信息；有界空间预检；自身验证SIGALRM wall deadline，adapter copy/probe必须自行强制预算与回收。
- file/dir fsync与原子final/transfer.complete；receipt失败保留final并恢复。host_verified保持R未收到；R独立认证回执API缺认证或错绑定拒绝，独立R.received。
- 23个新离线test methods（内部含多组故障/subtest），所有producer/source/host是合成临时目录、动作注入fake；原exporter21例一起回归，总44/44 PASS（约1.14秒）。
- mapping proposal增加wrapper/tests的精确behavior domain、python profile；proposal自身同时映射export/transfer两域，既有export脚本及测试fixture新增transfer依赖域。未改共享rules/catalog/runner，交协调者统一应用。
- 已审exporter字节与15b293ce完全相同。

## RED/GREEN证据

测试设计见同目录test_cases.md T01–T10，映射已审transfer方案；不新增DB/迁移/Celery语义。

1. verifier最小RED：`python3 -m unittest scripts.tests.test_f02_transfer.VerifierTests.test_manifest_hash_files_receipt_counts_and_source_rejected`，exit1，8组反例均 `TransferError not raised`；hash/文件/身份/数量缺失行为真实失败。随后VerifierTests 5/5 GREEN。
2. transfer最小RED：`python3 -m unittest scripts.tests.test_f02_transfer.TransferTests.test_interrupted_partial_not_recopied_and_complete_copy_ack_loss_recovers`，exit1，partial/complete均not_implemented!=transfer_unknown；实现后TransferTests 7/7 GREEN。
3. delivery/CLI RED：DeliveryAndCLITests，exit1，缺R认证仍未拒绝、CLI故障仍返回0；mapping改为get后独立RED明确 `module:scripts.tests.test_f02_transfer not found in []`。随后同组3/3 GREEN。
4. capture状态RED：AdditionalFailureTests.test_capture_unknown_and_transport_exception_redacted，exit1，transfer_unknown!=capture_unknown；修正后GREEN。额外timer测试为实现后回归证据，不冒称独立RED。
5. 最终 `python3 -m unittest scripts.tests.test_f02_transfer scripts.tests.test_f02_readonly_export` exit0，44/44 PASS；workflow contract PASS，4契约tests PASS，diff check PASS。

初次fixture因macOS临时路径祖先symlink触发exporter拒绝、mapping的初次KeyError均属fixture/断言问题，不计RED；修正为绝对resolve合成路径与明确断言后才记上述有效RED。
可捕获mutation：移除hash/身份/数量校验、放宽links/权限/预算、unknown后copy、忽略post漂移、final覆盖、receipt失败误报成功、producer自签R、漏fixture domain/profile、timer超时未恢复handler。

## 待核 / 限制

- 新增代码、custodian认证接口及包布局待原R代码review；真实adapter未接入，callback超时合同不等于现场网络已验证。
- 独立R认证材料未创建/绑定；没有凭据/密钥写仓库、artifact或输出，合成测试key不用于生产。
- 正式capsule/host路径/owner/空间/执行Python环境/transport argv仍待协调者绑定，原runtime模板持续失效。
- 无Linux正式delivery/真实DB查询/生产转存/R收包/新增真实样本；不能把local GREEN称发布或F02完成。
- 最近周额度实时剩余5%，没有子代理/模型CLI或后台长进程。本线不合并、不部署。
