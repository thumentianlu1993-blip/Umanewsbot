# A029：现有 HKJC 单马缓存接入 H02 的最小方案

任务 A029-H02-EXISTING-CACHE-ADAPTER-PLAN-001，base `bd843f8c4320b63984a6db4cf52f8532dcbbf27a`。原R e2e02fbc 已批准 A028 LOCAL_OFFLINE_SLICE，本轮不复审旧纯函数。责任仅本A报告及专用runtime；其他线程并行，旧producer/共享models/views/settings/冻结runtime不改。只读源码和一份仓库测试fixture，未读生产DB、真实缓存目录、敏感原件或扩抓；无接入执行/测试/模型调用/4GiB构建。后台与QQ暂缓沿用。

## 推荐的一个接入点

复用 `p0_horse_completion_adapters.run_p0_horse_completion_adapter` 已有的 **HKJC `p0-horse-source-cache.v2` 单马JSON**，但下一片新增旁路离线适配函数，不调用该runner。实际链路为：

1. `p0_horse_completion_prepare._request_from_candidate` 形成provider-bound request；`p0_horse_completion_cache_path` 将candidate_key做SHA256得到 `<digest>.json` 路由。这个digest是**候选键哈希，不是内容hash或身份验证**。
2. `_HKJCClient._fetch` 要求 hkjc + external ID，构造 `https://racing.hkjc.com/racing/information/English/Horse/Horse.aspx?HorseId=<id>`；既有client产出 canonical source payload。下一片只读这种既有格式，不构造client、不调用fetch/transport。
3. runner经 `validate_p0_horse_source_cache` 校验后，`_write_source_cache_atomically` 写canonical UTF-8 JSON（排序/紧凑分隔/末尾换行），flush/fsync、临时文件link/replace；`_read_cache`只读JSON object。缓存本身保留source时间，**不带独立原件SHA及producer认证收据**。
4. 新 `stable.services.horse_source_cache_reuse_adapter.adapt_hkjc_source_cache(raw_bytes, *, expected_sha256, ref, source_ref)`（待实现）只接收调用方已限定的单份字节，返回一个H02 record或固定拒绝码；随后调用已批准 `plan_cache_reuse`，不改旧producer/runner，也不触发任务或公开发布。

## 字段与可信边界

| H02字段 | 唯一出处及约束 |
| --- | --- |
| content | 原件bytes严格UTF-8解码，保留空白/末尾换行；不能解析后重新dump冒同一原件 |
| content_sha256 | 对原bytes SHA256与调用方明确固定的expected_sha256比较，匹配才填写；若只现算自身hash而无独立期望值，拒绝content_hash_unbound |
| horse_key | 只用source.name=`hkjc`和非空source.external_horse_id构成`hkjc:<id>`；与原URL唯一HorseId及固定HKJC host/path一致；不casefold外部ID、不取名字/血统或legacy sentinel |
| profile_id | 固定null，producer不自称已绑定profile；H02只按H01已验证身份解析profile。H01身份不足/冲突仍留分母且无可复用候选 |
| source_time | source.fetched_at，必须显式带时区且满足既有strict validator的UTC条件；不取mtime/当前时钟/批次启动时间。旧日期仍旧日期，H02按注入as_of/age分类 |
| parse_status | 仅完整通过现有 `validate_p0_horse_source_cache(..., allow_manual_supplements=False)` 后为complete；不因合法JSON/缓存存在就叫complete，不使用legacy兼容、名称匹配或normalizer自动补值 |
| ref/source_ref | 调用方给定稳定、受H02 key约束的原件定位ID；可绑定已固定文件/收据hash；不能把不受控绝对路径或URL凭据塞入输出 |

完整validator检查schema/region/adapter、来源、基础资料、二代血统、别名、生涯总数/逐条核心证据及实际出赛数一致、manual supplement标记等。它允许外部ID缺失但“四字段血统身份完整”的旧形态；**本适配额外要求外部稳定ID**，不把这一兼容当H02强身份。validator的source URL目前只检查HTTP URL及provider名称，故适配额外按既有 `_HKJCClient.allowed_hosts={'racing.hkjc.com'}` 与固定单马path/唯一HorseId绑定；拒userinfo/非HTTPS/异常port/fragment/多HorseId和非provider原件。URL与hash仍不是来源真实性证明，可信前提是调用方提供受控既有producer原件与独立固定摘要，H01提供已核身份；此函数不能给任意本地JSON签名或升级权限。

expected_sha256可由下一片明确限定输入清单固定，不创建通用manifest框架；它证明本次指定字节未替换，不证明历史采集时已签名或真实线上完整。真实文件若没有这种可信输入绑定，保留拒绝；不得临时扫描目录补hash后声称历史原件已认证。现阶段不存在获准的真实缓存清单，实际可复用数量未知。

## 拒绝与 H02 衔接

新适配不做网络fallback：bytes>128KiB、非bytes、UTF-8/JSON损坏或重复JSON key/NaN、原件SHA缺失/不符、非v2/HKJC、缺ID/URL-ID不一致、source时间缺失/无时区、strict validator失败均固定码拒绝且没有record。拒绝汇总仍带ref和有限原因，不输出原异常文本/敏感URL；不得从错误中读目录或补空字段。caller保留完整H01目标，适配失败不删除目标分母；H02可对已核身份但没有合格缓存给refresh_required，旁边保留adapter拒绝码以区分损坏、缺证和不支持。身份未核即使内容完整仍不足，不能由adapter制造verified identity。

已有validator依赖Django模型枚举及adapter模块，且birth_year上界使用当前UTC年；下一片只调用验证函数、不调用source client。测试在现有隔离Django SimpleTestCase下冻结该validator时钟并禁止任何DB/network；这里不把共享import改成新框架，也不改已批准H02纯函数。H02新鲜度仍由调用方强制注入，无默认TTL。首片限定香港单provider，其他地区、补源合并、parser升级策略和字段级局部复用后置，严格validator失败不冒“部分也足够”的新业务标准。

## 样例与最小测试

唯一只读fixture：`server/stable/fixtures/p0_horse_completion/hong_kong.json`，显式example.test、HK-001/HARBOUR TEST及测试血统，2026-07-18旧source时间；是仓库合成合同样例，**不是实际HKJC历史快照**。其基本字段和生涯证据完整性由旧测试使用；本轮未执行validator或旧整组，不能记新的PASS。按新origin约束原fixture应拒provider_origin，不改旧fixture。下一片正向例仅在独立测试副本中替换为固定HKJC格式URL并重算测试期望hash，保留旧时间，明确仍合成；H01的验证身份另用合成已核snapshot，绝不声称验证了真实马。

最小RED→GREEN测试：

1. 对完整受控合成v2字节，精确保留内容/换行/hash、HKJC稳定ID和来源旧时间，接H02得需刷新（非mtime更新）；另显式注入时钟/阈值证明可复用边界。
2. example.test原fixture、错误host/path、URL不同或重复HorseId、同名异ID、缺外部ID但四字段完整、legacy sentinel均不能误生成强身份record。
3. 缺/错expectedSHA及一字节篡改、坏UTF-8/JSON/重复key/NaN/超界内容拒绝，不触fetch、任务、DB或补抓；hash验证在解析之前。
4. 缺/无时区/未来source_time、partial career/缺必需字段/manual supplements拒绝或由H02不足（未来时间不改写）；不从名称fallback或normalizer补齐。
5. 同一原件/实体版本重复及顺序重排候选相同；H01 unresolved/conflict/retired身份仍无候选；staging-only不变public。

变异：跳过expectedSHA会接受篡改；重dump会改变原件；用mtime/current time会把旧缓存冒新；移除ID/URL绑定会合错马；走legacy/name fallback会绕强身份；只看JSON会接部分/手工补录；validator/client混用会触发网络。下一片预期仅新增adapter服务/独立测试及A报告，不改旧producer或共享入口；实际fixture接入而非生产批次。待ROOT→原R方案快审及下一片派单，不先实施。
