# B-002 本地导出器阶段报告

日期：2026-10-03，Asia/Shanghai。阶段：本地GREEN，脚本/命令可审；未运行生产查询。
worktree `/Users/mentianlu/.codex/worktrees/a14d/umanews`；branch `codex/next-version-news-ai-20261003`。
代码base `907f8de699b31a6fcc80acc78e9ba070aadc4f28`；本任务parent `a2704b2d7ef93a6ee8518fca2f63ada4a43c2b64`；新head由阶段消息绑定。

## 已完成

- 读取原R F02-M-01；协调者已转达 a2704b2d APPROVED、finding CLOSED及导出方案审核通过。
- 本线负责 `scripts/f02_readonly_export.py`、`scripts/tests/test_f02_readonly_export.py`，未覆盖其他线程或共享rules/catalog。
- 实现默认离线plan、显式绑定metadata/content模式、只读/超时/schema/预算检查、固定cohort与窗口/尝试明细、R selection/input漂移、脱敏和文件manifest。
- 完整设计映射见 [test_cases.md](test_cases.md)，执行前命令与绑定缺口见 [命令包](B-002-command-package.md)。

## RED / GREEN 与异常

实际命令均为 `python3 -m unittest scripts.tests.test_f02_readonly_export... -v`，没有访问真实网络/DB。

| 阶段 | RED证据 | GREEN证据 |
|---|---|---|
| metadata/HTML | 初始2例因已可导入接口的NotImplementedError缺行为失败，exit1 | 同2例通过 |
| sealed content | ContentTests 2例/5子例因publish_content未实现失败，exit1 | 加边界后全组通过 |
| readonly DB合同 | DatabaseContractTests 因collect_metadata未实现失败，exit1 | 对readonly顺序/schema/超时回滚等通过 |
| CLI | 首次mock缺接口AttributeError不计RED；补骨架后2例因main未实现失败，exit1 | 默认离线/固定binding与fake全路径通过 |
| 最终局部回归 | — | 17例通过，exit0，约0.85秒 |

macOS /var临时目录symlink导致的fixture失败不计目标RED，测试使用真实绝对路径；没有放宽导出器拒绝symlink边界。
大文本边界测试发现邮箱正则过慢：只停止已确认本线PID的单元测试进程（退出143），修正边界后原测试恢复GREEN；未触碰其他线程/生产进程。
数据/测试不是人类gold；producer结构校验也不写成独立机器核验。

## 仍待进行

- 原R脚本与命令技术核对；真实resident容器/image/release SHA、挂载路径与env能力绑定。
- 映射衔接：新增路径与测试入口已交协调者，待A首个固定rules/catalog补丁后组织B映射和现行固定Linux/full证据；不规避策略。
- fake不能证明真实PostgreSQL语义，尚无隔离PG/live结果或正式测试交付收据。
- 生产新快照/gold/真实holdout均0；F02未完成，M01不解锁。无migration/配置/生产业务写入/真实模型/外发/合并。

## 资源与恢复

最近实时额度为周used93%/remaining7%，只作当时证据，无子代理或模型CLI运行。
临时异常最多3次（2秒/5秒）核对后恢复；未知写入结果先查收据。额度查询临时失败可有界重试，恢复>1%自动解除未知保护；实际≤1%按用户要求停工，待用户明确恢复且实时>1%。不使用积分/重置券。
持续每5分钟、每轮/长任务/review前检查，≤3%逐批次检查。Linux资源接入待协调者/A验证专属DOCKER_CONFIG方案，不修改runner或全局context。

## 原R三项P2返修（当前阶段）

原审核 @48c51fb1：REVISE，无P0/P1；17例独立fake PASS为旧版本证据，保留不改。
P2-01已获真实RED：URL reason原样泄漏导致断言失败；修复为明确码正则/unknown及替换计数，GREEN。
P2-02已获真实RED：合法内容路径receipt缺来源摘要，9组反例仍尝试连接DB；仅补CLI参数入口后的测试已证明行为缺失，非参数/导入错误。修复实际metadata全包/receipt/cohort绑定后，同例GREEN。
P2-03已获契约RED：proposal缺python profile返回None；补profile提案后GREEN。实际shared rules/catalog仍未改。
返修后局部回归21/21 PASS，约0.86秒；新离线plan已生成，仍未连接数据库。命令包已绑定新script/test摘要和--source-metadata-dir，真实生产槽位仍待核验。
原R限定复审仍待，不自称findings关闭；无新真实样本/PG/Linux正式收据。最近实时周剩余6%，无子代理/模型CLI。

## O01 输出路径适配（方案阶段）

协调者已实核resident web没有通用F02持久挂载，只有horse_profile_completion挂载。本线未再次探测生产。协调者另核psycopg可用、五项POSTGRES键存在、uid0和/tmp可写；DB二进制16.14，仍未执行DB查询。
已写 [容器临时目录与宿主artifact转存方案](B-002-transfer-plan.md)，标记旧持久挂载模板失效；不改Compose/挂载/服务或借用horse目录。
建议容器producer包经精确ID的docker cp转到私有host stage，独立核manifest/文件/hash/bounds后原子提交final及transfer receipt，再直接交R。
未转存、unknown、持久host verified、source lost、R收包分别记状态；先核实际结果，不盲重采。wrapper/verifier尚未实现，不把方案称为执行证据。
本次仅文档适配，三P2修复脚本字节仍与910353a5一致；待原R同上下文核对。
