# QQ Bot 配置教程

## 1. 当前 QQ 推送能力状态

当前项目已经实现：

- 通过 OneBot HTTP API 推送群消息
- 支持文本消息
- 支持“文本 + 1 张图片”
- 如果图片发送失败，会自动降级为纯文本
- 推送结果会写入 `PushLog`

核心文件：

- [onebot.py](E:\Codex\server\stable\services\onebot.py)
- [pushing.py](E:\Codex\server\stable\services\pushing.py)
- [models.py](E:\Codex\server\stable\models.py)

## 2. 当前实际测试情况

已测：

- 推送消息拼装逻辑
- `BotPusher.send_group_message()` 的调用流程
- 推送成功后 `PushLog` 和文章状态回写

未做实机联调：

- 没有连真实 QQ 机器人框架发过消息
- 没有验证不同 OneBot 实现对图片字段的兼容差异
- 没有验证账号风控和群权限问题

所以现在的状态是：

- 代码接口已经有了
- 但你还需要接入一个真实 OneBot 服务端，才能完成联调

## 3. 推荐接入方式

当前推荐路线：

- QQ 客户端侧：`NapCatQQ`
- 协议侧：`OneBot v11`
- 我们项目侧：HTTP API 调用 `/send_group_msg`

不建议把业务逻辑直接绑死到某一个 QQ 框架内部实现。

## 4. 你需要准备什么

### 4.1 一台可运行 QQ 机器人框架的环境

通常需要：

- 一台 Windows 机器或可运行 NTQQ 生态的环境
- 一个用于机器人的 QQ 账号
- 已经进到目标群

### 4.2 OneBot 服务地址

你需要拿到：

- OneBot HTTP 地址
- Access Token

例如：

```env
ONEBOT_BASE_URL=http://127.0.0.1:3000
ONEBOT_ACCESS_TOKEN=your_token
```

如果 OneBot 服务和 Django 不在同一台机器：

- 把 `ONEBOT_BASE_URL` 改成可访问的内网地址或反向代理地址
- 确保 Web/Worker 机器能访问它

## 5. 在项目中配置 QQ Bot

编辑 `.env`：

```env
ONEBOT_BASE_URL=http://你的onebot地址:3000
ONEBOT_ACCESS_TOKEN=你的token
```

然后重启 Django/Celery。

## 6. 在后台配置群

进入后台：

`/admin/stable/pushtarget/`

新增群配置：

- `name`
  - 例如：`赛马新闻测试群`
- `group_id`
  - QQ 群号
- `is_default`
  - 是否为默认群
- `is_active`
  - 是否启用

如果你不在推送时手动选群，系统会默认推到所有 `is_default=true` 的群。

## 7. 推送消息长什么样

当前固定格式：

1. 中文标题
2. 发布时间
3. 来源
4. 中文摘要
5. 原文链接
6. 主图（如果有）

目前不推送整篇全文，避免刷屏。

## 8. 常见问题

### 8.1 点了推送没反应

优先检查：

- `ONEBOT_BASE_URL` 是否可访问
- token 是否正确
- QQ 机器人是否在线
- 机器人账号是否在目标群里
- 目标群是否允许发消息

### 8.2 图片发不出去

当前代码会自动降级成纯文本。

如果你希望更稳，可以后续改成：

- 先上传图片到公网 URL
- 再发图片 URL
- 或针对具体 OneBot 实现改造图片字段

### 8.3 被风控怎么办

这个属于第三方 QQ 机器人方案的客观风险，代码层面无法保证规避。

建议：

- 先小范围测试群联调
- 控制频率
- 单独准备机器人账号

## 9. 建议的联调顺序

1. 先把 OneBot 服务独立跑通
2. 用 Postman 或 curl 手工调一次 `/send_group_msg`
3. 再在项目 `.env` 中填写 OneBot 配置
4. 后台新增一个测试群
5. 在后台点一次手动推送
6. 查看 `PushLog` 和目标群结果

## 10. 我建议你下一步做什么

最合适的下一步是：

1. 你确定准备使用哪套 QQ 框架
2. 我帮你把这份教程进一步细化成“NapCat 实操版”
3. 再补一个“推送自检页”或“测试发送按钮”
