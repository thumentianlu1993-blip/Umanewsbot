# 按改动范围测试启用证据

记录时间：2026-10-03 00:21，Asia/Shanghai。

[PR233](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/233)已合并为`d38727d5613abf58dd382535a7a3c11112064275`；候选`185a7d072e399576d35a53ddea4f94f136bb7228`，基线`fc1eed938beb8b431e0d4b37953f7599a40a72ce`，受验tree`bde1542bbb082b4f38441ecb1d31fc1d28970216`。
[CI37028610440](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/37028610440)成功，41批/6165项，6155通过、10项登记skip、零失败/错误，全部正常收尾。镜像`sha256:6d0715086ab41ea9247866c26f91be7cf168d8f0d619f80c09f8a65170f31100`。
10项skip包含8项真实缓存、1项真实镜像、1项root权限合同，登记复核期限2026-10-16；它们是明确覆盖缺口，不算执行通过。

仓库策略`IMPACT_TEST_POLICY=active`；main required check为`test-plan-gate`（GitHub Actions app15368），strict及enforce_admins为true。
手动校准不能满足GitHub的PR必需检查；合并前已原子替换为普通PR的`test-plan-gate`，真实PR检查及独立核验通过后才合并。整个过程未留下无required check的间隙。
此前主线没有传统保护/branch rules，策略变量不存在；原设置及精确发布包保存在协调者外置记录中。
无迁移、生产数据动作、服务重启或外部发送。回滚按受审CI revert恢复旧入口及原设置，不涉及业务数据恢复。

本记录仅修改Markdown，作为真实docs-only PR验收：应仅运行静态检查、0项业务测试、0个数据库测试容器，无旧PR全量入口。
结果以本记录PR的真实CI与候选外交付回执为准；不使用skip-ci规避验证。代表性业务小迭代耗时及token统计仍需积累。

## 候选外可信交付回执

核验器来自独立审核绑定的Git对象，运行在候选目录外；从本次CI镜像重新收集6165个ID并逐批比对，未重复执行全量。

```json
{
  "status": "verified",
  "base_sha": "fc1eed938beb8b431e0d4b37953f7599a40a72ce",
  "head_sha": "185a7d072e399576d35a53ddea4f94f136bb7228",
  "test_sha": "a4495961d02d7d2829ec864cfa0792a93edf83c5",
  "merge_sha": "a4495961d02d7d2829ec864cfa0792a93edf83c5",
  "test_tree": "bde1542bbb082b4f38441ecb1d31fc1d28970216",
  "run_id": 37028610440,
  "run_attempt": 1,
  "artifact_id": 11237438440,
  "artifact_sha256": "ad67e527a647515aba61a7bafadc97ddc7fe492cee5c964f4b10ed79521d4142",
  "trusted_sha": "185a7d072e399576d35a53ddea4f94f136bb7228",
  "verifier_sha256": "7e58cb72042dd76ef064f9121589f1a06655aad6befc1278d389ffc8799c7d7d",
  "summary": {
    "status": "passed",
    "skipped_count": 10,
    "mode": "full",
    "count": 6165,
    "plan_digest": "93cf8c978ad253d687499a7cf8fdd8ea5b552fbbcc0f418722cb7a05ee66d5ed",
    "run_id": "37028610440",
    "run_attempt": "1",
    "test_tree": "bde1542bbb082b4f38441ecb1d31fc1d28970216"
  }
}
```
