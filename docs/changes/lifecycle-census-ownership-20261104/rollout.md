# 归属校验修复与授权续期恢复包

## 固定对象和已完成部分

- 当前生产：`ab5775f62619ec196aed7bd7f87f65236b53dfa8`，镜像 `sha256:ef9a690471051f4bfb7095b10fc5b2e93d47cf7d6a3ad37972076b56f315df27`，schema0079。
- 新固定候选：`661a0859242f001853957365fcb8dd7c5ad0ddab`，基于当前生产，仅修改两份校验文件及promotion失败恢复。不发布含额外迁移的完整主线。
- 新授权 artifact SHA：`00a4e93ca22e4189d9b026359a9111898a745a2751b37ec78d43fdea7aa33b86`，批准提交为上述候选；生成时间 `2026-11-04T15:43:50.598118+00:00`，须在24小时有效期内应用。
- 原 active root：`28c327c0897f3c1559dfa99fc9fed76532dc1b1bee6f2ed994db4e680e5bb1a9`；新 generation3、成员仅956、membership SHA `f500e2fac984d03df92cc7fa83762425fb2b6bf70a4e540a168bae0ac2ce4a90`。
- 新期限 `2027-12-31T16:00:00Z`，覆盖北京时间2027/12/31全天。TRA已经续期，本包不再变更TRA摘要、地区、接口、配额或standing policy期限。

原PR275已合并、应用发布已完成，但promotion在写数据库前被同机外项目worker阻断。当前lifecycle false/off、普通worker和Beat停止；web与race_sync_v2_worker运行，OneBot停止。原generation2仍active但过期，新generation3不存在。不得将该状态报告为完整续期成功。

## 资源与恢复锁

目标仅主机47.239.167.86的umanewsbot项目及单赛事956授权。不得停止、重建或改动wechat-summary项目。保留全宿主扫描，不以project过滤替代归属证明。

原`/tmp/umanews-deployment.lock`是失败保留证据，不能按时间自动删除。包内明确包含一次恢复所有权接管：在持有`/tmp/umanews-release-coordinator.lock`的排他flock时，核对原promotion PID151725、锁PID151734及原coordinator142784均已退出且命令身份没有复用；归档原锁内容、哈希及owner证明，再将原锁目录原子移动到私有证据目录。若PID仍存活或身份不清，立即停止。原只读恢复lease PID158666须先通过其stop文件退出，确认flock释放后新coordinator接管，心跳连续记录owner/thread/operation/SHA/资源域。新操作均使用原受保护共享锁入口，不绕过校验器。

保留原`/opt/umanews-authorization-20261104`中的发布intent/complete、两轮备份和失败日志；恢复动作另建私有目录。新发布前再次核对生产版本、配置、单成员、事件行、服务状态、磁盘/内存、任务/队列和并行导入锁。条件漂移时不继续。

## 发布顺序

1. 验证固定候选、源码与PR对应文件一致，授权artifact原始SHA/approved_commit/期限及前驱一致。配置从当前**active release**复制；canonical.env存在旧QQ漂移，不能作为复制来源。分别备份两份env，保留现有false/off及全部QQ关闭值、OneBot停止状态。
2. 准备独立新release目录和共享持久化挂载，镜像绑定新候选SHA；不清理旧checkout。按上述恢复接管规则归档遗留锁。
3. 使用新候选`deploy/deploy_0079.sh deploy`执行同schema发布。执行原归档备份、SHA/TOC、迁移空计划、static及完成凭据检查。**无新增迁移，无反向迁移，无全库恢复。**失败只允许原intent/镜像的受保护resume；不得把旧complete当新收据。
4. 0079按进入时服务清单恢复web与race_sync_v2_worker；普通worker、Beat仍停止。核验完成凭据后，在同一coordinator、共享部署锁下以新候选及false/off配置重建并启动普通worker，保持Beat停止。四个应用服务都必须为新候选镜像（Beat随后重建）；该worker恢复明确属于本包。对web IP变化执行`nginx -t`及平滑reload，不重建Nginx。
5. 以固定新artifact运行修复后的受保护`deploy/promote_lifecycle_enforce_registry.sh`：先排空并停止普通worker，备份验证后更新配置，重建web/worker为false/off，用修复后的宿主归属检查器核验，再创建generation3与单成员。须验证旧root/identity/CAS和956行不变；不得修改赛事事实、扩大成员或人工触发抓取。
6. 运行原`deploy/switch_lifecycle_mode.sh`，新root/membership/count与artifact完全匹配；先激活数据库，再写true/enforce并重建web/worker，最后重建启动Beat。只恢复原956授权范围。nginx如因web重建变化再次平滑reload。
7. 核对四应用镜像/commit、配置和QQ关闭态，TRA合同不变；新registry active、旧registry退休、成员与control一致，956仍finished。核对schema0079、迁移空计划、队列/锁、worker和Beat健康，双域名首页/healthz/956页面。至少10分钟连续观察，无新OOM/restart、资源越线、健康错误或授权漂移。自然计划任务随原Beat恢复，禁止额外人工抓取或对外发信。
8. 归档新intent/manifest/complete、备份SHA/TOC、artifact及验收记录，确认共享锁释放；最后释放coordinator。dump目录验证不冒充整库恢复验收。

## 失败与回滚边界

promotion在排空前记录Beat实际状态；若进入时Beat停止，排空/备份/验证失败只恢复worker，并核验false/off及Beat停止后才释放锁。无法恢复或证明时停止worker/Beat、保留锁。进入时Beat运行的既有失败恢复行为不变。

本包采用受保护续跑或关闭态前向修复，不回退旧镜像或数据库。promotion/activation失败沿原脚本恢复false/off；证明失败时停Beat/普通worker并保留锁及证据。web尽量保持健康，race_sync_v2_worker不被归属修复扩大操作范围。不会为恢复而停止外项目worker、替换docker输出、改签旧checkout或跳过census。任何需要改变新候选、artifact、成员或安全边界的后续动作均依根AGENTS.md处理。

## 交付条件

本地回归、真实元数据只读验证、独立review、固定HEAD完整CI及候选外交付核验全部完成后，按根AGENTS.md给出一次“只合并”或“合并并执行本包”选择。本文件是待交付包，不表示已批准或已执行恢复。
