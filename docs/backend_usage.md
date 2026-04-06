# 后台使用说明

## 1. 当前后台能力

当前后台基于 Django Admin，已经具备：

- 新闻列表查看
- 查看新闻原文、中文译文、图片、榜单快照、翻译记录、推送记录
- 编辑中文标题、中文正文、推送摘要、备注
- 维护术语库
- 维护 QQ 群目标
- 手动触发重新翻译
- 手动触发推送
- 查看任务执行日志

## 2. 启动后台

```bash
cd E:\Codex\server
python manage.py migrate
python manage.py seed_admin --username admin --password admin123456
python manage.py runserver
```

打开：

`http://127.0.0.1:8000/admin/`

## 3. 后台主要入口

- 新闻：`/admin/stable/newsarticle/`
- 术语库：`/admin/stable/termentry/`
- 推送群：`/admin/stable/pushtarget/`
- 任务日志：`/admin/stable/taskexecutionlog/`
- 推送日志：`/admin/stable/pushlog/`

## 4. 推荐操作流

### 4.1 先抓取

```bash
python manage.py crawl_news netkeiba_latest --pages 2
python manage.py crawl_news jra
```

### 4.2 看后台新闻列表

重点关注：

- `source_site`
- `source_mode`
- `status`
- `is_first_crawled`

### 4.3 检查翻译结果

如果没配真实翻译模型，看到的是 `dummy` 回填结果，这是正常的。

### 4.4 手工编辑

你可以直接修改：

- `title_zh`
- `body_zh`
- `push_summary_zh`
- 图片中文说明

### 4.5 手动推送

进入新闻详情页，点击“推送到QQ群”。

## 5. 当前未完成的后台联调项

- 还没有做独立前台管理页面，当前是 Django Admin 形态
- 还没做更丰富的任务看板
- 还没做批量导入术语
- 还没做自定义筛选器增强体验
