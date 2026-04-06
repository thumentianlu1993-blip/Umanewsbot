# 翻译与术语库配置说明

## 1. 当前翻译能力状态

当前项目里翻译链路已经实现：

- 文章入库后可进入翻译任务
- 翻译前会先从术语库召回日文专有名词
- 翻译服务支持 `OpenAI-compatible` 接口
- 如果没有配置模型接口，会自动降级为 `dummy` 模式

说明：

- `dummy` 模式不会真正翻译，只会把日文正文原样回填，方便本地开发验证流程
- 要得到真实中文译文，必须配置可用的大模型接口

核心配置文件：

- [translation.py](E:\Codex\server\stable\services\translation.py)
- [models.py](E:\Codex\server\stable\models.py)
- [.env.example](E:\Codex\.env.example)

## 2. 配置真实翻译模型

在项目根目录复制环境变量模板：

```bash
copy E:\Codex\.env.example E:\Codex\.env
```

然后至少填写这些字段：

```env
TRANSLATION_PROVIDER=openai-compatible
TRANSLATION_MODEL=gpt-4.1
OPENAI_API_KEY=你的Key
OPENAI_BASE_URL=
TRANSLATION_TERM_LIMIT=20
```

说明：

- 如果你直接用 OpenAI 官方接口，`OPENAI_BASE_URL` 可以留空
- 如果你用兼容 OpenAI 协议的中转服务或私有网关，就填写它的 base URL
- `TRANSLATION_TERM_LIMIT` 表示每次翻译最多注入多少条术语

## 3. 术语库数据结构

后台术语库表是 `TermEntry`，字段如下：

- `term_type`
  - `horse`
  - `race`
  - `jockey`
  - `trainer`
  - `owner`
  - `farm`
  - `racecourse`
  - `org`
  - `fixed_phrase`
  - `other`
- `source_ja`
  - 日文标准词条
- `target_zh`
  - 你希望固定采用的中文译法
- `aliases_ja`
  - 日文别名列表，JSON 数组
- `aliases_zh`
  - 中文别名列表，JSON 数组，可先不用
- `notes`
  - 用于给模型的备注，例如“马名，不要意译”
- `is_active`
  - 是否启用
- `priority`
  - 优先级，数字越大越优先

推荐维护规范：

- 一匹马一条词条
- 一场比赛一条词条
- 常见固定短语单独建条，例如“競走馬登録抹消”
- `aliases_ja` 放常见简称、旧译名、片假名变体
- `notes` 只写真正有帮助的约束，不要写长段说明

## 4. 推荐知识库录入示例

### 马名

```json
{
  "term_type": "horse",
  "source_ja": "ソダシ",
  "target_zh": "苏打希",
  "aliases_ja": ["Sodashi"],
  "aliases_zh": ["白毛马苏打希"],
  "notes": "马名，固定音译，不要意译",
  "is_active": true,
  "priority": 100
}
```

### 比赛名

```json
{
  "term_type": "race",
  "source_ja": "大阪杯",
  "target_zh": "大阪杯",
  "aliases_ja": [],
  "aliases_zh": [],
  "notes": "日本JRA GI赛事名",
  "is_active": true,
  "priority": 90
}
```

### 固定短语

```json
{
  "term_type": "fixed_phrase",
  "source_ja": "競走馬登録抹消",
  "target_zh": "取消竞走马注册",
  "aliases_ja": [],
  "aliases_zh": [],
  "notes": "JRA官方公告固定表达",
  "is_active": true,
  "priority": 80
}
```

## 5. 如何在后台维护术语库

启动后台后，进入：

`/admin/stable/termentry/`

你可以：

- 新增术语
- 编辑译法
- 暂停某条术语
- 用优先级控制冲突时的召回顺序

## 6. 当前实际测试情况

已测：

- 术语召回函数可正常命中并返回固定译法
- 翻译任务链路可运行
- 未配置模型时可回退到 `dummy` 模式

未完成的实网联调：

- 没有拿真实 OpenAI-compatible 凭证跑过一轮完整翻译
- 没有验证长文、多术语并发场景下的成本和耗时

## 7. 建议你下一步怎么做

建议先录入三类术语：

1. 马名
2. G1/G2/G3 与经典赛事名
3. 常见固定公告短语

等你把第一批术语给我后，我可以继续帮你：

- 做一份“推荐初始术语模板”
- 补一个 CSV/JSON 导入器
- 优化提示词，让赛马新闻翻译更像专业赛马媒体口吻
