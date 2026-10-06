# A036：prepare-only 命令测试先行准备

任务 `A036-H03-PREPARE-COMMAND-RED-PREP-001`。基线已审 A035 `72f82102409bd9d7c6e200fb57a565ed9d23059b`；原 R `01bcc0879e8c83312d686cf056090810ea44c06e` APPROVED_PLAN_ONLY / finding CLOSED 的状态来自 ROOT 核验通知（7指纹、receipt3e66687c），本卡不冒充新代码审核。独立 worktree `/Users/mentianlu/.codex/worktrees/a036-h03-prepare-command/umanews`、branch `codex/a036-h03-prepare-command`。A035候选冻结；A034/其他lane不改。本次授权覆盖准备测试及无写stub，G1已满足；G2/G3没有执行动作。适用根AGENTS.md；按tdd skill先写完整test_cases再stub/测试，不启动其他规格工作流或subagent。

## 已准备的固定范围

- 新 `management/commands/horse_basic_profile_from_cache.py`：正常BaseCommand可导入/可解析，只输出JSON not_implemented/prepare_not_implemented；requires_system_checks=[]、requires_migrations_checks=False，六项明确输入参数，不注册apply/commit。无helper调用、无原件读取、无DB/网络/写文件。这是为避免UnknownCommand假RED的stub，不是GREEN。
- 新 `test_horse_basic_profile_from_cache_command.py`：六个直接SimpleTestCase方法，业务DB全部alias禁止；新fixture是已有A032合成JSON逐bytes副本，HKJC URL只是测试形状，不构成真实来源认证或审批。
- [test_cases](A-036-h03-prepare-command-test_cases.md) 固定接口、正常/异常/权限/路径/故障/恢复/显示/性能边界和mutation；无新model/migration/事务/celery/公开行为，原A03225方法不重复成新增。

首例preflight会执行真正adapter/H02/normalizer及现有workbook并读回关键cell，证明合成输入和真实消费函数有效；然后真实call_command收到正常stub JSON，断言status必须prepared，所以预期业务失败为not_implemented!=prepared。helper/import/setup/fixture/workbook异常不算RED。命令成功路径的helper spy仅wrap真实实现，输出断言检查实际JSONL/CSV/XLSX，不只看mock调用。

setup前零DB由独立CLI子进程覆盖：BaseDB connect/ensure_connection/cursor/_cursor和socket guards在django.setup之前安装，禁dotenv；两个alias与普通/生产样式settings/任意DATABASE_URL都需setup成功、zero trips且实际workbook可读。拒write参数、hash/身份/过期、symlink/越界/覆盖/JSON限额、公式/控制字符与故障后半成品清理在其余精确方法中；普通negative不因stub提前拒绝而被称已验证。显示转义不改canonical，pending manifest不写reviewed_input_sha/生产approval。prepare入口不称apply闭环。

## 静态检查与真实执行边界

已做仅AST语法（含CLI bootstrap字符串）、六canonical IDs直接存在、stub无禁止调用、合成fixturebytes相等、共享源码及八controls相对基线逐bytes不变、docs-only契约说明与git diff --check。未import/run测试/helper/Django command/workbook；没有业务RED、GREEN或代码review证据。正式catalog未改，正式文档suite未运行，不标其PASS。

## 交 ROOT 的最小首 RED 申请

只申请 `stable.test_horse_basic_profile_from_cache_command.PrepareCommandTests.test_prepare_real_pipeline_pending_outputs_and_visible_seven_fields` 一次，profile django，须ROOT将固定SHA/tree/测试/stub指纹绑定官方精确batch。未映射新模块不改catalog/不私跑collector；当前无资源授权。八controls、官方固定镜像及单容器资源/600秒总窗细节见test_cases与runtime request。SimpleTestCase无业务DB，但正式Django执行器自有临时PG初始化/版本探测，不绕过它或降为宿主Python。

若首RED正确，下一步ROOT核证并授权同范围GREEN；后五方法及必要直接回归另申请窗口。任何不匹配/错误/timeout先技术定位修复，不猜RED。A保持准备状态，不启动PG/Docker/网络/生产、不改A035候选或共享代码。

当前额度17%已用/83%剩余；每5分钟检查、每批目标<=3%、剩余<=1%停止。固定新candidate与runtime receipt交ROOT后等待allocation。
