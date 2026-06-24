## 1. 数据模型与配置

- [x] 1.1 (application) 新增外部赛马数据模型：比赛、出走表、赛果、赔率、马匹、马匹履历、马名索引、导入运行、导入错误。
- [x] 1.2 (application) 为外部数据模型添加唯一约束、查询索引、`raw_payload`、来源字段和抓取时间字段。
- [x] 1.3 (application) 生成并检查 Django 迁移，确保 PostgreSQL 与 SQLite 均可应用。
- [x] 1.4 (operations) 固定并接入 `keibascraper` 依赖，更新依赖文件和部署构建路径，并提供 import 冒烟检查。
- [x] 1.5 (operations) 在 `server/app/settings.py` 和 `.env.example` 中新增外部赛马数据导入开关、回溯月份、请求间隔、抖动、批量上限和赔率/马匹详情开关。

## 2. 导入适配与持久化服务

- [x] 2.1 (integration) 新增 `keibascraper` 适配层，封装 `race_list`、`entry`、`result`、`odds`、`horse` 数据读取。
- [x] 2.2 (integration) 在适配层实现外部请求限速、随机抖动、网络开关校验和统一异常类型。
- [x] 2.3 (integration) 实现同一来源真实外部请求导入互斥，避免多 worker 并发绕过限速。
- [x] 2.4 (integration) 实现比赛、出走、赛果、赔率、马匹、履历数据的幂等 upsert 服务。
- [x] 2.5 (integration) 实现从出走表、赛果、可信马匹主名和人工单马参数派生本地马名索引的服务。
- [x] 2.6 (integration) 实现导入运行进度、覆盖率统计和导入错误记录服务。

## 3. 管理命令与异步任务

- [x] 3.1 (application) 新增管理命令，支持默认近两年导入、指定年月导入、指定 `race_id` 导入、指定 `horse_id` 导入、单马可选 `--horse-name` 和 dry-run。
- [x] 3.2 (application) 管理命令必须支持单次最大比赛数、单次最大马匹数、是否抓取赔率和是否抓取马匹详情参数。
- [x] 3.3 (application) 新增 Celery 任务封装外部赛马数据导入，但不加入默认全量 Celery Beat 调度。
- [x] 3.4 (application) 新增马名索引查询和导入覆盖率统计入口，供管理命令验收指定日文马名是否命中本地索引。

## 4. 测试与验证

- [x] 4.1 (application) 新增模型约束和迁移相关测试，覆盖重复导入不产生重复记录。
- [x] 4.2 (integration) 使用 mock `keibascraper` 返回值测试 entry/result/odds/horse/history 全字段保存和原始 payload 保留。
- [x] 4.3 (integration) 测试限速、网络开关、单来源互斥、批量上限、断点续跑和错误隔离。
- [x] 4.4 (application) 测试 dry-run 不写入数据，真实导入写入运行记录、覆盖率统计、错误记录和马名索引。
- [x] 4.5 (application) 测试单马导入仅在存在可信马名时创建马名索引。
- [x] 4.6 (application) 执行 `DB_ENGINE=sqlite python manage.py check`。
- [x] 4.7 (application) 执行 `DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true python manage.py test stable`。
- [x] 4.8 (operations) 执行 `openspec validate add-netkeiba-horse-data-import --strict` 和 `openspec validate --all`。

## 5. 文档与生产运行手册

- [x] 5.1 (operations) 更新 `docs/current_state.md`，记录外部赛马数据导入能力的当前状态和默认关闭策略。
- [x] 5.2 (operations) 更新 `docs/deploy_runbook.md`，补充生产执行前备份、dry-run、单月小批量导入、限速建议、日志检查和停止方式。
- [x] 5.3 (operations) 更新 `docs/decisions.md`，记录为何使用离线低频导入和本地索引，而不是新闻处理链路实时查询 netkeiba。
- [x] 5.4 (operations) 更新 `docs/project_status.md`，保留项目级摘要。
