# 代码复审

## 范围

- 历史日期/直接来源discovery artifact
- pending首批验收选择器与selection snapshot命令
- 日期来源批准后的原子ready/materialize apply
- URL host/authority/region/provider边界
- 跨年届次与地区距离单位解析
- 对应管理命令和测试

## 返修轮次

1. 补selection snapshot绑定，禁止省略或替换难抓target；无候选目标进入gap ledger。
2. 只允许pending且未materialize目标apply；manifest候选/缺口/输入计数互相校验。
3. 复制并绑定selection、source cache manifest和request ledger原件，批准后篡改会阻断。
4. 跨年必须显式actual_year、原因且自然年差不超过1；保留届次year。
5. URL证据强制provider/authority，按adapter校验HTTPS host、重定向、地区和主赛果能力。
6. 管理命令把损坏JSON、缺文件和非法类型转换为可读CommandError。
7. 真实source spike后补逐URL成功请求与source cache identity关联；HTTP成功但反爬正文不得进入ready。
8. 详情adapter优先消费审核直链，并在缓存命中前校验候选host；所有网络重定向和最终URL继续fail closed。
9. 失败内容校验仍保留HTTP状态、最终URL和重定向链，避免失败账本丢失现场。
10. 生产首次apply暴露PostgreSQL禁止`FOR UPDATE`锁定可空外连接；锁查询移除`event` join并补专属回归，失败事务确认零写入。
11. 生产第二次apply在共享`materialize_historical_event()`暴露同类可空外连接锁；共享锁查询同步移除`event` join，仓库内已无同类查询，失败事务再次确认零写入。
12. 详情导入、冠军补录、权威字段更新和发布路径的多行锁查询同步移除可空`event` join，并以跨四个历史服务文件的静态回归防止同类问题复发。
13. 新增event input导出、netkeiba EUC-JP历史结果parser和详情候选打包器；候选逐场绑定当前target/inventory SHA、已审核result URL和逐文件验证的source cache identity。
14. 香港旧11列表格、旧两字母马匹代码、美国方括号赞助名和同URL多次capture均补真实回归；27场完整候选与9场法国gap分离。
15. 法国 ZEturf 详情网络层改用统一 HTTPS/host/重定向校验；真实缓存复审修复 2012 旧 `<span class="horse-name">` 丢行、骑师/练马师错列，以及 `Criterium de Saint-Cloud` 被宽松匹配到 `Criterium International` 的问题。修复后离线回放 2012/2025 六场均唯一命中。
16. 新增ready/materialized目标的独立detail-source artifact；批准证据同时非破坏写入target/event，packager精确匹配批准capture。复审补齐RaceEvent行锁，避免并发来源维护覆盖event.source_refs。
17. 真实Equibase探测发现`eqbPDFChartPlus.cfm`会以HTTP 200返回Incapsula反爬HTML；缓存门禁现将该CFM端点强制视为PDF，并补`_Incapsula_Resource`和`To regain access`标记，防止假成功进入source cache。
18. 新增英法IrishRacing备用详情adapter。首轮复审发现地区provider可交叉使用和并列名次可触发存储唯一约束；修复后adapter与artifact双层校验地区，并以连续存储顺序+`official_finish_position`保留官方并列位次。重新复审无剩余可修复问题。
19. 新增美国Equibase单场standard PDF详情adapter；真实样本复审补空格版表头、`1a`联合投注编号和日期/赛场/场次三重身份校验，六场官方PDF均完整解析。
20. 首轮Equibase复审发现任意本地PDF可重新缓存到已批准URL；修复为详情PDF必须精确匹配日期发现source cache中的URL、大小和SHA-256。
21. 二、三轮Equibase复审继续收紧为source cache manifest本身必须匹配target在日期apply时记录的大小和SHA-256，并且每次只允许一个已批准manifest，禁止批准manifest与其他manifest中的PDF混用。修复后重新复审无剩余可修复问题。
22. 新增年代带标准批次artifact命令。首轮复审补齐artifact层独立输入校验，拒绝空批次、重复target、年代带外目标、inventory漂移、未批准系列和非pending/materialized目标；地区进度改为按当前年代带计算。修复后重新复审无剩余可修复问题。
23. 新增JRA与TOBA/Equibase Yearbook批次来源发现及离线详情解析。真实抓取复审发现旧`tvg`静态PDF规则在2025年全部404、美国裸数字距离缺少furlong单位、详情打包器与来源artifact键契约不同；分别改用可缓存的Equibase Yearbook单场页、显式地区单位、先来源审批后重新打包的既定链路。新增JRA/Equibase来源名白名单后，20项聚焦测试和863项完整stable回归通过，重新复审无剩余可修复问题。
24. 首次生产详情apply发现Equibase多匹退赛均使用`SCR`，数据库马号唯一约束才报错。修复为稳定`SCR-n`，并在dry-run增加重复马号拒绝；864项完整回归通过后重新review，无剩余可修复问题。
25. 续跑发现Equibase官方并列名次不能直接作为唯一存储位。修复为连续`finish_position`加独立`official_finish_position`，dry-run增加重复存储位拒绝；865项完整回归通过后重新review，无剩余可修复问题。
26. 新增 NSA 官方结果 PDF 固定列解析，数字名次进入 results，F/UR/PU/RO/BD 等未完赛马只保留 runner 与状态；两场真实缓存回放得到 15 runners / 14 results，866 项历史底座回归通过，重新 review 无剩余可修复问题。
27. 生产协调复审发现历史镜像基线落后于已应用 `stable.0027–0029` 的数据库。当前 worktree 合入 `origin/main@1a70b22e`，保留双方服务和迁移；修复 main 中 lease 测试固定绝对时间导致半小时后失效的问题。历史与法国/归属/翻译组合 323 项、完整 stable 1093 项均通过，重新 review 无剩余可修复问题。
28. 2016–2025 法港英详情抓取复审发现 Aintree Bowl 被误配到同日 Aintree Hurdle。新增审核系列别名、详情 URL 全局占用门禁，并将 URL fragment 从占用键中剔除，避免同一页面用带/不带 `#video-player` 的写法绕过去重。重抓后法港英各 50 场、合计 150 个详情 URL 全局唯一；专项 204 项及完整 stable 1126 项通过，重新 review 无剩余可修复问题。
29. 生产只读日期 artifact 首次构建暴露 47 场英国距离证据缺少显式单位或使用 `1m71/2f` 紧凑写法。扩展既有地区补单位入口：英国裸数字按 `<5 mile / >=5 furlong`，紧凑 mile/furlong/yard 写法展开；复审同时修复距离消歧把 `71/2f` 错读为 `70.5f` 的十倍级错误。57 项专项和完整 stable 1128 项通过，第三轮 review 无剩余可修复问题。

## 最终结论

**无剩余可修复问题。**

验证结果：

- Django check：通过
- `makemigrations --check --dry-run`：无变化
- `stable`完整测试：1128项通过，1项按设计跳过
- OpenSpec change strict：通过
- OpenSpec all strict：25项通过
- `git diff --check`：通过

本结论覆盖上述实现范围，以及香港、netkeiba、Sporting Life、Horse Racing Nation、法国 ZEturf、英法 IrishRacing 与美国 Equibase 单场PDF详情adapter、候选封装和独立补充来源审批链。法国和英国2000年样本已完成生产补源；美国2000/2012六场官方PDF已离线验证，待部署后执行日期与详情受控写入。
