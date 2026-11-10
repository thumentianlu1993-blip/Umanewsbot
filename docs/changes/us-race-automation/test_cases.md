# 测试和 mutation

自动测试只用本地 HTML/PDF、fake transport 和固定时钟；禁止外网/生产数据库/Redis/队列。

| ID | 行为 | 捕获的 mutation |
|---|---|---|
| U01 | TOBA窗口143条来源记录（Glen Cove第5/8场同名待核）、DMR 11-28三场同时保留、not run独立、重复去重、冲突保留双方 | 忽略年份；not run归入窗口；静默覆盖 |
| U02 | NSA跨页六场秋季+两场九月分级 | 把封面历史冠军当赛程；跨页丢失日期；误用序号 |
| U03 | Del Mar精确身份、5匹、无移动版重复、磅/空赔率 | 忽略日期；两次数DOM；缺赔率补零；PGM/PP互换 |
| U04 | 未final不输出正式observation | 忽略not finalized提示 |
| U05 | 报名PDF11匹、声明计数/日期/名校验、无马号/骑手 | 排序充当马号；截断成功；错误日期通过 |
| U06 | changes正文日期、退赛/负重/场况，旧日拒绝 | 忽略日期；负重调整方向反转 |
| U07 | NSA原PDF七匹含PU，名单/字段完整区分 | 丢PU；复制冠军时间/胜出着差到每匹 |
| U08 | 未知状态、重复身份、缺表头、截断、非法日期失败 | 静默跳坏行；空完整结果 |
| U09 | URL/重定向/超时/体积/请求上限；不请求Equibase | 任意主机；无限重试；403当未发布 |
| U10 | 离线保留抓取时间/SHA；损坏缓存失败；无网络/业务库 | now覆盖原时刻；不验SHA；miss自动联网 |
| U11 | 命令输出候选/缺口；下载成功不等于完整验收 | 隐藏失败；写生产；打开开关 |
| U12 | Del Mar标准入口与其他来源回归 | 绕过route/identity；私自启用provider |

先以现有来源发现对 Del Mar 不支持取得真实 RED，再实现。后续逐行为 RED/GREEN，最小接口占位可以抛 unsupported；不以导入错误作为 RED。命令、退出码和失败摘要写 release_evidence.md。

回归：新测试+直接受影响 multisource discovery/adapter/identity，核对 impact plan；本批无 schema/Celery/settings 改动，不要求全量或PostgreSQL并发组。后续写入/调度批必须先补幂等、过期租约、worker crash、并发、回滚测试。

独立 HTTP 验收与自动测试分开，不证明5/10分钟延迟或七天更正，这两项需自然调度观测。

U13：TOBA原始Listed行与Del Mar报名PDF共同输入，Bob Hope输出双方等级/URL/SHA和conflict；不进入G1—G3分母、不创建生产身份。mutation：先过滤丢Listed；按原始字符串漏关联；自动优先官网改等级。

## 独立审核回归

- U14：已有成功TOBA缓存，200防护页解析失败后恢复旧SHA/抓取时刻，失败原件保留版本历史；捕获刷新覆盖恢复入口。
- U15：截断PDF转us_pdf_invalid，仍生成含TOBA成功证据的报告；捕获文档异常逃逸整批。
- U16：2027重放2026缓存仍得到相同报名和等级冲突；捕获使用当前年份。
- U17：Montpelier Noel Laing第五名精确为SCORPION'S REVENGE (IRE)，删除独立(L)；捕获坐标交错字符损坏马名。
