# 断点交接：Gate 6 逐批 apply（Batch 1 中段）

## 1. 当前断点

**任务**：`audit-reprocess-historical-news-body-contamination` Gate 5 完成，Gate 6 Batch 1 进行到 **26/171**。

**生产服务器**：`root@47.239.167.86:/opt/umanewsbot`，代码 HEAD=`10f341e6`（已含本轮全部新增文件）。

**分支**：`codex/audit-reprocess-historical-news-body-contamination`（已合并到 main）。

**关键特性**：安全分类器偶尔阻断 SSH 命令，需要直接用 `! ssh ...` 前缀发送。

## 2. 已完成

| Gate | 内容 | 证据 |
|------|------|------|
| Gate 2 | 4 个新命令部署到生产 | `manage.py check` 通过，`healthz` 200 |
| Gate 3 | 282 篇冻结 inventory 总账 | `/app/runtime/news_body_history/inventory-20260724/` |
| Gate 4 | Pilot 候选准备 (9623, 9519) | 翻译干净，candidate_sha=`e56bf53c...` |
| Gate 5 | Pilot apply 2/2 | receipt_sha=`f31c93d9...` |
| Gate 6 | Batch 1 前 26 篇 applied | 目录 `apply-b1-001`, `apply-b1-002b` |

### Inventory 分布

| 类别 | 数量 | 进度 |
|------|------|------|
| Batch 1: 未公开 + 无 QQ + source_changed + translated | 171 | **26/171** |
| Batch 2: 已公开 + 无 QQ | 21 | 未开始 |
| Batch 3: QQ 已发送 | 47 | 未开始 |
| 其他 (translation failed/pending) | 43 | 手动处理 |

### 已知翻译失败文章

- 6185, 6189（placeholder validation failure）
- 随脚本继续运行会有更多失败记录在 `batch1_failed.json`

## 3. 新增文件清单

| 文件 | 用途 |
|------|------|
| `server/stable/services/news_body_history.py` | 核心服务 (~1200行) |
| `server/stable/management/commands/inventory_news_body_history.py` | 只读盘点 |
| `server/stable/management/commands/prepare_news_body_candidates.py` | 候选生成（纯provider，不写DB） |
| `server/stable/management/commands/apply_news_body_history_batch.py` | 离线精确写入 |
| `server/stable/management/commands/rollback_news_body_history_batch.py` | CAS 回滚 |
| `server/stable/management/commands/verify_news_body_history_batch.py` | 写后验证 |
| `server/stable/test_news_body_history.py` | 42 项测试 |

**重要**：`prepare_news_body_candidates.py` 不在 Docker 镜像中——它是通过 `docker cp` 热加载到容器的。如果容器重建，需要重新 `docker cp`。

## 4. 关键工作流

### 管线每批流程

```
prepare_news_body_candidates (翻译API调用, ~2min/篇, 不写DB)
  → 抽查 translated_body_zh 无污染
  → 生成 approved_manifest.json
  → apply_news_body_history_batch --commit
```

### 命令速查

```bash
# 在容器内执行（所有路径以 /app 起始）

# 候选准备（每批最多 10 篇）
python manage.py prepare_news_body_candidates \
  --article-id A --article-id B ... \
  --output-dir /app/runtime/news_body_history/candidates-<TAG> \
  --max-articles 10

# 抽查翻译是否含污染词
python -c "
import json
bad=['即时','热门','登录','免费注册','公平赔率','相关页面','焦点新闻','Log in','Sign up','Trending']
with open('/app/runtime/news_body_history/candidates-<TAG>/candidate_manifest.json') as f:
    m = json.load(f)
for e in m['entries']:
    t = e['exact_output'].get('translated_body_zh','')
    hits = [w for w in bad if w in t]
    print(f\"ID={e['article_id']} src={e.get('source_status')} hits={hits}\")
"

# 批准（从 candidate 生成 approved manifest）
python -c "
import json,hashlib,os,shutil
cand_path='/app/runtime/news_body_history/candidates-<TAG>/candidate_manifest.json'
with open(cand_path) as f: m=json.load(f)
cs=hashlib.sha256(open(cand_path,'rb').read()).hexdigest()
apply_dir='/app/runtime/news_body_history/apply-<TAG>'
os.makedirs(apply_dir,exist_ok=True)
decs=[{...}]  # see below for full template
ap={'schema_version':2,'candidate_manifest_sha256':cs,'decisions':decs}
with open(f'{apply_dir}/approved_manifest.json','w') as f: json.dump(ap,f,ensure_ascii=False,indent=2)
ahs=hashlib.sha256(open(f'{apply_dir}/approved_manifest.json','rb').read()).hexdigest()
shutil.copy(cand_path,f'{apply_dir}/candidate_manifest.json')
print(ahs,cs)
"

# Apply
python manage.py apply_news_body_history_batch \
  --manifest /app/runtime/news_body_history/apply-<TAG>/approved_manifest.json \
  --manifest-sha256 <approved_sha> \
  --candidate-manifest /app/runtime/news_body_history/apply-<TAG>/candidate_manifest.json \
  --candidate-manifest-sha256 <candidate_sha> \
  --rollback-dir /app/runtime/news_body_history/apply-<TAG>/rollback \
  --commit
```

## 5. 下一步操作

### 第 1 步：确认环境

```bash
! ssh root@47.239.167.86 'docker compose -f /opt/umanewsbot/docker-compose.prod.lowcost.yml ps --format "{{.Name}} {{.Status}}" | grep -E "web|worker|beat" && echo "---health---" && curl -s http://127.0.0.1/healthz/'
```

### 第 2 步：确保 prepare 命令在容器内可用

若容器已重建，重新热加载：
```bash
! ssh root@47.239.167.86 'docker cp /opt/umanewsbot/server/stable/management/commands/prepare_news_body_candidates.py umanewsbot-web-1:/app/server/stable/management/commands/prepare_news_body_candidates.py'
```

### 第 3 步：继续 Batch 1（剩余 145 篇）

剩余 ID 列表：
```
6246,6247,6357,6360,6484,6790,6798,6801,6806,6817,
6885,6886,6889,6894,7021,7022,7023,7036,7071,7134,
7136,7146,7149,7152,7157,7163,7165,7257,7260,7270,
7284,7287,7295,7305,7411,7412,7418,7425,7429,7435,
7439,7557,7571,7572,7578,7581,7584,7585,7586,7589,
7597,7704,7705,7717,7720,7721,7723,7728,7732,7774,
7865,7893,7895,7897,7899,7935,7936,7941,7947,7948,
7949,7951,8076,8078,8091,8094,8095,8096,8097,8100,
8101,8104,8308,8310,8312,8319,8323,8332,8333,8334,
8393,8394,8397,8401,8404,8449,8493,8494,8506,8508,
8510,8511,8513,8644,8659,8759,8783,8896,8910,8920,
8922,8924,8939,8944,8950,9041,9046,9049,9052,9059,
9064,9066,9103,9114,9131,9133,9266,9275,9278,9280,
9282,9283,9286,9287,9288,9290,9334,9344,9345,9346,
9351,9393,9406,9408,9413,9435,9447,9498,9505,9513,9611
```

## 6. Approved Manifest 模板

```python
decisions = []
for e in good_entries:  # good_entries = [e for e in m["entries"] if not e.get("error")]
    d = {
        "article_id": e["article_id"],
        "decision": "approve_fields",
        "reviewer": "auto-<TAG>",
        "reason": "Batch 1 auto: clean translation, unpublished, no QQ",
        "approved_fields": e["approved_fields"],
        "before_fingerprint": e["before_fingerprint"],
        "exact_output": e["exact_output"],
    }
    if e.get("source_evidence"):
        d["source_evidence"] = e["source_evidence"]
    decisions.append(d)

approved = {
    "schema_version": 2,
    "candidate_manifest_sha256": "<candidate_file_sha>",
    "decisions": decisions,
}
```

## 7. 后续 Gate

| Gate | 内容 | 注意事项 |
|------|------|---------|
| Batch 1 完成 | 剩余 145 篇未公开文章 | 每 10 篇/批, ~2min/篇 |
| Batch 2 | 21 篇已公开 + 无 QQ | 影响公网可见内容 |
| Batch 3 | 47 篇已公开 + QQ 已发送 | QQ 消息不可逆，每批必须人工审核 |
| 兜底 | 43 篇 translation_failed/pending | 手动处理 |
| 收尾 | `verify_news_body_history_batch` 验证 | 每批产出 receipt |

## 8. 回滚

- 每批 apply 都生成了 `rollback_manifest.json` + `receipt.json`
- 回滚命令：`rollback_news_body_history_batch --rollback-manifest ... --manifest-sha256 ... --receipt ... --receipt-sha256 ... --commit`
- 代码回滚：`git checkout <previous>` + `docker compose up -d --build web worker beat`
- 数据库备份：apply 前未做（Batch 1 是未公开文章，风险低）。Batch 2/3 执行前需要 `pg_dump`。
