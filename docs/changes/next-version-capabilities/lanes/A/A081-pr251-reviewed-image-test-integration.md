# A081：PR251 已审镜像测试文件整合候选

仅本地固定整合，待 ROOT 路由原R精确整合审。直接parent为ROOT live确认的PR251 openDraft head `50a87d7b455fe47da1786fce6825dbfb7dc7fcf8`，main仍以ROOT指定固定对象 `1dd5e0a508957672bcddd1c33e454fbbef1b75c1` 为基准；本轮不请求网络或独立重查API，不push/更新PR/CI。本候选不是新的PR test-merge。

只从获审 `d611a13c9d88883141c97eb3458c558cb72da84c` 导入原 `server/stable/test_migration_history_repair.py` **exact blob `2b5c839a0ea12b0a82d862465ff8232a5a44ba0c` / SHA256 `76e786ea51ea96895a1c75c20e7d9272d5e67cd83e6675e81c8ec0a0faef8064`**；该文件在parent原同main。另仅本文新增，不cherry-pick A079/A080文档、台账或其他slice，不重实现。

依赖原R报告 `dd7a1637d15f32f22d2a3279179ad7552421c125` / SHA2482b1afb838b3ba7282730d23e89a997d158f8b3f74a94845c8f8d7162adb85，review receipt SHA cc8d5b831ca01fde08a5a06e1814e290afb37d62a34fec59d8ace07c80738340。原A080封包index6cbcc82b27ea0db344a627cc15290f1d5df18a1366af71baf202d676be0bcf2e的63files逐字/hash核，未修改；作者六轮RED/GREEN及最终20pure、原R独立20pure仅为已有本地合同证据，本轮没有再运行。

## 三层静态计划

固定commit后的精确base/head/test=head、tree、changed paths、全部domains/真实labels与catalog profile binding在自有runtime `/Users/mentianlu/.codex/runtime/a081-pr251-reviewed-image-test-integration-001` 的三份Git plan及 `three-layer-plan-summary.json`。test=head是本地固定对象，不冒PR merge/正式collect；native总分母及native profile counts一律unknown/null，不从labels或A077的旧6912推当前执行数。

| 层 | 作用／计划 | 静态范围 |
|---|---|---|
| L1 main→parent | `main-to-parent-plan.json`；保留原PR251 R04与mapping差异 | full：267domains、330labels；静态目录声明profile families为django/python/release-postgres，不能当native profile计数 |
| L2 parent→本候选 | `parent-to-candidate-plan.json`；只测试file+本文 | targeted：2domains、10labels（下面完整列表）；原test module覆盖新增20pure，20canonical IDs按实际worker prefix规则均django |
| L3 main→本候选 | `main-to-candidate-plan.json`；整个PR累积范围 | full：267domains、330labels，因既有rules/catalog差异触发；未执行full CI或原app回归 |

L2 domains：`core`、`module:stable.test_migration_history_repair`。labels：

- `stable.test_horse_profile_publish.BasicPublishGateTests`
- `stable.test_impact_core`
- `stable.test_migration_history_repair`
- `stable.test_race_data_sync_r0.RaceDataSyncR0FlagContractTests.test_celery_route_and_beat_schedule_are_isolated`
- `stable.test_race_live_official_publication.RaceLiveOfficialAuthorizationBehaviorTests`
- `stable.test_race_live_official_publication.RaceLiveOfficialAuthorizationCommandTests.test_authorization_apply_exact_replay_is_idempotent`
- `stable.test_race_live_target_eligibility`
- `stable.test_release_commit`
- `stable.tests_legacy.PublicHomeInfoFeedTests`
- `stable.tests_legacy.PublishWindowServiceTests`

现rules/catalog已具 `stable.test_migration_history_repair` module覆盖，无mapping变更，所以没有必要再跑39映射合同。新pure20只增canonical IDs，不需要添module label或另造profile。未知路径和catalog dependency drift静态调用仍ValueError拒绝；models高风险静态选full。父候选4件R04 core/mapper/tests和20control blobs逐字不变（rules/catalog的R04登记亦保留），原10skip exact IDs/profile/reason/review_by与固定main一致，2026-10-16不延期/删减。

## 正式worker约束的静态兼容分析

测试镜像 `deploy/test-impact/Dockerfile` 已装git，USER10001，PATH有/usr/bin；entrypoint在/tmp/work创建固定Git snapshot，/tmp为可写tmpfs。pure20使用自己的TemporaryDirectory/init/add/明确user.name-email commit、read/archive，显式core.hooksPath=/dev/null，不依赖snapshot的祖先history或父1dd对象，不访问remote、不执行Docker/root方法。Python3.12语法静态解析通过；非root权限足以写自己临时repo和700 context，100644/100755由自己chmod并正常清理。

现catalog模块把pure20归django；worker先清外部env、Django setup，collect与django批入口会启动专用PG，execute还probe PG16并用DiscoverRunner。因此“pure20自身不连DB”不等“正式worker不启动PG”；本轮只静态核协议，**未import/collect/worker/PG**，Linux实际约束仍待正常CI。原migration-image env开关不被setup保留，旧Docker ID保持同reason skip；其未来需要另外获准准确Git源对象/daemon。产品Dockerfile不装git不是pure20测试镜像缺陷，没有改product Dockerfile理由。

导入blob中的expected image.source仍 `1dd5e0a508957672bcddd1c33e454fbbef1b75c1` / tree `67e755d385725fa7404cba822bf65d74f50403cf`，不漂移为d611/parent/本候选。原实际image、nativeDocker ID、owned resource cleanup与full delivery无新证据，skip关闭仍 **0/10**。无本地测试重跑、资源/DB/PG/VM/Docker/CI/下载/cache/provider/network/付费/生产动作；原封包、他线与ROOTledger保留。后续只在原R审准确候选后由ROOT另派正常FF+CI；merge/deploy无权，完整R04/source/I2仍未完成。
