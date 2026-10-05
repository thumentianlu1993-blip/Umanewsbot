# B020：M01 Responses 适配器/mock 开发子片

固定实现基线 `22e130adf4464fd3c5dd63ccd3f508c4a853d464`；worktree `/Users/mentianlu/.codex/worktrees/m01-responses-mock/umanews`，独立分支 `codex/m01-responses-mock`。依据已审B019 `9edcf8f509a39a29ce96e4e50971bb6fb163c136`，原R确认B019-R01 CLOSED。本次只改responses_analysis.py、新test_responses_analysis.py及settings独立配置块，并新增此B报告；原a14d及两项untracked保留，不改F01、requirements、旧translation/rewriting/tasks或共享CI映射。未合并/发布。

## 实际行为

新增纯AnalysisInput/AnalysisResult与一个ResponsesAnalysisProvider。默认off及空模型/endpoint；factory在disabled时不读取其他配置/凭据或构造/克隆client。正文先校验F01版本、UTF8 SHA、单text_evidence_id/原件摘要、identity或显式normalize_lf_v1派生关系和允许区间，再核typed候选与实际snapshot.entity的kind/state/canonical/mention；候选ID必须确在输入candidate_ids且有显式映射，不能推定身份。错误输入0请求；无绑定null候选为unresolved，模型猜ID拒绝。

启用且有效时一请求；真实与注入client都配置max_retries=0，store=False/stream=False/truncation=disabled、无tools/previous_response_id；请求只投影正文/绑定候选/该篇证据区间，不发送秘密locator或完整F01控制。strict schema与本地JSON深度/节点/bytes/区间/引用/唯一性校验；扫描全部content的拒答，非completed/截断不解析，重复文档拒绝。不修补/回退/自动重试/升级身份或确认事实。

返回业务DTO及白名单有界metadata，记录requested/returned model、prompt/schema/provider版本、输入SHA/版本、response ID、usage（缺失null）及耗时；异常正文/headers/request不回传。429/timeout/502–504仅标可重试，不重发；Retry-After裁至0–3600秒。client构造失败安全归一，不泄露异常文本。没有ORM写入或自动发布入口。

## 测试与可追溯源

使用仓库TDD规则，以已审方案RED矩阵作为本次测试设计与mutation清单，未新增规格工作流：

- 真实RED：可导入最小接口stub，disabled零访问、合法显式LF派生两方法分别assert失败，2 tests/2 failures、exit1；不是导入/环境错误。额外构造异常测试捕获异常直接外泄，1 test/1 error、exit1，随后修复。
- 初步GREEN：13纯mock tests通过。最终Linux冻结快照 **17 tests / 0 skip / 0 error / 0 failure，exit0，0.967s**；16适配/mock/配置方法加1旧provider factory兼容方法，无真实API或生产服务。旧dummy/fallback及openai-compatible选择保持，未运行全量或建立测试数据库。
- Mutation覆盖：移除disabled先判/输入绑定/证据归属/typed身份/区间/SHA检查，接受拒答或截断/重复文档，忽略429/timeout或泄露构造异常，启隐式重试/请求存储、改旧factory选择均被对应断言捕获；另测512KiB/1MiB、bool offset、非法/超限配置、source/evidence误绑定、ambiguous/revoked/crosskind、合法对象/dict及缺usage。
- RED快照内容hash `c5bdb7e8893a92537ad0491e7b3bbf7dacec46bf91ce79d964d9c5c23f1ae568`；构造异常RED快照 `4c35a52c054cf5958bcc52b2ef6863363cb223272bb4d223635247ef2461c79a`。
- 最终实际测试source内容hash `e520fd2bbfde9afd90e548195878121ea36c6f88f68251f28f1bf6ad68644cc4`，基线git archive加指定三处修改的只读bind快照，`source.json`逐文件SHA；测试后与工作树四输入文件（含未改F01）完全相同。
- 缓存image `sha256:ab8494e6202dced04a6c2b5b885b3d1f2d9c80776ec8ae8d97f3552aae6b3ecc`，显式colima-umanews-impact-ci；一自有容器b020-m01-responses-v2、2CPU/4GiB/pids256、network none、只读rootfs、capdropALL/NNP、专属/tmp。exit0后--rm回收，exact-name ps -a为空，已向ROOT释放窗口给C026，未等到14:36。

运行收据 `/Users/mentianlu/.codex/runtime/b020-m01-responses-tests/test-receipt.json`，RED日志及各只读snapshot同目录。源文件AST和git diff --check通过。最终代码提交SHA在ROOT交接消息和该收据绑定；独立代码review由ROOT安排，同原R使用官方review_fingerprint前后，不把本地GREEN称为独立review通过。

## 仍待进行

当前只是开发子片：新近F02五地区≥100及真实人工gold、账号可用/实际模型参数、模型质量/时延/成本和最终M01仍未完成。产品模型未启用，不读取生产配置/密钥，不调用付费API，不用历史一篇抵扣F02。shared影响映射未改，正式CI交付由ROOT整合安排；本次17项不是全量/正式CI宣称。实施资源已清理，等待原R代码审；任务完成即停，不自动扩到N03、翻译接入或native/Index。
