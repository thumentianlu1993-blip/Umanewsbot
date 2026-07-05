# termbase-seed-data-preparation Specification

## Purpose
定义从 HKJC 体系与 WP Stud 等来源准备中文术语种子候选的受控流程，确保候选文件可审核、可追溯、兼容正式术语导入，并且不会在种子准备阶段直接写入生产术语或触发新闻发布链路。
## Requirements
### Requirement: 系统必须从 HKJC 和 WP Stud 准备术语种子候选
系统 SHALL 提供受控的术语种子数据准备能力，从 HKJC 体系和 WP Stud 抽取含中文译名的赛马术语候选，并生成供人工审核的本地文件。第一版术语类型 SHALL 限定为 `horse`、`race`、`jockey`、`trainer`、`racecourse` 和 `fixed_phrase`。第一版 HKJC 抽取 SHALL 只承诺稳定 HTML/文本入口，不承诺 `racecards` PDF 或排位表全量抽取。

#### Scenario: 生成第一批来源候选
- **WHEN** 运维人员执行术语种子准备命令并选择 HKJC 与 WP Stud 来源
- **THEN** 系统生成覆盖支持术语类型的候选记录
- **AND** 系统不得生成 `owner`、`farm`、`org` 或其他未纳入第一版范围的候选类型

#### Scenario: 未选择来源时拒绝执行
- **WHEN** 运维人员未指定 HKJC 或 WP Stud 任何来源执行命令
- **THEN** 系统 SHALL 拒绝执行并提示需要选择至少一个支持来源

#### Scenario: 不支持的首版来源被排除
- **WHEN** 运维人员请求首版未支持的 HKJC PDF/racecard 全量抽取
- **THEN** 系统 SHALL 拒绝或跳过该来源
- **AND** 输出摘要 SHALL 标记该来源为 deferred 或 unsupported

### Requirement: HKJC overseas simulcast 来源必须可生成术语种子候选
系统 SHALL 在现有术语种子准备流程中支持 `hkjc_overseas` 来源，从 HKJC overseas simulcast Race Card 准备海外术语候选。

#### Scenario: 显式选择 hkjc_overseas 来源
- **WHEN** 运维人员执行 `prepare_termbase_seed_data --source hkjc_overseas`
- **THEN** 系统 SHALL 使用现有审核文件输出流程生成 HKJC overseas 候选
- **AND** 系统 SHALL NOT 要求同时选择 `hkjc_local_horses` 或 `wpstud`

#### Scenario: hkjc_overseas 不写正式数据表
- **WHEN** `hkjc_overseas` 来源生成候选文件
- **THEN** 系统 SHALL NOT 创建、更新或删除 `TermEntry`、`TermAlias`、`ExternalHorse` 或 `ExternalHorseAlias`
- **AND** 系统 SHALL NOT 派发翻译、发布或 QQ 推送任务

### Requirement: HKJC overseas 必须支持自动发现 Race Card
系统 SHALL 支持自动发现 HKJC overseas 当前可见 Race Card，并在触网边界内低频抓取。

#### Scenario: 默认自动发现当前 Race Card
- **WHEN** 运维人员传入 `--source hkjc_overseas --allow-network` 且未指定具体 Race Card
- **THEN** 系统 SHALL 自动发现 HKJC overseas 当前可见 Race Card
- **AND** 默认 SHALL 最多处理前 3 个 race card
- **AND** 系统 SHALL 在 `summary.json` 记录发现数量、处理数量和请求数量

#### Scenario: 使用限制参数控制抓取范围
- **WHEN** 运维人员传入 `--limit-meetings`、`--limit-races`、`--max-requests` 或 `--request-interval-seconds`
- **THEN** 系统 SHALL 按这些参数限制 HKJC overseas 发现与抓取范围
- **AND** 达到请求上限时 SHALL 停止继续请求并在 `summary.json` 标记结果可能不完整

#### Scenario: 支持精确指定 Race Card
- **WHEN** 运维人员重复传入 `--hkjc-overseas-race RaceDate=YYYY-MM-DD,Racecourse=<code>,RaceNo=<number>`
- **THEN** 系统 SHALL 只抓取这些指定 Race Card
- **AND** 输出证据 SHALL 保留每个指定 Race Card 的参数

#### Scenario: 精确 Race Card 参数格式错误时拒绝执行
- **WHEN** 运维人员传入无法解析为 `RaceDate`、`Racecourse` 和 `RaceNo` 的精确 Race Card 参数
- **THEN** 系统 SHALL 拒绝执行并提示参数格式错误
- **AND** 系统 SHALL NOT 静默回退到自动发现

#### Scenario: Race Card 未有资料时跳过
- **WHEN** HKJC Race Card 页面可访问但显示未有资料或等价状态
- **THEN** 系统 SHALL 在 `summary.json` 的 `skipped_races` 中记录该 Race Card
- **AND** 跳过原因 SHALL 为 `race_card_not_available`
- **AND** 该情况本身 SHALL NOT 将整批结果标记为失败

### Requirement: HKJC overseas 首版候选必须覆盖马名骑师和赛事名
系统 SHALL 从 HKJC overseas Race Card 生成 `horse`、`jockey` 和 `race` 三类术语候选。

#### Scenario: 生成海外马名候选
- **WHEN** 英文 Race Card 和繁中 Race Card 中存在可对齐的同一匹马
- **THEN** 系统 SHALL 生成 `term_type=horse` 的候选
- **AND** `source_language` SHALL 为 `en`
- **AND** 英文马名 SHALL 写入原文字段
- **AND** 繁中马名转换后的简体中文 SHALL 写入 `target_zh`

#### Scenario: 生成海外骑师候选
- **WHEN** 英文 Race Card 和繁中 Race Card 中存在可对齐的同一名骑师
- **THEN** 系统 SHALL 生成 `term_type=jockey` 的候选
- **AND** `source_language` SHALL 为 `en`
- **AND** 繁中骑师名转换后的简体中文 SHALL 写入 `target_zh`

#### Scenario: 生成海外赛事候选
- **WHEN** 英文 Race Card 和繁中 Race Card 中存在可对齐的赛事名
- **THEN** 系统 SHALL 生成 `term_type=race` 的候选
- **AND** `source_language` SHALL 为 `en`
- **AND** 繁中赛事名转换后的简体中文 SHALL 写入 `target_zh`

#### Scenario: 首版暂缓其他海外字段
- **WHEN** Race Card 中包含练马师、马主、马场、装备、负磅或评分字段
- **THEN** 系统 MAY 在证据中保留这些原始字段
- **AND** 系统 SHALL NOT 在本变更中承诺为这些字段生成候选

### Requirement: HKJC overseas 中文目标必须简体化并保留繁体证据
系统 MUST 将 HKJC overseas 的中文目标译名输出为简体中文，并保留 HKJC 原始繁体写法。

#### Scenario: 繁中马名输出为简体目标
- **WHEN** HKJC overseas 繁中页提供中文译名
- **THEN** 系统 SHALL 将转换后的简体中文写入 `target_zh`
- **AND** 系统 SHALL 在 `notes` 或 `source_evidence.json` 保留原始繁体中文

#### Scenario: 不额外生成 zh-hant 候选行
- **WHEN** HKJC overseas 同时提供英文原文和繁中译名
- **THEN** 系统 SHALL 将英文作为 `source_language=en` 的候选原文
- **AND** 系统 SHALL NOT 因繁中译名额外生成 `source_language=zh-hant` 的候选行

### Requirement: HKJC overseas 候选必须记录官方来源元数据
系统 SHALL 将 HKJC overseas 候选标记为官方来源候选，并保留人工审核所需的元数据。

#### Scenario: 官方来源备注
- **WHEN** 系统生成 HKJC overseas 候选
- **THEN** `notes` SHALL 标记 `source=hkjc_overseas`
- **AND** `notes` SHALL 标记 `source_tier=official`
- **AND** `notes` SHALL 标记 `requires_review=false`

#### Scenario: 同名同译名来源合并
- **WHEN** 多个 HKJC overseas Race Card 产生相同 `term_type`、英文原文和简体中文译名
- **THEN** 系统 SHALL 合并为一条候选
- **AND** 系统 SHALL 在 `source_evidence.json` 保留多个来源证据

#### Scenario: 同名不同译名进入冲突清单
- **WHEN** 相同 `term_type` 和英文原文对应多个不同中文译名
- **THEN** 系统 SHALL 在 `seed_conflicts.csv` 记录冲突
- **AND** 系统 SHALL NOT 静默随机选择一个中文译名

### Requirement: HKJC overseas 证据必须结构化输出
系统 SHALL 为 HKJC overseas 生成 `source_evidence.json`，记录候选、冲突、跳过与失败的结构化证据。

#### Scenario: 候选证据包含 Race Card 上下文
- **WHEN** 系统生成 HKJC overseas 候选
- **THEN** `source_evidence.json` SHALL 记录对应 Race Card 的 `RaceDate`、`Racecourse`、`RaceNo` 和语言页面 URL
- **AND** 对马名候选 SHALL 记录 horse profile 中可取得的 `h` 或 `simulcastHorseId`
- **AND** `h` 或 `simulcastHorseId` SHALL 仅作为证据而非术语去重主键

#### Scenario: 证据包含抓取方式
- **WHEN** 系统通过直接请求、脚本数据、公开接口或浏览器渲染取得 HKJC overseas 数据
- **THEN** `source_evidence.json` SHALL 记录每个 Race Card 或候选的抓取方式

#### Scenario: 渲染 fallback 不可用时失败可见
- **WHEN** 直接请求无法取得 Race Card 内容且当前运行环境没有可用渲染器或渲染后缓存
- **THEN** 系统 SHALL 在 `summary.json` 或 `source_evidence.json` 记录 `render_fallback_unavailable` 或等价原因
- **AND** 若因此无法完整处理选定 Race Card，`summary.json` SHALL 标记 `incomplete=true`
- **AND** 系统 SHALL NOT 将该 Race Card 当作空数据成功处理

#### Scenario: 失败记录不伪装为空结果
- **WHEN** HKJC overseas 请求失败、解析失败或指定 Race Card 无法取得
- **THEN** 系统 SHALL 在 `summary.json` 或 `source_evidence.json` 记录失败 URL、参数和错误原因
- **AND** 若失败导致选定来源或指定 Race Card 未完整处理，`summary.json` SHALL 标记 `incomplete=true`

### Requirement: HKJC overseas 地区映射不得扩展当前枚举
系统 SHALL 使用现有 `RacingRegion` 值为 HKJC overseas 候选填写地区，不在本变更中新增地区枚举。

#### Scenario: 已支持地区映射到现有值
- **WHEN** HKJC overseas Race Card 可识别为英国、法国、美国、日本或香港相关赛事
- **THEN** 系统 SHALL 将候选映射到现有对应 `racing_region`

#### Scenario: 未支持地区映射到 other
- **WHEN** HKJC overseas Race Card 可识别为南非、德国、澳洲、爱尔兰、韩国、阿联酋、新西兰或其他当前无枚举地区
- **THEN** 系统 SHALL 将候选 `racing_region` 写为 `other`
- **AND** 系统 SHALL 在 `notes` 或 `source_evidence.json` 保留原始国家或地区代码

### Requirement: 候选输出必须先人工审核且不得写正式表
系统 SHALL 将术语种子准备结果输出为审核文件，不得直接创建、更新或删除 `TermEntry`、`TermAlias`、`TermCandidate`、`ExternalHorse` 或 `ExternalHorseAlias`。

#### Scenario: 种子准备不写正式术语库
- **WHEN** 术语种子准备命令成功生成候选文件
- **THEN** `TermEntry` 和 `TermAlias` 计数 SHALL 保持不变
- **AND** 命令输出 SHALL 明确提示文件需要人工审核后再通过现有术语导入流程处理

#### Scenario: 种子准备不影响新闻发布链路
- **WHEN** 术语种子准备命令执行
- **THEN** 系统 SHALL NOT 派发翻译、自动评分、自动发布或 QQ 推送任务

#### Scenario: 输出目录与正式种子文件隔离
- **WHEN** 运维人员未显式指定 `--output-dir`
- **THEN** 系统 SHALL 将 `seed_candidates.csv`、`seed_conflicts.csv` 和运行摘要输出到 `runtime/termbase_seed/<timestamp>/`
- **AND** 系统 SHALL NOT 覆盖 `server/stable/data/terms_seed.csv`

### Requirement: 候选主表必须兼容现有术语导入 CSV
系统 SHALL 生成 `seed_candidates.csv`，且该文件表头 MUST 严格等于现有术语导入字段：`term_type,source_language,racing_region,source_ja,target_zh,aliases_ja,aliases_zh,priority,is_active,notes,race_grade`。

#### Scenario: 候选 CSV 可被现有导入器预检
- **WHEN** 系统生成 `seed_candidates.csv`
- **THEN** 该文件 SHALL 可作为 `import_terms --dry-run` 的输入
- **AND** 不得包含 `source_tier`、`evidence_url` 或其他未被现有导入器支持的额外列

#### Scenario: 来源元数据写入备注
- **WHEN** 候选记录需要保留地区、来源、证据 URL、繁简转换说明或人工审核提示
- **THEN** 系统 SHALL 将这些信息写入 `notes` 字段

### Requirement: 冲突清单必须独立于候选主表
系统 SHALL 生成 `seed_conflicts.csv` 记录人工审核所需的译名冲突、来源差异和推荐处理结果。冲突清单 MUST NOT 被设计为可直接导入正式术语库的文件。

#### Scenario: HKJC 和 WP Stud 译名不同
- **WHEN** 同一候选实体在 HKJC 与 WP Stud 中存在不同中文译名
- **THEN** 系统 SHALL 在 `seed_conflicts.csv` 记录 HKJC 译名、WP Stud 译名、推荐主译名、候选别名、来源证据和冲突类型

#### Scenario: 候选主表保留推荐结果
- **WHEN** 冲突清单中存在推荐主译名
- **THEN** `seed_candidates.csv` SHALL 只保留推荐后的主候选和别名
- **AND** 冲突细节 SHALL 保留在 `seed_conflicts.csv`

### Requirement: 来源优先级必须区分官方和民间来源
系统 MUST 在合并候选时优先使用 HKJC 译名作为主译名，WP Stud 译名作为民间来源补充。只有 WP Stud 有译名时，系统 MAY 生成主译名候选，但必须标记为需要人工审核。

#### Scenario: HKJC 和 WP Stud 同时存在
- **WHEN** 同一实体同时有 HKJC 和 WP Stud 中文译名
- **THEN** 系统 SHALL 使用 HKJC 中文译名作为 `target_zh`
- **AND** 系统 SHALL 将 WP Stud 中文译名作为 `aliases_zh` 或写入 `notes`

#### Scenario: 只有 WP Stud 存在
- **WHEN** 某实体只有 WP Stud 中文译名
- **THEN** 系统 SHALL 生成候选记录
- **AND** `notes` SHALL 标明 `source_tier=community` 与 `requires_review=true`

### Requirement: 中文目标译名必须输出为简体中文
系统 MUST 将所有 `target_zh` 输出为简体中文。若来源中文译名为繁体中文，系统 SHALL 执行繁简转换，并保留原始繁体证据。

#### Scenario: 繁体 HKJC 译名转为简体目标译名
- **WHEN** HKJC 来源返回繁体中文马名 `美麗傳承` 或其他繁体中文译名
- **THEN** 系统 SHALL 在 `target_zh` 写入对应简体中文
- **AND** 系统 SHALL 在 `notes` 或 `seed_conflicts.csv` 保留原始繁体写法

#### Scenario: 英文原文不被繁简转换破坏
- **WHEN** 候选原文语言为 `en`
- **THEN** 系统 SHALL 保持英文 `source_ja` 原文大小写和空格语义
- **AND** 仅对中文目标译名和中文别名执行繁简转换

### Requirement: 多语言原文必须按 source_language 分行输出
系统 SHALL 支持同一术语概念以多行候选表达不同原文语言。每行只能有一个 `source_language`，并且必须使用现有支持的语言值。

#### Scenario: 同一香港马匹输出英文和繁体中文候选行
- **WHEN** HKJC 来源同时提供英文马名和繁体中文马名
- **THEN** 系统 MAY 生成一行 `source_language=en` 的英文原文候选
- **AND** 系统 MAY 生成一行 `source_language=zh-hant` 的繁体中文原文候选
- **AND** 两行的 `target_zh` SHALL 均为简体中文译名

#### Scenario: 日文来源排在最后处理
- **WHEN** 候选来源包含日本相关术语
- **THEN** 系统 SHALL 在地区排序中将日本候选排在香港和其他国际地区之后

### Requirement: 地区处理顺序必须香港优先日本最后
系统 SHALL 按地区顺序组织候选生成和输出。香港候选必须优先输出，日本候选必须最后输出，中间地区可按实现便利度排序。

#### Scenario: 输出文件地区顺序稳定
- **WHEN** `seed_candidates.csv` 同时包含香港、英国、法国、美国、澳纽、其他和日本候选
- **THEN** 香港候选 SHALL 排在最前
- **AND** 日本候选 SHALL 排在最后

### Requirement: 触网抓取必须显式启用并保留请求边界
系统 MUST 要求运维人员显式传入 `--allow-network` 才能访问外部网站。触网执行 SHALL 支持请求上限、请求间隔、请求超时和输出目录参数，并在产物或摘要中记录来源、请求数量和失败摘要。

#### Scenario: 未允许网络时不触网
- **WHEN** 运维人员未传入 `--allow-network` 执行命令
- **THEN** 系统 SHALL NOT 请求 HKJC 或 WP Stud 网络页面
- **AND** 系统 SHALL 只允许读取 fixture、缓存文件或本地输入

#### Scenario: 达到请求上限时停止
- **WHEN** 触网执行达到配置的最大请求数
- **THEN** 系统 SHALL 停止继续请求
- **AND** 输出摘要 SHALL 标记本次结果可能不完整

#### Scenario: 网络失败被记录且不伪装成功
- **WHEN** HKJC 或 WP Stud 请求返回非 2xx、超时或解析失败
- **THEN** 系统 SHALL 在运行摘要中记录 URL、来源、状态码或错误原因
- **AND** 对应来源的结果 SHALL 标记为不完整
- **AND** 系统 SHALL NOT 把该来源的缺失结果当作空数据成功

### Requirement: 来源入口必须可追溯
系统 SHALL 在实现解析器前固定本轮使用的 HKJC 与 WP Stud 入口、样本和可抽取字段，并在 fixture、测试或文档中保留证据。

#### Scenario: 来源 spike 固定解析范围
- **WHEN** 实施人员新增 HKJC 或 WP Stud 解析器
- **THEN** 对应解析器 SHALL 有本地 fixture 或缓存样本
- **AND** 测试 SHALL 说明样本覆盖的实体类型、原文语言和中文译名字段
