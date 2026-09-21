# 发布、数据恢复与验收边界

实现与本地测试已完成，未执行下面任何生产步骤。0079发布包仍待准备，不将0078固定目标工具直接视为0079可用。人工门禁唯一来源为根 AGENTS.md，方案独立审核不代表发布或生产数据授权。

## 1. 迁移与兼容包

固定提交/image、schema leaf（当前0078）、新增两表/四字段迁移、两套policy/registry及各自SHA、三默认关闭开关、来源地域/host/path/能力/有效期、预算上限、精确赛事修复与A0身份seed清单（绑定旧来源/候选、baseline和fresh链接链；不能无限扫描补造所有历史身份）、旧v1升级清单（可以为空）、服务重建与验收/恢复方法一起进入发布包。身份准入和真实来源抓取若扩大，明确列出G3动作，由G2完整包覆盖时不重复审批。

v1旧policy/roster/digest读取必须保持；全量旧登记只读检查列出每场owner、source、generation、manifest、公开revision和admission结果。v2加入前后旧场每项一致才启用，不能只看健康检查200。运行中的旧消息先排空，采用支持两schema的同一镜像重建web/worker/beat；不能让旧worker执行v2消息或读v2登记。read-only shadows不注册身份、不写budget或调用provider。

## 2. 分阶段

1. 离线测试/PG并发/实现独立review与同SHA CI完成，形成精确发布包。
2. 新鲜生产预检：实际四应用commit/image、有效配置、锁/采集暂停、三队列、备份恢复验证、磁盘/内存、leaf及待迁移计划。沿用0078受保护前向发布合同，不普通git reset回滚。
3. 关闭新开关部署并迁移；v1照常工作。零写预演新覆盖分母、来源绑定、冲突、预计请求量、104/103处置和旧场公开不变。
4. 在批准scope内按地区开启v2发现，再开启apply；官方及参考source均必须具备该地区proof，不以共享adapter代替地区proof。先验收JRA症状，再扩NAR/HK/UK/Ireland/France/US，各桶未通过就保持缺口，不宣布全球完成。
5. 103/104采用固定target/source URL/身份/完整结果/名单/manifest SHA补登记与结果的同一pipeline；任务幂等，写前备份、dry-run、独立verify，不能直接SQL改status。明日105只在当前日期仍合适时做自然样本；日期变化改用新样本，不更改旧证据。
6. 每桶验证单登记、多身份、自然任务状态推进、完整赛果确认、一次publication、公网页面、未登记告警、两次自然刷新。实时与late admission分别按test_cases H4的30分钟／6小时窗口验收，预算延期保留分母并报告超标；官方confirm时点或provider首次可见时点未获证据则时效指标unknown，不能以T+30推算实际完赛。

## 3. 中止与恢复

- 发现新误合并、重复publication、旧场admission退化、预算超限或未知生产写入：停止v2发现/apply并排空/撤销v2 claim；保留raw observation、bindings、identity keys及已发布版本。
- 关闭开关阻止新采集/新写，不删除既有v2登记，也不让public reader退回只懂v1导致已发布结果消失；reader继续用已保存、尚有效的发布授权展示最后有效版本。涉及来源撤销/身份错误的内容单独按既有公开撤销规则处理。
- additive schema保留，采取开关停用+受保护重载/前向修复；不反向撤销0078或删表。回退到完全不识别v2的旧镜像不是允许的通用恢复方法。
- v1转换逐event原子；中断后按receipt重读成功/未处理/冲突，禁止重置generation；尚未变更的v1不受影响。恢复已转v2的单event需固定snapshot和所有generation CAS的前向manifest，不能只改回source FK。
- 错绑需要冻结对应binding和受影响publication、人工审核后出具体修复manifest；identity key不自动重分配，不以批量删除冲突记录恢复。

## 4. 验收输出

逐地区：应纳管数、窗口未开放、已唯一匹配、歧义/冲突、已登记、缺能力、超预算、时间未知、赛果未知、已确认、公开通过；分层相加须守恒。记录自然task IDs、源URL/SHA/observed_at、入库receipt和revision/publication、公网抽样；对七桶分别标完成/缺口，不用整体SUCCESS替代。
