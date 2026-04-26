# 日本赛马新闻采集、翻译与发布系统

当前版本：`v0.0.1`（上线准备阶段）

## 系统能力

- 来源采集：`netkeiba`（新着/访问/注目）与 `JRA`
- 翻译链路：术语召回 + 大模型翻译 + 失败重试 + 人工编辑保护
- 内容后台：候选池、编辑台、术语库、来源管理、发布管理、操作日志
- 前台展示：信息流 + 详情页
- 推送能力：OneBot（QQ 群）手动推送

## 本地开发

```bash
pip install -r requirements.txt
copy .env.example .env
# 本地开发建议改成 sqlite
# DB_ENGINE=sqlite
cd server
python manage.py migrate
python manage.py seed_admin --username admin --password admin123456
python manage.py runserver
```

访问地址：

- 前台：`http://127.0.0.1:8000/`
- 后台：`http://127.0.0.1:8000/admin/login/`
- Django Admin：`http://127.0.0.1:8000/django-admin/`

兼容旧入口（会重定向）：

- `/login/` -> `/admin/login/`
- `/console/` -> `/admin/`

## 生产部署（Docker Compose）

```bash
cp .env.example .env
# 填写 .env 中的 RDS / OSS / API / 域名配置
docker compose -f docker-compose.prod.yml up -d --build
```

低成本模式（不购买 RDS，ECS 本机 PostgreSQL）：

```bash
cp .env.example .env
# .env 里先填 POSTGRES_DB/USER/PASSWORD 即可，POSTGRES_HOST 会由 lowcost compose 覆盖为 db
docker compose -f docker-compose.prod.lowcost.yml up -d --build
```

也可以使用脚本：

```bash
chmod +x deploy.sh deploy/*.sh deploy/docker/*.sh
./deploy.sh
# 低成本模式
./deploy_lowcost.sh
```

## 关键文档

- [项目状态文档](E:/Codex/docs/project_status.md)
- [生产部署指南](E:/Codex/docs/deploy_production.md)
- [阿里云香港区手把手指南](E:/Codex/docs/alicloud_hongkong_step_by_step.md)
- [回滚指南](E:/Codex/docs/rollback_guide.md)
- [备份与恢复指南](E:/Codex/docs/backup_recovery.md)
- [生产上线检查清单](E:/Codex/docs/production_checklist.md)
- [翻译与术语库配置](E:/Codex/docs/translation_and_termbase.md)
- [QQ Bot 配置教程](E:/Codex/docs/qqbot_setup.md)
- [后台使用说明](E:/Codex/docs/backend_usage.md)
- [PRD 归档目录](E:/Codex/docs/PRD/README.md)
