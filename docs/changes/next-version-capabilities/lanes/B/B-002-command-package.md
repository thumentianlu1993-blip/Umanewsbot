# B-002 固定导出脚本与命令包（待技术核对）

本地实现日期：2026-10-03，Asia/Shanghai。生产执行状态：未执行。
源脚本 `scripts/f02_readonly_export.py`，SHA256 `9c49d5d4e90cf5074591e42b1ba96f583b1f8b683bd15d3e758db85ddb00de34`。
测试 `scripts/tests/test_f02_readonly_export.py`，SHA256 `a1798c160f9ea0c477503975eba65e275008d7199b56fa027621f513ea6b6cc9`。
提交 SHA 由阶段消息绑定；执行者从该固定 Git 对象提取脚本，禁止使用随合并变化的 checkout 文件。

## 已有本地证据

17 个合成/fake 单元测试通过，代码字段对 model AST 校验通过。
默认 `--mode plan` 实测不连数据库，产物在本线专用工作树外目录 `/Users/mentianlu/.codex/artifacts/umanews-next-version-B/B-002/runtime/next_version/F02/b002-offline-plan-v1/`，manifest SHA256：
`1103cfa974be5330a99a55f97ef00a8790df4bdd3c2d06db2b8ce99161c19c8c`。
这是离线执行/合同产物，不是生产样本，也不是固定Linux受测树交付收据。

## 命令的绑定槽位

执行前由协调者核对并记录以下真实值，缺任何一项不执行 live：

- DELIVERY_HEAD：本阶段固定提交；SCRIPT_SHA256：上述摘要；EXPECTED_RELEASE_SHA：resident marker 与镜像标签一致的完整 40 位 SHA。
- WEB_ID：docker ps/inspect 实时核对的唯一 resident web 完整容器 ID，IMAGE_ID：只读 inspect 的实际镜像 ID。
- SCRIPT_PATH：同一个已核对的 runtime 挂载内脚本绝对路径，内容与固定脚本SHA一致；OUTPUT_ROOT 固定为该容器 `/app/runtime/next_version/F02`。
- OBSERVATION_ID：新的元数据 observation，例如 `F02-20261003-metadata-01`，不得覆盖旧包；内容包另用新 ID。
- 执行用户、目录权限与 R 托管路径；已有 POSTGRES_HOST/PORT/DB/USER/PASSWORD 必须明确存在，脚本不加载 .env、不猜密码、不输出环境。
- content 模式另绑定由 R 交接的 selection 文件路径、文件 SHA、source_metadata_manifest_sha256、source_schema_sha256、release SHA、最多150个明确ID/input SHA/updated_at。

当前本线未核验上述生产槽位，所以本包不能谎称已经存在可执行的真实生产绑定命令。
协调者确认槽位后生成字面 argv 数组与 capsule SHA，无需增加产品确认；R对脚本/命令技术核对和原有F02只读边界仍适用。

## 精确预检命令与 live argv 模板

下面第一个命令可用于绑定 discovery；本线尚未执行。其余 `WEB_ID/SCRIPT_PATH/EXPECTED_RELEASE_SHA` 必须替换为已核对字面值，禁止原样执行或从不受控输出插入 shell。

```sh
ssh -o BatchMode=yes -o ConnectTimeout=8 umanews 'docker ps --filter label=com.docker.compose.service=web --format "{{.ID}} {{.Names}} {{.Image}} {{.Status}}"'
```

通过同一既有 SSH 通道，由协调者执行以下 argv；使用参数数组或正确 shell quoting，不输出完整 docker inspect/env。

```json
["docker","inspect","--format","{{.Id}} {{.Image}} {{index .Config.Labels \"org.opencontainers.image.revision\"}}","WEB_ID"]
["docker","exec","WEB_ID","cat","/app/.umanews-release-commit"]
["docker","exec","WEB_ID","python","-c","import importlib.util; print(importlib.util.find_spec('psycopg') is not None)"]
["docker","exec","WEB_ID","python","SCRIPT_PATH","--mode","metadata","--output-root","/app/runtime/next_version/F02","--observation-id","F02-20261003-metadata-01","--expected-script-sha256","9c49d5d4e90cf5074591e42b1ba96f583b1f8b683bd15d3e758db85ddb00de34","--expected-release-sha","EXPECTED_RELEASE_SHA"]
```

脚本 staging 只由协调者向专用 runtime 写入固定字节并核对摘要，非业务数据写入；不覆盖应用目录，不重建/重启服务，不导入 Django。
transport 使用独立超时至少200秒；脚本内部总超时180秒、连接8秒、语句15秒、锁1秒、idle事务15秒。
工具 stdout 只接收脚本的完整/失败收据，所有原文落文件；禁止在工具中 cat 内容文件/原文包或直接 text()/模型输入完整包。

metadata 成功后，协调者把受控路径与 manifest 直接交 R。R按协议选择/分组，返回明确selection文件及摘要，再执行：

```json
["docker","exec","WEB_ID","python","SCRIPT_PATH","--mode","content","--output-root","/app/runtime/next_version/F02","--observation-id","F02-20261003-content-01","--expected-script-sha256","9c49d5d4e90cf5074591e42b1ba96f583b1f8b683bd15d3e758db85ddb00de34","--expected-release-sha","EXPECTED_RELEASE_SHA","--selection","R_SELECTION_PATH","--selection-sha256","R_SELECTION_SHA256"]
```

selection 文件绝对路径、无symlink、≤256KiB、权限不向group/other开放。B不读待划分全集，R只把development包后续交B；保留集始终由R托管。

## 查询、失败与恢复合同

脚本只调用参数化 SELECT、BEGIN READ ONLY、SET LOCAL 和 rollback；schema包含 stable六张表及 django_migrations 列存在性，缺列停止。
schema probe 读取 information_schema 元数据；实际业务表名/列由代码常量提供，不接收动态SQL。
所有 metadata SELECT 在同一 PG REPEATABLE READ READ ONLY 事务内。T来自 transaction_timestamp，固定 first_seen 28天 cohort；窗口/来源尝试独立事件流与无candidate窗口保留。
目前只导出cohort/事件流，不声称已完成全存量/全网漏报基线；原代码默认和生产有效settings仍另取证。
cohort≤10000、sources≤100、crawl/window≤20000、decisions≤100000、homepage exposure≤20000；超限先返回预算错误，不截断明细冒充完整。
content先只读取明确ID的字节长度，再读正文；≤150篇、512KiB单篇、30MiB整包，序列化扩张超限也拒绝。
第二次事务的schema/input SHA/updated_at不符即stale；原文SHA与脱敏SHA分别保存。

首次进程失败/传输结果未知：先查具体 observation 的manifest及进程是否已退出，不能盲重做。
已有成功目录拒绝覆盖；失败清理未完成目录，没有成功manifest。失败后新事务必须使用新 observation ID，不拼接旧半份结果。
可恢复连接/传输错误核对后最多3次（2秒/5秒）；脚本不自行重连或跨事务拼包。确定性schema/预算/漂移错误交协调者解决，不机械重试。
不会修改生产DB/Redis/队列、模型配置或权限，不发通知，不启动任何收费模型调用。

## 尚待证与交付验证

fake测试不能证明真实PG SQL执行/事务权限、resident env能力、运行时挂载/容器身份；待隔离PG或受审只读运行核验。
代码采用既有 requirements 中 psycopg 3.2.6，lazy import；本地离线测试不需该依赖。
不直接 import app.settings，因为它可能创建日志目录；本包的 effective_settings_verified 始终为 false。
脱敏只处理已列HTML区块、credential表达式、邮件与URL；不宣称可完美识别任意个人信息。可能含敏感内容的包只在R受控路径保存，脱敏损失的块标无法评价。
producer结构校验不冒充独立机器核验，machine_validation_status 初始 not_run、human_verification_status=not_reviewed；后续R独立验收再填对应状态。
真实新快照/gold/holdout仍0；F02未完成，不解锁M01。

新测试路径建议登记 `scripts.tests.test_f02_readonly_export`；脚本映射到该测试模块及现有核心检查，具体rules/catalog由协调者接A补丁后组织。
固定Linux/full证据按现行runner取得，不能把上述17例本地GREEN当默认策略已全面启用。
