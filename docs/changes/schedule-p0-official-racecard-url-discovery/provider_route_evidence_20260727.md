# P0 官方出马页面 provider route 证据（2026-07-27）

## 1. 结论

本轮把“生成 URL”与“读取页面内容”拆成两个独立能力：

- `deterministic_url`：只用赛事基本身份和受审模板离线构造 URL，不发网络请求；
- `head_exact_path`：对候选 URL 发 `HEAD`，仅用状态码确认精确静态路径存在，不下载正文；
- `head_application_entry`：`HEAD` 只能确认应用入口存在，不能确认 hash/query 对应数据已经发布；
- `auth_redirect_unverifiable`：候选路径统一跳转认证，真假路径响应相同，不能证明精确页面存在。

只有 `head_exact_path` 的 2xx 可直接成为 `found`。`head_application_entry` 可把官方日期索引
URL 保存为 `listing_reachable`，但必须明确它是共享日期索引，不声称已确认单场出马表。
`auth_redirect_unverifiable` 仍显示“暂无”，保留候选 URL 仅供审计，不进入人工录入 URL 列。

证据时间：`2026-07-27T04:45:00Z` 至 `2026-07-27T05:00:00Z`
（`2026-07-27 12:45` 至 `13:00 Asia/Shanghai`）。

robots 证据：

- BHA `https://www.britishhorseracing.com/robots.txt`：
  SHA-256 `05216315099509ab55563fadd64456fa154c46c227c31bc67beb01d3cffc883a`；
  目标 `/racing/fixtures/upcoming/` 未被禁止，`crawl-delay: 10`。
- Equibase 实际请求 origin `https://tvg.equibase.com/robots.txt`：
  `2026-07-27T05:06:02Z` 返回 `404`、无 redirect、body 1245 bytes、SHA-256
  `dc1d54dab6ec8c00f70137927504e4f222c8395f10760b6beecfcfa94e08249f`。该 origin 未发布
  robots 规则，contract 不借用其他 origin 的规则；项目主动采用更保守的 5 秒最小间隔。
- `https://www.equibase.com/robots.txt` 仅作旁证：
  SHA-256 `c01e2df00e7d7448c534e17b7d96441fb46ee31110a3923be19973478fd6f109`；
  其 `/static/entry/` 未被禁止且声明 `Crawl-delay: 5`，但该文件不作为 `tvg` route 的
  robots 授权或 contract digest 输入。
- 本轮用户决策把零正文 `HEAD` 与自动提取页面内容明确分离；contract 只允许前者。BHA 条款
  中对自动“extract data”的限制不扩展解释为禁止零正文可达性检查；任何 `GET`/正文解析仍然
  不在授权内。

## 2. BHA

- 权威性：British Horseracing Authority 官方赛事入口。
- 官方索引：
  `https://www.britishhorseracing.com/racing/fixtures/upcoming/`
- 日期 URL 模板：
  `https://www.britishhorseracing.com/racing/fixtures/upcoming/#!/?fromdate={YYYYMMDD}&todate={YYYYMMDD}&pagenum=1`
- 变量：赛事本地日期；同一日期的多个赛事共享一个官方日期索引 URL。
- 实际页面源码显示，列表项会进一步链接到
  `racecard/#!/{fixtureYear}/{fixtureId}`、`entries/#!/{fixtureYear}/{fixtureId}` 或
  `view-races/#!/{fixtureYear}/{fixtureId}`。
- 限制：`#` 后内容不会随 HTTP 请求发送到服务器，因此有效日期与无效日期的 `HEAD` 都只检查
  同一个应用入口。该检查不能证明日期数据或单场 racecard 已发布。
- contract：允许离线构造并以 `HEAD` 确认应用入口；输出状态为 `listing_reachable`，
  `verification_scope=date_listing`。同一批去重为一次 HEAD，不下载正文。不得输出
  `confirmed_racecard`。
- 当前身份：英国 P0 事件用 `country_region + local_date + internal event_id` 绑定共享日期索引；
  不按赛事名模糊匹配。

## 3. Equibase

- 权威性：Equibase 官方静态 race card index。
- 精确模板：
  `https://tvg.equibase.com/static/entry/RaceCardIndex{TRACK_CODE}{MMDDYY}USA-EQB.html`
- 变量：官方场地代码、赛事本地日期；一个 URL 对应该场地当日完整 race card index。
- 正向 `HEAD`：
  - `RaceCardIndexDMR080126USA-EQB.html` -> `200`，`Content-Length: 140665`
  - `RaceCardIndexCNL080126USA-EQB.html` -> `200`，`Content-Length: 143741`
- 负向 `HEAD`：
  - `RaceCardIndexZZZ080126USA-EQB.html` -> `404`
  - `DMR010126USA-EQB.html` -> `404`
- 对照结论：状态码能区分已生成的精确静态路径与不存在路径；无需下载正文。
- contract：`verification_method=HEAD`、`verification_scope=track_date_racecard_index`；
  2xx 为 `found`，404 为 `not_published`，429/5xx/超时为 `source_error`，其他状态 fail closed。
  同一 host 请求间隔至少 5 秒。contract digest 必须绑定 `tvg` robots 404 的状态、证据时间、
  body SHA、method、host/path、2 次批次上限与最小间隔；不得绑定 `www` robots SHA 冒充。
- 当前身份：生产 P0 事件已有 `track_code=DMR/CNL` 与 `local_date=2026-08-01`。provider
  event identity 为 `track_code + local_date`，不需要猜单场号。
- `www.equibase.com` 对有效和无效路径都返回相同的通用 200 页面，不能用于判定；route 必须
  精确限定为 `tvg.equibase.com`。

## 4. France Galop

- 权威性：France Galop 官方马场与会议入口。
- Deauville 官方马场页：
  `https://www.france-galop.com/fr/hippodromedeauville`
- 该官方页列出的会议 URL：
  `https://www.france-galop.com/fr/courses/reunion/20260802/UUI1MEN3bUdDZ09lcDluYm41NGxndz09`
- 模板变量：本地日期；尾部 token 是 France Galop 对 Deauville 的官方稳定场地标识，可在
  registry 中按精确场地映射保存，禁止从名字近似推断。
- 访问对照：有效日期、无赛事日期、远期日期和伪 token 均返回相同 `302` 认证跳转；
  因而 `HEAD`/最小 GET 均不能证明目标会议页面已发布。
- contract：保留受审模板和场地 token 映射，但当前为
  `auth_redirect_unverifiable`；不得因 302 报告 `found`。任务显示
  `暂无（path_unverified）`。

## 5. 其他已登记地区

- JRA：保留未来接入 contract；本轮无当前 P0，未启用网络 route。
- NAR：`robots.txt` 明确禁止 `/KeibaWeb/TodayRaceInfo/`，保持 blocked。
- HKJC：保留日期、马场、场次 contract；本轮无当前 P0，未取得可判定正向/负向页面的证据。
- Del Mar：官方赛场入口
  `https://www.dmtc.com/racing/entries/{YYYY-MM-DD}` 已验证当前 DMR 页面存在并包含当日
  entries；可作为 Equibase 的独立官方赛场 fallback，但本轮先采用无需正文的 Equibase HEAD
  contract，避免同时命中两个 provider。

## 6. 当前窗口预期

生产只读清单在本轮证据时间内共有 6 场 P0：

- 英国 3 场：输出同日期的 BHA 官方索引 URL，状态 `listing_reachable`；
- 美国 2 场：Equibase 精确静态页面 `HEAD 200`，状态 `found`；
- 法国 1 场：候选会议 URL 无法用状态码区分真假，显示“暂无”；
- 日本、香港：当前窗口 0 场，但 adapter/contract 保留。

这意味着 provider route 补齐后的当前可用人工 URL 覆盖预期为 `5/6`，其中
`confirmed_racecard=2`、`listing_reachable=3`、`暂无=1`。上线前必须用相同 contract 做一次
有界 no-write proof；若实际响应不同则 fail closed，不沿用本文件的历史成功。
