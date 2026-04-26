# 后台使用说明

## 1. 后台入口

- 后台登录：`/admin/login/`
- 后台工作台：`/admin/`
- Django Admin：`/django-admin/`

兼容入口（会自动跳转）：

- `/login/`
- `/console/`

## 2. 常用页面

- 来源管理：`/admin/sources/`
- 候选新闻池：`/admin/candidates/`
- 术语映射：`/admin/terms/`
- 术语批量导入：`/admin/terms/import/`
- 已发布内容：`/admin/published/`
- 操作日志：`/admin/logs/`

## 3. 基本工作流

1. 来源管理中确认 `netkeiba` / `JRA` 来源已启用。  
2. 在来源页触发“测试抓取”，或等待定时任务入库。  
3. 在候选池筛选稿件，进入编辑台完成中文标题、正文编辑。  
4. 提交审核并发布。  
5. 需要时手动触发 QQ 群推送。  

## 4. 编辑台规则

- 必填：中文标题、正文
- 选填：中文摘要、标签、来源说明、编辑备注
- 摘要可手动清空，保存后保持为空
- 标签支持自动提取术语库中的马名（中文译名）

## 5. 相关文档

- [翻译与术语库配置](E:/Codex/docs/translation_and_termbase.md)
- [QQ Bot 配置教程](E:/Codex/docs/qqbot_setup.md)

