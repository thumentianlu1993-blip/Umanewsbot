# PR233 CI策略启用包

用户在2026-10-02明确要求“启用并上线”，范围为PR233及上一轮列明的首次校准、实际交付核验、严格保护和策略切换。
本包以PR233最终head和实时main/base/tree绑定；精确SHA、CI run、review及delivery receipt由执行记录保存。
人工确认门禁仅引用根AGENTS.md。

## 操作范围

- 单候选full首次校准：每批≤200，最多4容器并发，不执行基线全量；所有失败/skip显式记录。
- 独立review通过后，从受信Git对象提取核验器到候选目录外，以同run镜像重新收集并核验证据。
- GitHub main保护：strict required checks与enforce_admins；引导阶段要求实际检查名`impact-validation / test-plan-gate`，合并切换后要求普通PR的`test-plan-gate`。不增加人工审批人数或旁路身份。
- 设置仓库变量`IMPACT_TEST_POLICY=active`，合并PR233，切换统一PR gate，启用受控高风险及日周full入口。
- 没有数据库迁移、生产配置/数据动作、应用镜像重建或服务重启；没有QQ、邮件、通知或真实抓取动作。

## 验证

核对真实API的检查名称、成功run/attempt、完整合并tree、控制文件身份、实际收集全集、strict/admin保护和base未前移。
主线启用后，以文档小改动的真实PR验证新入口只做静态检查、不执行业务数据库测试，并核对旧入口不再自动触发。
其他targeted/expanded/full/error分支用已有合同与计划回放验证；首次full通过不等于10个明确环境覆盖缺口已消失。

## 失败处理与回滚

任一必需核验失败时不合并。修改前保存原始保护配置、变量状态、主线SHA与旧workflow。
合并前失败可恢复原保护/变量状态，不影响业务服务。
合并后若新入口不能正确拦截或执行，通过受审revert恢复旧workflow和原变量/保护配置；不得仅关闭新检查后继续交付。
回滚会恢复旧测试成本，但不涉及生产数据库、镜像或业务数据恢复。

## 首次引导兼容修复

实际GitHub check-run名包含reusable workflow调用前缀。核验器从已验证的bootstrap workflow推导唯一required context；
普通PR仍严格要求无前缀的`test-plan-gate`，不得用引导检查替代。新增小测试先RED，再48项GREEN；等待独立复审。
