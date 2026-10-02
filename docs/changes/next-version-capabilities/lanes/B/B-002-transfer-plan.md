# B-002 容器临时输出与宿主转存适配方案

日期：2026-10-03，Asia/Shanghai。阶段：方案可审，未执行、未实现转存wrapper/verifier。
本方案补充 `910353a51685310c5dc6bcf7ea8ca3d3c1a18880` 的三P2返修；现有导出脚本字节不变。
不改 Compose、挂载或服务，不借用马匹资料目录，不新增采样/权限/模型调用。人工门禁仍以根AGENTS.md为准。

## 最新运行证据与旧模板失效

协调者 O01 只读核验提供（本线未重复探测）：

- resident web ID：`9f03d1faa0ccf681d50dd2a9db6018af55a33937bf94517b0d447f453ac2190c`。
- marker/image revision：`ad50abdb74b89669ab8ada2958b040877c1a1849`。
- image：`sha256:73ee1dcf7edb5b7c7bda49f5d6baedffe030d639fcc5bf191b831ece6e9f5930`。
- 仅有 `/app/runtime/horse_profile_completion` 的 runtime 挂载；不存在预期通用 `/app/runtime/next_version/F02` 宿主持久挂载。
- 后续协调者只读核验：`psycopg_available=true`，POSTGRES_HOST/PORT/DB/USER/PASSWORD五键均存在（未读取或输出值），执行uid为0，`/tmp`可写，`/app/runtime`存在。
- DB二进制版本为PostgreSQL 16.14；尚未执行DB查询，不据此声称schema或连接已经验证。

这些是时点证据，真实执行前仍核对 ID/image/revision；没有把容器健康当作DB/样本完成证明。
旧命令包中依赖持久 runtime mount 的模板失效，不能直接执行；以上ID也不是允许忽略后续漂移的常量。

## 两层目录与直接交R

1. 容器 staging 建议独占目录 `/tmp/umanews-f02-910353a5-t01/`，owner绑定协调者任务，0700；已存在时先查该capsule状态，不覆盖、不复用其他任务目录。
   固定脚本放 `tools/f02_readonly_export.py`；原selection及经宿主验证的metadata回传放独立input路径，0600。
   OUTPUT_ROOT 为 `/tmp/umanews-f02-910353a5-t01/runtime/next_version/F02`，满足现有脚本绝对路径/无symlink/固定后缀约束，无需改脚本。
2. 宿主 artifact 建议独占 `/opt/umanews-artifacts/F02-capsules/<capsule-sha>/`，实际目录可用性/owner/空间由协调者只读核对后绑定；不能借用现有horse挂载。
   最终包路径为 `runtime/next_version/F02/<observation-id>/`，0700目录/0600文件。这个目录是任务artifact，不是服务挂载或业务数据库。
3. 同一既有SSH通道只传固定脚本、受控input与artifact。正文程序仅落容器文件；随后host侧 `docker cp` 从精确容器ID拷入私有staging目录，正文不经过工具stdout。
   B收到计数/manifest/transfer摘要；完整metadata与原始内容路径/包直接交协调者/R，B不读待划分全集或保留集。
4. metadata宿主持久验收通过后，R从该不可变包给selection及SHA。content运行前必须把完整metadata（含manifest/receipt全部文件）复制回原容器input OUTPUT_ROOT对应source_observation_id目录并再验SHA。
   新P2-02代码会验证实际来源包，而不是只信文件名或摘要形状；selection仍绑定同一metadata/schema/release/observation/cohort。
   容器重建时不自动换目标或重读DB；先走下文漂移/丢失判断。若协调者批准在兼容新容器读取内容，也须重新绑定容器/image/release并复验每篇输入，不能修改原T的metadata。

## 固定命令包形状（不是可执行批准）

capsule需包含script HEAD/SHA、上述实核容器/image/release、执行user、container/host目录、observation ID、selection/source摘要、所有argv和传输预算。
当前仅给模板；新wrapper/verifier尚未提交，不能把下面状态判断当已实现能力。

metadata live argv适配为：

```json
["docker","exec","9f03d1faa0ccf681d50dd2a9db6018af55a33937bf94517b0d447f453ac2190c","python","/tmp/umanews-f02-910353a5-t01/tools/f02_readonly_export.py","--mode","metadata","--output-root","/tmp/umanews-f02-910353a5-t01/runtime/next_version/F02","--observation-id","F02-20261003-metadata-01","--expected-script-sha256","fcdb8e6a130b3c98dd0ab500df6328e42d8ac817d3475a18cbdc46f79be997a5","--expected-release-sha","ad50abdb74b89669ab8ada2958b040877c1a1849"]
```

该argv只有在staging、capsule及独立verifier审过并重新核容器后才可执行；输出仍是容器producer收据，不是最终交付收据。
传输argv形状为 `docker cp <bound-web>:<container-output-root>/<obs>/. <host-private-stage>/runtime/next_version/F02/<obs>/`。
host-private-stage新建且专属于本capsule/transfer attempt；实际路径先做无symlink/空目录/权限/空间核验。
复制按文件目录进行，不在模型工具中解码原文；如果使用tar传输，解包须拒绝绝对路径、`..`、symlink/hardlink及额外文件，不能直接通用tar解包不可信内容。

## 转存校验与最终receipt

producer manifest SHA由成功stdout收据或只读摘要探针取得；探针仅返回固定obs的文件摘要/计数，不打印正文。
复制前后source manifest SHA必须一致；host独立verifier从stage检验：

- manifest SHA等于固定source承诺；schema_version/kind/complete/observation吻合；精确文件清单，无额外文件/链接/非regular文件。
- receipt及全部文件SHA重算；receipt observation/script/release与capsule对应。metadata分母/cohort/schema链、content来源manifest/schema/selection链都能核验。
- 元数据沿现有预算；校验文件总量≤128MiB、cohort≤16MiB、单个其余metadata≤64MiB；content≤30MiB+有界receipt/manifest，单篇预算不放宽。
- 文件0600、目录0700、路径无symlink；host空间至少是包预算+一次staging副本，实际余量不足停止复制，不删其他任务产物。
- schema/hash/数量/时间对账与脱敏/标签状态缺口如实保存；转存验收不意味着gold/独立机器或人类事实核验已完成。

通过后，在同一宿主filesystem把stage内完整observation目录原子rename到固定final目录；final已存在时核capsule/manifest，相同复用已有结果、不同则冲突停止，禁止覆盖。
final receipt单独放capsule控制目录，字段包含：capsule SHA、source container/image/release、obs、producer manifest SHA、host包manifest SHA、verification方法/SHA、artifact绝对路径、传输尝试ID、阶段/时间与R交接状态。
先原子保存 `transfer.complete`，再回传仅摘要；写控制receipt失败则完成状态待核，不能把数据rename成功猜作receipt成功。
R读取/确认收到对应immutable包后才记 `delivered_to_R`。producer成功、host验收成功、R收包三种状态分别保留。
最终F02可消费收据至少要求host验证与持久化完成；仅容器文件或stdout complete不够。

## 异常状态与恢复（不盲重采）

| 状态 | 判据 | 下一步 |
|---|---|---|
| produced_not_transferred | 容器完整manifest已核，host没有完整包 | 原obs继续复制，禁止再次DB采集 |
| transfer_unknown | SSH/docker cp超时，host有stage或receipt返回丢失 | 查固定final/transfer receipt/stage摘要及复制进程；先核实际结果，不能新开并行复制 |
| host_verified | final与transfer.complete匹配，回传可能丢失 | 复核同一摘要后重发摘要/交R，不重采、不覆盖 |
| capture_unknown | 查询传输中断，producer是否结束未知 | 只核本capsule进程/manifest，证实退出后再处理；不重启生产容器 |
| source_lost | 绑定容器消失且host无已验证final包 | 保留原obs、已获manifest/receipt和缺口；标未交付/原快照丢失，不能伪造成功 |
| invalid_package | 缺/错文件、hash、预算或身份漂移 | 留受控诊断摘要，隔离该attempt，定位确定性问题；不机械同命令重试 |

source_lost若host已有完整可验stage，先独立核验；source承诺不足则保持unknown。只有证据足够才提交final。
若确需重新只读采样，由协调者安排新observation T2，同原T1丢失记录并列；不能覆盖原obs或把T2说成T1恢复，也不因为时间经过自动重读。
瞬时传输错误核对实际状态后最多3次（2秒/5秒），每次有attempt ID，复用原immutable producer包；确定性错误修正后复验。
不删容器stage直到host验收和R交接完成；随后只清理本capsule的精确临时目录，不改服务，不碰其他线程文件。
这些artifact文件不是资源锁，不替代既有协调/生产锁；本任务无服务发布面动作。

## 待实施与离线验证

请协调者与原R审此适配；通过后B才实现本线transfer wrapper/verifier和离线fake测试，再给新固定SHA/字面capsule技术核对。
至少覆盖：复制中断/回传丢失、已存在同包幂等/不同包冲突、copy后源hash变化、额外/链接文件、空间不足、容器消失但host已有包、容器/host都丢失、receipt原子提交失败。
fake用合成目录，不读取真实保留集；不会以状态表的描述冒充恢复代码或现场验收。
本方案只是输出/传输适配，原only-read DB、R托管、无Djangoimport、字节与180秒查询预算保持；复制/校验阶段另设有界超时（建议各60秒、至多3次），不延长DB事务。
