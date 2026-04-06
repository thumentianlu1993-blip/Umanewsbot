# 日本赛马新闻采集-翻译-QQ 推送系统

当前版本：`0.0.1`

基于 `Django + Celery + PostgreSQL/SQLite + Redis + OneBot` 的日本赛马新闻采集后台。

当前已实现：

- `netkeiba` 三种榜单模式采集器
- `JRA` 月归档新闻采集器
- 新闻、图片、榜单快照、术语库、推送目标、推送日志、任务日志数据模型
- OpenAI-compatible 翻译接口与 dummy 翻译降级
- QQ OneBot 推送服务与图片失败降级
- Django Admin 后台，支持编辑新闻、维护术语库和推送目标、手动推送、重译
- Celery 定时任务与管理命令

## 本地启动

1. 安装依赖

```bash
pip install -r requirements.txt
```

2. 配置环境变量

```bash
copy .env.example .env
```

3. 初始化数据库

```bash
cd server
python manage.py migrate
python manage.py seed_admin --username admin --password admin123456
```

4. 启动后台

```bash
python manage.py runserver
```

后台地址：`http://127.0.0.1:8000/admin/`

## 常用命令

抓取新闻：

```bash
python manage.py crawl_news netkeiba_latest --pages 2
python manage.py crawl_news netkeiba_access
python manage.py crawl_news netkeiba_attention
python manage.py crawl_news jra
```

运行测试：

```bash
python manage.py test stable
```

## 部署

仓库根目录已包含：

- `Dockerfile`
- `docker-compose.yml`

生产环境建议：

- `.env` 配置 PostgreSQL、Redis、OpenAI-compatible 接口、OneBot 地址
- `web + worker + beat + db + redis` 一起编排
- 由反向代理暴露 `/admin/` 和 `/media/`

## 文档

- [翻译与术语库配置](E:\Codex\docs\translation_and_termbase.md)
- [QQ Bot 配置教程](E:\Codex\docs\qqbot_setup.md)
- [后台使用说明](E:\Codex\docs\backend_usage.md)
