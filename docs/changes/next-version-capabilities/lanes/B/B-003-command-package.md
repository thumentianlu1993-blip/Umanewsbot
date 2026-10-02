# B-003 转存接口与本地校验命令包

日期：2026-10-03，Asia/Shanghai。阶段：本地实现完成，待原R代码review；未执行生产。
承接已审15b293ce方案，范围限新模块、fake测试与B报告。人工门禁仍引用根AGENTS.md。

## 固定代码及依赖

- `scripts/f02_transfer.py` SHA256：`78b7d3965e46f61fd1f7ba533c3b1e83469019856d48acb09667d4c9d2376042`。
- `scripts/tests/test_f02_transfer.py` SHA256：`85f54d60d048fbe92922b0af077fc61047bd0d91f1c3fdd145dfb7d47d8dd9dd`。
- 固定delivery HEAD由阶段消息绑定；从Git对象提取上述模块及原exporter，禁止依赖可变化的工作树。
- 原 `scripts/f02_readonly_export.py` 与15b293ce字节一致，SHA256仍为 `fcdb8e6a130b3c98dd0ab500df6328e42d8ac817d3475a18cbdc46f79be997a5`；不引入Django、psycopg或网络依赖。
- 新模块使用Python标准库及POSIX flock/ITIMER_REAL，必须在主线程验证；遇已有timer不覆盖而停止。嵌套source验证共用外层deadline，不重置预算。
- 模块用 `python3 -m scripts.f02_transfer` 启动；部署到专属tools目录时需保留 `scripts/` 包布局并核包内每个文件SHA。当前仓库用Python namespace package，无scripts/__init__.py。本任务没有安装或生成宿主工具包；实际Python/包布局仍待协调者固定核验。

## capsule合同

capsule仅允许下列精确键，JSON≤64KiB、文件0600、绝对无symlink路径。SHA以UTF-8、sort_keys、ensure_ascii=False、结尾换行的canonical JSON计算，与exporter.encoded一致：

- schema_version=1；kind为metadata或sealed_content；observation_id为合法固定ID。
- container_id 64位；image_id=`sha256:`+64位；release_sha 40位。
- exporter_script_sha256、verifier_sha256、manifest_sha256、source_schema_sha256均64位；verifier摘要必须等于正在执行模块字节。
- container_output_root为无..的绝对路径且以runtime/next_version/F02结尾；这是远端词法路径，不能用宿主文件系统误判远端/tmp的链接状态，真实container路径由适配器实核。
- execution_uid显式整数；copy_timeout_seconds/verify_timeout_seconds为1–60。
- sealed_content另外含R托管的selection对象，绑定原metadata observation/manifest/schema/release与明确ID/input SHA/updated_at；需要完整私有source metadata目录，所有dataset/hash/count/region/time/输入重新核验。

最终producer manifest摘要取得后才形成该转存capsule；提前执行producer的capture包仍独立绑定导出代码/环境/argv/observation，不把转存capsule误称能预知查询结果。
已审exporter content收据没有script字段，本模块不改其字节；内容的script身份绑定依赖复制前后的受信probe与外部执行capsule，host对来源metadata和内容收据作独立校验。该边界待正式adapter技术核对，fake不证明现场probe真实性。

## 可注入传输接口

`transfer(capsule, artifact_root, adapter, attempt_id, source_metadata_dir=...)`；artifact_root为协调者核定的独立私有宿主目录。

- `adapter.probe(timeout=seconds)`：返回state=complete及container_id/image_id/release_sha/exporter_script_sha256/manifest_sha256/execution_uid实际证据；源消失返回source_lost，未完成返回其他state并映射capture_unknown。必须在约定时间停止自己的探针进程，不返回正文。
- `adapter.copy(private_destination, timeout=seconds)`：从精确源ID+capsule output_root+obs复制到本模块刚创建的stage；本模块不执行shell，不解析任意shell string。实际形式仍是已审 `docker cp <bound-ID>:<bound-root>/<obs>/. <private-stage>/`，但真实runner/路径/argv尚未绑定或运行。
- adapter必须执行并收回自身进程的超时；callback阻塞不能由Python调用者安全强杀。本模块另检查copy/probe返回后的耗时；自身bundle验证使用真正SIGALRM wall clock deadline。
- 不自动重试copy；中断返回unknown，保留source.commit及stage。再次调用先检查同一final/receipt/stage，不再复制；换attempt ID不能绕过unknown或invalid包。方案允许最多3次受控恢复，本实现更保守：需要新copy的异常由协调者核查新capsule/attempt方案，不能机械绕过。
- OS flock串行化同一artifact root，记录owner uid/pid、B-003、operation、代码SHA、资源路径、时间及自动释放方式。此artifact锁不替代生产发布锁。

## 本地只读命令

在核过的固定tools工作目录中，以下为结构化argv（槽位尚未绑定，无执行授权含义）：

```json
["python3","-m","scripts.f02_transfer","verify","--capsule","<ABS_PRIVATE_CAPSULE_JSON>","--bundle","<ABS_PRIVATE_OBSERVATION_DIR>"]
```

sealed_content加 `--source-metadata-dir <ABS_PRIVATE_SOURCE_METADATA_DIR>`。
已转存宿主final与transfer.complete交叉核对用：

```json
["python3","-m","scripts.f02_transfer","inspect","--capsule","<ABS_PRIVATE_CAPSULE_JSON>","--artifact-root","<ABS_PRIVATE_HOST_ARTIFACT_ROOT>"]
```

CLI只返回计数/摘要/固定错误码，不输出行数据、异常正文或凭据。没有transport命令，也没有从CLI创建R身份或密钥的命令。

## 持久化与R收包

宿主目录为artifact_root/capsule_sha；attempt stage及source.commit持久保留。完整包逐文件fsync，再同FS rename至runtime/next_version/F02/obs，fsync两个父目录，最后原子写transfer.complete并fsync。final存在时重算所有hash、检查唯一source commitment与receipt；相同包复用，损坏或冲突停止，禁止覆盖。
`host_verified`仍是R未收状态；独立的 `record_delivery` API接受精确capsule/manifest/obs/received_at绑定的R回执及来自可信custodian调用面的独立HMAC密钥，缺认证或错签名拒绝。
密钥不能来自producer/adapter/capsule，也不落artifact或stdout；当前只用了合成密钥测试，没有创建真实密钥/身份/权限。正式custodian认证材料如何由既有可信面提供仍待协调者/R绑定；本实现不自签R收到。R.received与producer/host收据分别保存。
转存验证不改变model/machine/human标记，也不证明原始内容预算、脱敏语义或gold真实性：原文被去掉部分无法恢复，原始预算依赖固定exporter执行证据。

## 待核与禁止推断

原R需review新模块/测试、HMAC认证调用边界和host工具包布局；协调者需固定实际路径/owner/空间、resident身份、正式probe/copy runner及超时/进程回收合同、capsule SHA和R托管路径。未绑定前不执行。
目前只有本地合成故障证据；无真实Docker/SSH/DB动作、没有持久host现场收据、没有R真实收包、没有Linux正式delivery收据，也没有新增真实样本。
