# 新闻正文提取边界发布报告

## 发布身份

- 发布日期：2026-07-24（Asia/Shanghai）
- 任务提交：`9fded052df6c6bd9a8814dba0b4f0e272d6edfe7`
- PR：[GitHub #12](https://github.com/thumentianlu1993-blip/Umanewsbot/pull/12)
- `main` 合并提交：`0e4a35206999c3daa3218a82dcc8fdd90197c394`
- 独立只读 review：`APPROVED`
- review parent：`45ded0834e6517a544ad2acd600503e127bd59ef`
- review content hash：`47b86960dcfed2472e80c461f1458bd462b7bb785ea5e922df1f0211c8291b77`
- review fingerprint：`107e3b58ae796e64c45feaba9c5988553d779554d4a463ff388dbfc4fa794f26`

## 发布前恢复点

- `.env`：`.env.backup.news-body-boundary-20260724T015733+0800`
- PostgreSQL：
  `backups/db/pre-news-body-boundary-20260724T015733+0800.sql.gz`
- 数据库备份大小：`237423530` bytes
- 数据库备份 SHA-256：
  `250e81de23816d00c7c15d9fd354867d28521f56edca980786f7f557c4a4330d`
- `gzip -t`：通过

发布前 Celery `active/reserved` 已排空，外部导入运行数为 0；未执行历史正文识别或重处理。

## 部署结果

- 生产 `/opt/umanewsbot` 从 `17d7757aec764755394339400eb2523eae896fa5`
  快进到 `0e4a35206999c3daa3218a82dcc8fdd90197c394`。
- 无新增 migration；`makemigrations --check --dry-run` 返回 `No changes detected`。
- `web / worker / beat / race_live_worker` 使用同一镜像：
  `sha256:36b9a75b854f9be0ccfb7beca164a69e9a5f79bab77b4bcd2f4cbb9f50356733`。
- Django check、worker ping、内部和公网 `/healthz/`、首页及文章 `9623` HTTP 访问通过。
- 部署后 Celery `active/reserved` 为空；四个应用服务近 10 分钟未发现
  `Traceback / CRITICAL / IntegrityError / Exception`。

第一次执行 `deploy_lowcost.sh` 时，部署脚本与新 web 启动脚本并发处理共享 static volume，
外层 `collectstatic` 遇到一个瞬时文件不存在错误。新 web 自身已成功完成 collectstatic 并保持
healthy；核对未发生 migration 后，在单一进程中重跑 `collectstatic` 成功，再显式重建
`worker / beat / race_live_worker`。未重放数据库写入。

## 正文边界验收

生产镜像对文章 `9623` 的真实 HRN 来源页只读解析结果：

- `body_parse_status=ok`
- `body_selector=.article-body`
- 正文长度：`9355`
- 正文 SHA-256：
  `31ede23b2013af653e0b7d57cf13d19b716ce82936bff6e8a0d7f75bef18f242`
- 已知页面框架文本命中数：`0`
- 首尾均为文章正文

部署后的自然 HRN 抓取 job `27503 / 27504` 均成功，均为 14 条重复、0 条新文章。因此本轮没有
“此前从未入库的新 HRN 文章”，Gate A 的全新文章翻译及公开详情验收仍待自然新稿出现，不能用
重复抓取冒充。

自然重复抓取已把 `9623` 原文层更新为 `.article-body`，原文层不含已知中文污染词；但既有
`translated_body_zh / body_zh / effective_body` 仍含“当前、热门、CCA橡树大赛分析、正面交锋、
公平赔率、登录、免费注册”。本次没有触发重译、改写、重新发布或 QQ 发送，也没有以模板隐藏内容。
这部分继续属于 Gate B/C，必须先完成可审计识别并取得独立历史批次授权。

## 回滚

如新采集出现异常，先暂停 HRN 来源并排空队列，再把四个应用服务恢复到部署前镜像
`sha256:5a3dd28b846954837ade517e5d85aa2bba3b4651d322876f950f0cdfcda45e44`
及对应代码；本次无迁移，只有确认数据损坏时才使用上述数据库恢复点。
