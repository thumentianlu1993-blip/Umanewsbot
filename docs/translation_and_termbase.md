# 翻译与术语库配置说明

## 1. 当前翻译能力

当前系统支持：

- 文章入库后自动进入翻译任务
- 默认在新稿落库后立即同步调用翻译接口，后台点进文章时可直接看到译文
- 翻译前先从术语库召回相关专有名词
- 通过 OpenAI-compatible 接口生成 `title_zh`、`body_zh`、`push_summary_zh`
- 翻译状态可见：`pending / translating / translated / failed`
- 失败原因、最近模型、重试次数、翻译完成时间会写回文章
- 人工改过的字段不会在重翻时被机器覆盖
- 支持单篇重翻和批量补翻历史文章
- 翻译结果会做完整性校验，遇到疑似半截译文时会自动重试
- 翻译运行会记录 `finish_reason`、token 用量和尝试次数，方便后台排查
- 对于术语库未提供中文译名的疑似马名，翻译会优先要求保留原始日文马名，不再擅自音译或意译

当前已显式支持两个提供方：

- `openai-compatible`
- `siliconflow`

如果没有配置可用的真实模型接口，系统会自动回退到 `dummy` 模式，只用于本地流程联调。

核心代码：

- [settings.py](E:\Codex\server\app\settings.py)
- [translation.py](E:\Codex\server\stable\services\translation.py)
- [tasks.py](E:\Codex\server\stable\tasks.py)
- [models.py](E:\Codex\server\stable\models.py)
- [.env.example](E:\Codex\.env.example)

## 2. 推荐的硅基流动配置

我已经把默认配置切到了硅基流动。

推荐值：

```env
TRANSLATION_PROVIDER=siliconflow
TRANSLATION_MODEL=deepseek-ai/DeepSeek-V3
SILICONFLOW_API_KEY=你的硅基流动Key
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
TRANSLATION_TIMEOUT_SECONDS=90
TRANSLATION_MAX_TOKENS=2400
TRANSLATION_MAX_ATTEMPTS=3
TRANSLATION_UNKNOWN_HORSE_LIMIT=12
TRANSLATION_TERM_LIMIT=20
AUTO_TRANSLATE_ON_INGEST=true
AUTO_TRANSLATE_SYNC=true
```

说明：

- `SILICONFLOW_BASE_URL` 使用官方 OpenAI-compatible 接口地址。
- `TRANSLATION_MODEL` 我默认给你设成了 `deepseek-ai/DeepSeek-V3`。
- `TRANSLATION_MAX_TOKENS` 用来限制单次翻译输出上限，长文建议保持在 `2400` 左右。
- `TRANSLATION_MAX_ATTEMPTS` 控制占位符遗漏、疑似半截译文等校验失败时的最大翻译尝试次数，默认 `3` 次；重试提示会累计保留此前约束，并附上缺失占位符的原文位置，避免修复一种违规时引入另一种违规。
- `TRANSLATION_UNKNOWN_HORSE_LIMIT` 控制“未在术语库命中、需要按日文原样保留”的疑似马名提取上限。
- `AUTO_TRANSLATE_ON_INGEST=true` 表示新稿落库后默认自动触发翻译。
- `AUTO_TRANSLATE_SYNC=true` 表示抓取任务内同步等待翻译完成，适合你现在这种“进后台就想直接看到译文”的工作方式。
- 改完 `.env` 后需要重启后端服务。

## 3. 模型建议

针对“日文赛马新闻 -> 简体中文 + 稳定 JSON 输出”这个场景，我建议优先用：

1. `deepseek-ai/DeepSeek-V3`
   硅基流动官方文档在聊天场景下直接推荐使用它，适合作为当前新闻翻译链路的默认模型。
2. `Qwen/Qwen2.5-72B-Instruct`
   如果你更偏好中文表达与指令遵循风格，也可以作为备选模型。

这里的推荐是我基于硅基流动官方文档中的模型示例和你当前场景做的推断。

## 4. 当前配置方式

### 4.1 硅基流动

```env
TRANSLATION_PROVIDER=siliconflow
TRANSLATION_MODEL=deepseek-ai/DeepSeek-V3
SILICONFLOW_API_KEY=你的Key
SILICONFLOW_BASE_URL=https://api.siliconflow.cn/v1
```

### 4.2 OpenAI

```env
TRANSLATION_PROVIDER=openai-compatible
TRANSLATION_MODEL=gpt-5-mini
OPENAI_API_KEY=你的Key
OPENAI_BASE_URL=https://api.openai.com/v1
```

## 5. 批量补翻历史文章

```bash
cd E:\Codex\server
python manage.py translate_news --pending --limit 20 --sync
python manage.py translate_news --failed --limit 20 --sync
```

说明：

- `--pending`：补翻待翻译文章
- `--failed`：重跑失败文章
- `--sync`：当前进程立即执行，便于本地手测
- 不加 `--sync` 时会走 Celery 任务队列

## 6. 术语库配置入口

推荐入口：

- [术语工作台](http://127.0.0.1:8000/console/terms/)

备用入口：

- [Django Admin 术语表](http://127.0.0.1:8000/admin/stable/termentry/)

## 7. 手测建议

建议这样验证：

1. 在 `.env` 里填好 `SILICONFLOW_API_KEY`
2. 重启服务
3. 在候选池里找一篇文章点“重新翻译”
4. 看状态是否从 `翻译中` 变成 `已翻译`
5. 进入编辑台确认人工改过的字段不会被重翻覆盖

## 8. 专有术语候选发现

新文章可通过旁路任务发现尚未进入正式术语库的马名、比赛名、骑手名和马主名。发现结果只进入候选池，不会直接影响正式术语映射。

```env
TERM_DISCOVERY_ENABLED=false
TERM_DISCOVERY_PROVIDER=rules
TERM_DISCOVERY_MIN_CONFIDENCE=60
```

- 正式术语主日文名和日文别名都会参与去重，停用术语也会参与。
- 重复发现会合并出现次数和文章证据，不会重复创建候选。
- 拒绝或忽略后的候选再次出现时保持原审核状态。
- 管理员接受后才会创建正式 `TermEntry`；合并时添加别名需要明确确认。
- 首版不进行历史全量回溯，单篇重跑可从后台候选新闻详情页触发。
