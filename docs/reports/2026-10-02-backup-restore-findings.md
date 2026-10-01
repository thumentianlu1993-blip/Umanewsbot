# 2026-10-02 备份恢复演练发现的既有唯一约束问题

本次为 PR229 赛事恢复上线前的附加演练。发现时生产仍运行 `310588704a5dd2cef477300eff626987491411cb`，PR229 尚未上线，七场赛事的生产恢复尚未执行。因此下列问题不是本批赛事写入引入。

## 已证实的事实

生产只读一致性备份为 636531864 字节，SHA256 `4c0cf4fa6ae00a335bd238556379f2511cc4b882493d4a17c504ea314e879a5e`，保存在服务器本次发布目录的 `rehearsal/production-snapshot.dump`，私有权限，不上传仓库。

在独立 Docker internal 网络、无生产网络连接、1 CPU / 768 MiB PostgreSQL 容器恢复，完整数据装载后，两处唯一约束无法建立：

| 表 | 约束 | 证据 |
|---|---|---|
| stable_newsarticle | uq_article_source_article_id | dump 恢复报告 source_site + source_article_id 重复；对报错键生产只读禁用索引扫描，heap 实际匹配 13 行 |
| stable_termcandidate | uq_term_candidate_type_normalized | dump 恢复报告 term_type + source_language + normalized_key 重复 |

源库两处约束均 convalidated=true，对应索引 indisvalid/indisready=true 且为 UNIQUE btree。这与实际重复行不一致。根因未定位，不能仅凭标志宣布索引/数据健康，也不将其直接归因为排序规则或某次发布。

因此本次 **整库恢复验证未通过**。此前通过的 SHA / `pg_restore --list` 只是归档可读性证据，不能替代真实恢复。发布工具的备份合同原本校验 SHA/TOC，本次未修改或绕过该合同。

## 赛事恢复演练边界

仅在隔离副本中排除上述两处失败的非赛事唯一约束，恢复剩余 post-data。未修改源库、未清理生产重复新闻或术语候选。

赛事相关 340 个约束、244 个索引、7 个非内部触发器完整恢复；与源库比较，索引/触发器一致，CHECK 仅存在 PostgreSQL 对枚举数组整体 cast 与逐元素 cast 的等价反解析差异。该比较保留全部条件和值，不忽略其他差异。

在此副本执行固定七场 manifest：dry-run ready，首次 applied，重复 already_applied。七个实际 Django 公开详情响应 200，共 52 行，828/833 的末条分别正确显示“跌倒”。新后台响应 200，无 incident 写入。此证据只证明目标赛事恢复与页面读取，不代表整库灾备能力已恢复。

演练容器、专用 volume 和 internal 网络已清理；私有原始 dump、TOC、错误日志、目标表结构比较和验证 JSON 留存在 `/opt/umanews-release-ec461daa-coverage-20261002/rehearsal/`。

## 待单独安排的运维修复（P1）

1. 先在只读/隔离环境核实重复范围、索引一致性与完整关联，保留失败 dump 和源库基线。
2. 为新闻、术语候选分别确定保留/合并规则和引用迁移方案；不能为让恢复通过而盲删重复行。
3. 在副本演练合并与索引重建、重跑完整备份恢复；用实际恢复结果验收。
4. 再形成独立生产修复包。本轮赛事恢复授权不扩展为新闻或术语批量去重。
