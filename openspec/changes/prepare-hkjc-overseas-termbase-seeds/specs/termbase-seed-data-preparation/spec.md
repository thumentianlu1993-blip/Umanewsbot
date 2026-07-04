## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: 候选主表必须兼容现有术语导入 CSV
系统 SHALL 生成 `seed_candidates.csv`，且该文件表头 MUST 严格等于现有术语导入字段：`term_type,source_language,racing_region,source_ja,target_zh,aliases_ja,aliases_zh,priority,is_active,notes,race_grade`。

#### Scenario: 候选 CSV 可被现有导入器预检
- **WHEN** 系统生成 `seed_candidates.csv`
- **THEN** 该文件 SHALL 可作为 `import_terms --dry-run` 的输入
- **AND** 不得包含 `source_tier`、`evidence_url` 或其他未被现有导入器支持的额外列

#### Scenario: 来源元数据写入备注
- **WHEN** 候选记录需要保留地区、来源、证据 URL、繁简转换说明或人工审核提示
- **THEN** 系统 SHALL 将这些信息写入 `notes` 字段
