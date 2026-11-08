# 日本公开字段修复发布实录（2026-11-08）

## 已发布版本

PR [#285](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/285) 已合并，merge `c7a99a7f8879b1a0072ca1ec73108bb9539ba4d5`。
生产采用现行 `69947674` 上的窄提交 `fd5349eff808b2d45740827bb65b28540787a1ad`，镜像
`sha256:26c344728d166f8420001ba7d7c252901f4bd3e12c0d163a4d35012717c94a95`。
只有本次8个业务／测试文件进入生产；无迁移，schema仍为 `0079_multisource_race_enrollment`。
配置、功能开关和来源权限未改变，QQ仍关闭，JRA浏览器保持原镜像和启动时间。

按用户“一起修复并发版、不需要全量CI”的明确指令执行。受保护同schema入口完成专属备份、
任务排空、四应用更新及服务恢复；之后在同一发布协调锁内停止writer，按固定清单dry-run和apply，
再恢复worker/Beat、检查Web健康并reload Nginx。人工确认规则仅引用根 `AGENTS.md`。

## 数据与网页验收

- 清单SHA `5c9c541f928e5f5c2e37588110ffc5e0ecf25583640e2407492d75d97fc2a9ad`；43场571行赛果及对应出马表完成补正，原发布revision不变。
- 570行有效热门排名已投影；唯一取消出走记录没有热门排名，不补造赔率。
- 571行对应出马表状态与赛果一致；负重按千克展示，所有非空差距均可读。
- 四场报名名单共77匹负重正确展示；仍为报名阶段，不冒充正式出马表。
- 24场缺失时间补齐，其余19场既有时间保留；43场已完赛赛事均显示北京时间。
- 27场未来赛事在本次证据中尚无已发布时刻，保留待定，不依据惯例生成。
- 70个公网详情页全部HTTP200，571条赛果、648条出马表／报名行逐页核对通过。比较按公开显示规范处理“第N热门”“同着”，结果零差异。
- 双域名healthz均200；四应用同固定镜像、运行且零重启／OOM；浏览器healthy。

真实浏览器样本：[JBC雌马经典赛](https://umafans.run/races/2026/nar-dirt-2026-1103-40/)。
10号 `ラブラブパイロ` 出马表由“已出走登记”变为“取消出走”，负重55千克；赛果同为“取消出走”。
该场显示2026-11-03 13:25（北京时间）；胜马9号在赛果中显示第4热门。

状态由官方明确标记映射，赛后发布按同场、同马的可靠身份同步出马表，保留人工锁；
不凭“未在新名单出现”推断退赛。JRA/NAR既有取消／除外映射及未完赛、同着等区别保留。

## 测试与交付证明

真实RED覆盖五项缺口。独立只读review提出旧磅制值被覆盖为千克的问题，两个RED复现后修复，
17项PG返修回归通过；原review上下文复审关闭finding，最终提交树与受审内容逐项绑定。
固定窄候选另通过整包PG dry-run/apply/幂等、70页隔离渲染及实际生产候选镜像17项离线回归。

[范围CI 42490692233](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/42490692233)
执行940项、零失败、零skip。候选目录外受信验证器核验固定提交／合并树、控制文件、CI镜像、
独立收集的完整测试清单和主线strict保护后，交付回执为verified；未执行full CI。
本地首次镜像加载因旧Docker环境满盘失败，随后在已有隔离环境的已挂载目录核验成功，未清理其他任务资源。

生产Compose构建比直接Docker构建仅多 `com.docker.compose.image.builder=classic` 标签；
两镜像RootFS及其余Config完全一致，发布意图与运行四应用均绑定最终Compose镜像ID。

## 备份与证据

发布ID `4af086fbd2c0edfcfa42a9eda2d715e2d6123dc255360da597d46e3dd806c8ad`，
intent SHA `596f1611d4be1e24b8c214657cff1cc48ba787708d5a5c769a2c3e2f9df0670c`。
专属dump 934826624字节，SHA `cb2865cbeb83e187a4ae91682a00b4fd638ad0d3565edb6559eb5c4ea4eb4415`，
TOC 1401行已验证；备份留在服务器，未下载生产库用于测试。
配置SHA与发布前一致。恢复边界沿用[发布包](rollout.md)，不通过整库覆盖纠正个别业务字段。

本次完整回执位于独立runtime目录 `japan-race-fields-20261108`：
`delivery-receipt.json`、`production-receipt.json`、`production-verified.json`、
`public-after.json`、`final-delivery.json`，以及SHA绑定官方页面、补正清单、测试与发布日志。

## 仍待实况回归

下一场正式出马表发布和新赛果自然状态流转仍按既定决定延期；本次历史补正不能代替该项验收。
其他地区全批及既有暂停任务不在本次发布范围内。
