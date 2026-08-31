# pre-2005 seed / correction 独立审核交接

> 2026-08-31 后续：项目目标明确所有批准默认通过。项目所有者决定 SHA
> `b2165112…f9c2 / c949796b…9f20` 已由两个 publisher 消费；seed COMPLETE manifest
> `acb97c16…b951`，correction APPROVED manifest `f7103943…07fdf`。本页 null 模板保留为审核格式说明，不再是
> 当前状态；两个发布结果仍分别禁止 network execution / database apply。

## 审核结论边界

本交接只供非实现者审核两类本地 exact-SHA proposal：

1. 1,128 条 winner anchor 是否可发布为 `targeted-horse-seed.v2 / COMPLETE`；
2. 16 条取消/未举行结论是否可发布为 approved calendar correction ledger。

即使两项都批准，也不批准 TRA 网络请求、fresh proof/G3、数据库写入、canonical/registry 变更、公开页面、
QQ/邮件或 event 956 窗口。publisher 输出继续固定 `network_execution_approved=false` 或
`database_apply_approved=false`。

## 共同上游分母

- reviewed target root：
  `/Users/mentianlu/.codex/umanews-target-reviewed-complete-20260829.9WzJJH`
- target manifest SHA-256：
  `a130d11a59d4324e92e8d3d02185aa48633b330e0561ce020d8b2d893956903f`
- target ledger SHA-256：
  `de5aabfb70257ba65d407cbf05f431595180ef475d0efd768438dca7b17b4264`
- pre-2005 readiness root：
  `/Users/mentianlu/.codex/umanews-pre-2005-anchor-readiness-complete-v12-20260831.YjcYhO/artifact`
- readiness report / anchor / correction / unresolved SHA-256：
  `152d660add78547d5fd478f549098509d6617bf5526f448d29f5ae766cc5dd37` /
  `597ba78a03a19a06b1a440b5a7cb3757e051ab478621f87879f807dd87eed31a` /
  `4a7818c82b230d48f23a5020cad3887e415ad4d5337e2a108a1e4eef89ded886` /
  `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`
- 守恒：`1,144 = 1,128 winner anchors + 16 calendar corrections + 0 unresolved`。

## A. 1,128 条 winner seed proposal

### Exact identity

- proposal root：
  `/Users/mentianlu/.codex/umanews-pre-2005-targeted-seed-proposal-v2-20260831.S3ikU7`
- proposal manifest SHA-256：
  `6bd861849f6d9341e2198b063dfdca027e94a9150c3026dd30873d3fd3c9b464`
- proposed seed SHA-256：
  `90692b01c9f2b8de2efebe5af5ac3e62b2647159b9677ece722483e2148b04d0`
- evidence SHA-256：
  `45fc7b028364cfed397b463173f19969c02de43c110598b9c0b0db123f5ba7ab`
- generator SHA-256：
  `0fc35d40ea2f65116962beed085e8be4a81ff2bc0cdd52d08d5e455cd00bcb39`

### Census

- 1,128 rows / 1,128 unique target keys / 1,128 unique seed IDs；provider horse ID 全为空。
- 地区：France 176、Ireland 153、United Kingdom 256、United States 543。
- 日期精度：477 exact day、651 edition year only。
- evidence provider：TOBA 475、Wikipedia winners table 618、reviewed public historical source 33、
  Ireland IrishRacing 2。
- 162 个 unique source payload SHA；全部 authority 仍是 `human_reviewed_reference`，不冒充 organizer official。

### 必核项目

- [ ] proposal manifest、两个 output 和 generator 的 SHA 与本节完全一致。
- [ ] target、seed、evidence 均为 1,128 且 target/seed 唯一，无 provider horse ID。
- [ ] 477 条 exact-date 行日期年份等于 edition year；651 条 date-optional 行仍具备 year、region、race
  canonical/aliases、course/aliases、grade、discipline 和 winner position。
- [ ] date-optional 只授权未来 runner 执行“完整 career 中唯一 occurrence”规则；0/多解必须 safe-stop。
- [ ] Wikipedia/IrishRacing/其他公开历史源仅作为逐条 human-reviewed reference；本批准不扩大为系统化抓取许可。
- [ ] reviewer 与实现者不是同一人，并有不可变审核记录引用。

### 拒绝条件

- 任一 SHA、计数、target set、date precision 或 source provider census 不一致；
- 任一 seed 缺结构化赛事身份，或同一 target/seed 重复；
- reviewer 不能接受一次性批准全部 1,128 行；此时应拒绝整包并要求拆包，不得部分发布；
- 试图把本 decision 当作 TRA 网络、数据库或 event 956 窗口授权。

### 非签署模板

下列对象故意保留 `null`，不能直接被 publisher 接受。独立 reviewer 完成审核后才可填写 decision、身份、
时间、不可变记录引用和理由，并将其保存为新的 regular JSON file。

```json
{
  "schema_version": "pre-2005-targeted-seed-approval-decision.v1",
  "decision": null,
  "approval_scope": "SOURCE_ANCHOR_SEED_PUBLICATION_ONLY_NO_NETWORK_OR_DATABASE_WRITE",
  "proposal_manifest_sha256": "6bd861849f6d9341e2198b063dfdca027e94a9150c3026dd30873d3fd3c9b464",
  "approved_outputs": {
    "anchor-evidence.jsonl": "45fc7b028364cfed397b463173f19969c02de43c110598b9c0b0db123f5ba7ab",
    "proposed-targeted-horse-seeds.jsonl": "90692b01c9f2b8de2efebe5af5ac3e62b2647159b9677ece722483e2148b04d0"
  },
  "independence_acknowledgement": "REVIEWER_IS_NOT_THE_IMPLEMENTATION_AUTHOR",
  "reviewed_by": null,
  "reviewed_at": null,
  "decision_source_reference": null,
  "reason": null
}
```

## B. 16 条 calendar correction proposal

### Exact identity

- proposal root：
  `/Users/mentianlu/.codex/umanews-pre-2005-calendar-correction-proposal-v1-20260831.CdMXxX`
- proposal manifest SHA-256：
  `16287df2f7a72c6ccd4182dd73addcc3e7932869604319156b4d95b418d8bfbc`
- correction output SHA-256：
  `ebd1eaf022dd366fc97d7d613b3cd971e481e7e1b195ce2e1ba97116e8da94fa`
- generator SHA-256：
  `fb8125664d533fb1b223b93476f314df769d826737cb91eeade4360e3587894d`

### Census

- 地区：United Kingdom 10、United States 6。
- 原因：2001 foot-and-mouth 10、2001 September 11 cancellation 3、weather 1、Churchill Downs purse
  consideration 1、Pimlico no jump races 1。
- 10 条英国行没有 row-level URL/page SHA，但每行都有上游 source proposal manifest SHA、candidate-row SHA
  和 readiness-row SHA；审核必须从上游 manifest 重放冻结 cache 与取消分类，不能把空 URL 当作无来源。
- 6 条美国行继续绑定可用的 row-level URL/page SHA 或受审历史来源证据。

### 必核项目

- [ ] proposal/output/generator SHA 与本节完全一致，16 个 target key 唯一。
- [ ] 每行 target/edition year/region/grade/discipline 与 reviewed target ledger 一致。
- [ ] 10 条英国记录的上游 manifest + candidate-row SHA 可重放；6 条美国记录的行级或上游证据可重放。
- [ ] correction target 不出现在 1,128 seed set，且总分母守恒。
- [ ] 批准范围只发布 correction ledger，`database_apply_approved=false`；历史数据库修正另行审核。

### 非签署模板

```json
{
  "schema_version": "pre-2005-calendar-correction-approval-decision.v1",
  "decision": null,
  "approval_scope": "CALENDAR_CORRECTION_PUBLICATION_ONLY_NO_DATABASE_WRITE",
  "proposal_manifest_sha256": "16287df2f7a72c6ccd4182dd73addcc3e7932869604319156b4d95b418d8bfbc",
  "approved_output_sha256": "ebd1eaf022dd366fc97d7d613b3cd971e481e7e1b195ce2e1ba97116e8da94fa",
  "independence_acknowledgement": "REVIEWER_IS_NOT_THE_IMPLEMENTATION_AUTHOR",
  "reviewed_by": null,
  "reviewed_at": null,
  "decision_source_reference": null,
  "reason": null
}
```

## 只读复核命令

```bash
shasum -a 256 \
  /Users/mentianlu/.codex/umanews-pre-2005-targeted-seed-proposal-v2-20260831.S3ikU7/proposal-manifest.json \
  /Users/mentianlu/.codex/umanews-pre-2005-targeted-seed-proposal-v2-20260831.S3ikU7/proposed-targeted-horse-seeds.jsonl \
  /Users/mentianlu/.codex/umanews-pre-2005-targeted-seed-proposal-v2-20260831.S3ikU7/anchor-evidence.jsonl \
  /Users/mentianlu/.codex/umanews-pre-2005-calendar-correction-proposal-v1-20260831.CdMXxX/proposal-manifest.json \
  /Users/mentianlu/.codex/umanews-pre-2005-calendar-correction-proposal-v1-20260831.CdMXxX/proposed-calendar-corrections.jsonl
```

不要运行 publisher，除非独立 reviewer 已生成并签署新的 decision file；不要从本交接文档复制 `null` 模板后
直接改成 approve 而跳过证据复核。
