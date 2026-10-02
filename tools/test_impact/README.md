# 按改动范围测试

此目录保存受审映射与纯数据合同。当前引导状态见
[实施记录](../../docs/changes/impact-based-testing/rollout.md)，不要把工具链检查通过称为策略已启用。

## 开发者入口

1. 最小 RED / GREEN 后，使用固定完整 base SHA 生成计划：
   `python scripts/plan_affected_tests.py --base <40位SHA> --local --output /tmp/test-plan.json`。
   本地计划包含 index、工作区、未跟踪文件、删除及执行权限，只有诊断效力。
2. 固定提交后用 `--base/--head/--test` 生成 Git 计划；PR 的 test 是精确合成合并提交。
   首个引导版本的 base 尚无规则时才用 `--bootstrap`，交付仍需独立审核绑定。
3. `python scripts/run_test_plan.py --plan <计划> --output <目录> --build`
   仅支持已核验的本地 Docker socket；无 daemon 时明确失败，不回退到宿主 Django。
   `--collect-only` 只列用例和分片，不执行测试。
4. `python scripts/verify_test_plan.py --plan <execution-plan.json> --reports <目录> --output <summary.json>`
   检查完整集合、身份、skip 政策及收尾。它不替代候选外的交付核验器。

## 选测边界

- `docs-only`：白名单说明文件，仅做差异/引用/语法及从固定base提取的工作流合同检查。
- `targeted`：显式领域与依赖，加53项核心检查（按当前收集结果；变化时重新收集）。
- `expanded`：相关领域超过400项，仍按范围执行，不截断、不偷偷改成全量。
- `full`：共享模型/迁移/装载/依赖/测试基础设施和映射变更；仅运行一套候选，没有默认基线全量。
- `unmapped`：未登记的新文件或函数，在执行前报错。补受审映射后继续，不默认为空或全量。

普通页面与马匹发布服务分开：后者额外覆盖批次自动发布、冻结排除和重试合同。
赛果写入包含公开读取、修复重放和 PostgreSQL 合同。其他未精细审核的已有生产路径保守标为高风险，
因此首版并不保证任意文件的小改动都能少测；不要只为降低数字把它改成低风险。

测试模块/类的所有权由 profile 定义；别名按 canonical ID 去重并记录。每个整类最多200项，单批最多200项，
最多4个独立容器同时运行。收集失败、超时、缺片、意外 skip、退出/收尾失败都阻断。
容器无外网，PG16在同一容器的loopback内且使用UTF-8；Docker CLI只用于离线Compose配置，真实daemon不可访问。

10项真实缓存/root/真实镜像合同目前存在明确覆盖缺口。catalog逐项列ID、原始skip原因和2026-10-16复核期限；
不自动延期，不扩展到其他skip，也不能宣称它们通过。普通核心/工具链验证不依赖这些豁免。

## 交付与回退

`verify_delivery_test_evidence.py` 必须从固定可信Git对象提取到候选外，以 `python -I` 运行。
该工具验证真实run/attempt/job/步骤、完整tree、控制文件白名单和strict保护；先重算可信模式，再用该run镜像独立收集。
缺镜像artifact或Docker时阻断，不能省略重收集。只有首次引导允许独立审核绑定的manual证据且完整tree与实时merge tree相同。

`toolchain` 和 `release` 是明确的手动诊断范围，均标 `validation-only`，不能冒充普通PR所需业务证据。
新策略激活变量、strict保护、full首次校准必须分别验真；交付门禁只引用根 `AGENTS.md`。
