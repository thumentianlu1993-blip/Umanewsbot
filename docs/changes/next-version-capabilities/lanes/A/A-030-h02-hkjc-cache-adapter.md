# A030：HKJC 既有缓存格式到 H02 的旁路实现

任务 A030-H02-HKJC-CACHE-ADAPTER-IMPLEMENT-001。固定base `2e7b78559f4ebf74f524763d1b3f61ad4a1c03ba`，原R af5bfb20 APPROVED_PLAN_ONLY；按A029实施，只新增adapter、独立测试和本A报告，不改既有producer/models/views/settings/mapping/旧fixture。原A028纯函数和A029包保持。用户后台/QQ暂缓、共用可靠性核心保留；授权仅本地开发/测试/演示/提交，无生产/抓取/付费/外发/4GiB隔离或合并动作。

## 可用的转换

`stable.services.horse_source_cache_reuse_adapter.adapt_hkjc_source_cache(raw_bytes, *, expected_sha256, ref, source_ref)` 返回H02八字段record；失败仅抛固定码 `CacheReuseAdapterError.code`，不携带原件/敏感URL/异常repr。不读路径或构造client。

顺序：bytes且≤128KiB →独立期望SHA完整/匹配（解析及validator之前）→定位key →严格UTF-8/JSON（重复key/NaN/Infinity拒绝）→v2/香港/HKJC adapter scope →稳定ID/唯一URL HorseId →fetched_at明确UTC →既有strict canonical validator（allow_manual_supplements=False）。合法record保留原UTF-8字节文本/空白/换行/hash及旧时间，profile_id=null，不设置H01验证身份。来源只允许既有HKJC client使用的HTTPS racing.hkjc.com及English Horse.aspx路径；无userinfo/异常port/fragment/control字符或额外query，ID精确保持大小写。拒绝legacy sentinel、无ID四字段fallback，不用名称匹配/legacy兼容/normalizer补齐。

严格validator只验证既有数据格式/来源/基础/血统/别名/生涯完整性；通过不等于真实线上取数或已公开。expectedSHA由可信调用方另行固定，adapter无法判其是否独立可信，不能把“对自己算hash”升级为采集认证。真实输入清单仍待，本轮只合成fixture。strict validator依赖Django枚举和当前UTC年，测试冻结它的时钟；正式adapter保留既有validator行为，没有宣称其全年时钟不变或修改共享实现。

## 可读例子

完整字节、期望SHA、转换record/拒绝码及保留H01分母的H02结果保存在runtime examples.json；全部明确合成。

| 输入 | adapter结果 | H02结果 |
| --- | --- | --- |
| 原hong_kong.json的example.test来源 | provider_origin拒绝 | 已核目标仍保留，需刷新 |
| 独立合成副本替换固定HKJC格式URL，保留7/18旧时间 | 转换成功，profile=null | 10/03按注入1小时阈值需刷新，不带旧内容候选 |
| 字节加空格但期望SHA不变 | content_hash_mismatch拒绝 | 目标仍保留，拒绝码另存 |
| source.external_horse_id不同于URL HorseId | provider_identity_url拒绝 | 不误绑另一匹马 |
| 内容完整且转换成功，但H01没有已核身份 | record不创造身份 | insufficient，无候选 |

这些转换实际执行了新adapter和H02，但没有调用producer/fetch/network/DB/批次任务；旧fixture未改，URL替换不声称真实HKJC缓存或真实身份。没有扫描真实缓存或估算真实复用数量。

## RED/GREEN与边界

按已审A029五类矩阵新增18个Django SimpleTestCase方法：首轮空入口返回None，原件类型/拒绝及hash-before-parse断言真实失败，exit1，非导入或环境错误；RED原输出保存。首轮GREEN只有测试辅助函数对字符串提前hash的TypeError，已修测试传参，失败日志也保留。最终命令经本卡runtime `run_offline_tests.py` 配置最小Django，18 adapter＋16 H02＋21 H01共55项通过，0 skip。该驱动不加载app.settings/.env、不创建DB，DATABASES=dummy、内存/dummy cache，SimpleTestCase禁止DB；测试patch ensure_connection、socket connect/connect_ex、urlopen、旧runner/HKJC._fetch并冻结validator datetime。没有PG/生产语义声明或共享catalog修改，ROOT集成新测试catalog。

测试覆盖字节/换行/旧时间/null profile，hash先于JSON与validator，篡改/路由hash，原fixture非官方origin，严格host/path/端口/userinfo/fragment/控制字符、唯一query及same-name ID错配，缺ID/四字段fallback/legacy sentinel，坏UTF-8/JSON/嵌套重复key/非有限数/大小限制，缺时区/非UTC/未来时间，缺硬字段/partial career/manual marker，拒绝不丢目标、身份missing/retired/conflict、staging不当public、实体版本去重/顺序/所有权。变异关联沿A029：删hash或前移解析会接篡改；重dump破坏原bytes；mtime/now更新会洗旧时间；删URL-ID校验/走name或legacy会绑错马；删strict校验会接不完整；调用producer/DB网络触guard。

只有本地旁路转换通过，不代表接入旧任务、完整H02验收或公开自动链完成。未检查真实producer持久目录/来源认证收据、真实H01分母/F03矩阵或真实缓存覆盖，后续输入须由ROOT明确限定。新函数抛有限原因码，调用方汇总拒绝保留H01目标；这不是新增持久化框架或自动重抓机制。

## 交付

新runtime `/Users/mentianlu/.codex/runtime/a030-h02-hkjc-cache-adapter/` 保存驱动、RED/初轮失败/GREEN、五示例及固定index/receipt。git diff --check通过，代码与旧fixture/source validator SHA封存；仅3 repo文件，无其他线程覆盖。额度起最新7，持续≤1暂停/≤3逐批；未启动代理/模型CLI/新构建资源、购买/reset/push/PR/merge/deploy。commit hooks禁用，仅显式窄测试。交ROOT→同原R独立代码审查，本A不自签APPROVED。
