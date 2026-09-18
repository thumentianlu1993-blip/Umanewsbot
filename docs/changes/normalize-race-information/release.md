# 2026-09-18 赛事信息归一化已上线

本次以服务器实际运行态及双域名网页为验收入口，发布完成于 `2026-09-18T09:52:59.194054+00:00`（北京时间17:52）；验收记录起点为 `2026-09-18T09:53:41.522506+00:00`。用户已明确授权推送公开仓库、合并并部署启用。

## 精确版本与配置

- [PR207](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/207) 已合并；合并提交 `b672554d038089a781b91ed2f8c50ff74c8fc325`。
- 实际应用 `433de627b9ae4d9c0c756dd518668a115a818bd8`；四应用镜像 `sha256:097820af0b7761b6ff7c5a6c8416c2b7456b3d4f3f6e4aea901b64e7afaa5763`。
- 实际目录 `/opt/umanews-release-433de627-normalize-20260918/umanewsbot`；证据目录为其上级 `evidence/`。
- 四应用 web、worker、beat、race_sync_v2_worker 的镜像标签、文件和 Django 有效版本相同，环境及有效设置均为 `RACE_INFORMATION_NORMALIZED_DISPLAY_ENABLED=true`。
- 配置仅新增此开关。JRA 保持 true，DB/Redis/Nginx/OneBot 原容器保留，Nginx 按协调器重载。
- schema 仍为0078，迁移计划为空；未进行历史业务回写、采集扩容或队列清理。原始字段保留，本次改变展示。

## 验证结果

- 最终37项局部归一化回归通过，同一独立 reviewer 最终复审 APPROVED；原相关 PostgreSQL 93项通过。没有重复本机整仓测试。
- [最终 Linux CI](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/35328094066) 完整候选 `5090` 项，`16` failures、`29` errors、`20` skipped；对同 run 历史基线及当前生产45项已知失败集合均无新增。既有失败保留，不能称为全量全绿。GitHub摘要步骤在合并时仍为in_progress；本次以已完成的测试作业和SHA绑定的完整同run原始结果执行相同失败ID集合比较，不伪造远端check状态或改变分支规则。45项发布合同、Django check、无迁移漂移、前后指纹验证通过。原始结果摘要和完整失败ID见 [ci-summary.json](ci-summary.json)。
- 最终固定镜像内，五地区各5场，共25场：等级25条正常，距离24条正常、1条原缺失，unknown/conflict 为0，原名称25条保持；只读事务、零业务写入。此聚合只证明指定范围，不代表全库覆盖。
- 双域名共 `36` 次公开 GET 通过；其中10场×2域名逐项核对等级、距离及名称，另覆盖健康、首页、赛事列表、马匹索引及抽取的新闻／马匹详情。出马表和赛果行数与上线前同页面比较：`20页出马表与赛果行数完全一致`。
- 八服务运行、四应用版本一致、Web健康；系统检查和空迁移计划通过。队列采样 `{"celery": 0, "race_sync_v2": 0, "race_live": 7543}`，旧 race_live 保持7543未消费。

## 备份与收尾

发布沿用 lowcost/0078 受保护协调器；专属备份 `561160412` 字节，SHA256 `42585d505a215f5d865142815344212292dfc9e9bca4a927ee34d33599c1d9f1`，与本次 manifest 一致。intent/manifest/complete、备份TOC和恢复服务清单均核验；原始文件留在服务器受限证据目录，没有导出业务明细或配置秘密。

发布锁、active pointer、restricted recovery 标记均已清理。原马匹采集保持暂停：批次8完成219匹（217候选、2缺口），待处理281，下一匹 `hrs_38905307`；本次不恢复采集。

## 恢复边界

展示异常可将新开关改为false，经现有受保护发布流程重载四应用并核验实际settings和公网页面。普通代码rollback仍禁用，不直接换旧镜像或恢复整库；未完成发布只沿原候选、原intent续跑，完成后的代码问题前向修复。

原主工作区 `horse_data` 及已有改动保留。应用发布固定上述已测SHA；后续纯文档提交只回写验收，不产生应用版本升级。
