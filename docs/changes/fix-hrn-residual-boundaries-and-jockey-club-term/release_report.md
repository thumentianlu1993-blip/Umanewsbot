# 发布与历史重处理报告

## 结论

任务 `fix-hrn-residual-boundaries-and-jockey-club-term` 已完成代码发布、生产历史候选复审、受控写入、
独立 verify 和最终 inventory。

- 代码已通过独立原生 review，PR `#22` 已合并。
- 生产 revision 为 `8cbee3e70bb1044248a18ed5521a1273d629d404`。
- 当前 `web / worker / beat` 统一运行镜像
  `sha256:02a83fbde219827ce5a49c633086057eb7d2957abb1e19c7b386205fc914c60e`。
- 冻结 36 篇中：`12 applied + 18 translation_failed + 6 review_rejected`。
- post-deploy inventory 另发现 8 篇同一 HRN dialog 结构污染；建立独立 cohort 后
  `8/8 applied + verified`。
- 本轮共审查 44 篇，20 篇写入并验证；未重发任何 QQ 消息。

## 代码发布证据

- 受审 fingerprint：
  `5a313e6a96917f4efdb2bb8c1301581d18173eca47d0f29f33d76635dc420481`
- 受审 content hash：
  `fbe390ee49584119e44a00bd7a27da864f1d150b400004af22b9b09ce6897651`
- reviewer session：
  `019f98b4-e9b2-7520-9b08-f04a3e01b2ec`
- reviewer 结论：`APPROVED`，无 P0–P3/actionable finding。
- release commit：
  `2592adacd9d5f0e08e4a2a93316de5d1f3c52c97`
- PR：
  `https://github.com/thumentianlu1993-blip/Umanewsbot/pull/22`
- merge/production revision：
  `8cbee3e70bb1044248a18ed5521a1273d629d404`

发布前恢复点：

- `.env`：
  `/opt/umanewsbot/.env.backup.pre-hrn-residual-20260725T162001Z`
  - SHA-256：
    `baef570546106ba5ec54f781b1c2f8e70ce14699b339d64a12d06cd7611632a3`
- PostgreSQL custom-format dump：
  `/opt/umanewsbot/backups/db/pre-hrn-residual-20260725T162001Z.dump`
  - `250941179` bytes、mode `0600`
  - SHA-256：
    `0ebd22ebdf419e8819545bb31ee97658ab43dc56ce82f95ca88fbd9fbd415296`
  - `pg_restore -l`：`1062` 行
- 旧镜像标签：
  `umanewsbot:rollback-pre-hrn-residual-20260725T162001Z`

部署执行 `bash ./deploy_lowcost.sh`；historical runner preflight 为 `migration_safe`，
worker 排空后重建应用服务。本次无待应用 migration。Django check、migration drift、
Celery ping、内外 healthz、首页和文章 `9623` 均通过。

## 冻结 36 篇结果

冻结 ID-set SHA-256：
`aba440437863e3c092e22fffc1ca77c9c29a82e53244d7f6942fc684267e978d`。

### Applied + verified（12）

`6373,6492,6626,6629,6642,8512,8805,8894,9045,9051,9062,9067`

### Translation failed（18）

`5712,5716,6158,6371,6488,6495,6515,6620,6637,6645,6646,8314,8657,8904,8962,9042,9279,9284`

失败原因均由 provider/占位符门禁生成：请求超时、确定性术语占位符变化、保护实体占位符伪造或
格式占位符变化。失败文章未写库。

### Review rejected（6）

- `8381`：以“中略”替代 26 匹赛驹训练明细。
- `6184`：两次候选正文均正确使用“美国赛马会”，但摘要持续生成明显语病。
- `6511`：遗漏多数赛驹的上次训练与最近出赛。
- `6631`：遗漏战术引语、血统段与多场经历。
- `8637`：遗漏凯里家族完整声明等关键段落。
- `8804`：明确以“此处省略重复模板”删除参赛表中间条目。

冻结 36 篇 completion：

- 路径：
  `/opt/umanewsbot/runtime/horse_profile_completion/news_body_history/hrn-residual-20260725/hrn-residual-20260725-completion.json`
- SHA-256：
  `6f2d600ab312ba5a88c588489d4c36cdae1b1d16baf4e4c6e6290a75926343b3`

### 冻结范围写入批次的 artifact 身份

以下路径均位于
`/opt/umanewsbot/runtime/horse_profile_completion/news_body_history/hrn-residual-20260725/`。

- `apply-b3-01/`
  - `candidate_manifest.json`：
    `adc962890a5fcbdc415ec4fbcf6d2349a911c00eb0b801abfb5ac049428776c7`
  - `approved_manifest.json`：
    `6e9ef52957cc91245da8d9949d9f8a66f5d89f41d824b929a1880246efd453fa`
  - `rollback/receipt.json`：
    `6bb060584d90bddf0b69d9d990cb3ec40458f70c9e8f073375675d0583f96e2a`
  - `rollback/rollback_manifest.json`：
    `1388a8cb6aa65eae94b56c3564a6a93110e2a8c2a10fb117614986489bc6704a`
- `apply-b3-02/`
  - `candidate_manifest.json`：
    `09bac09c7b3b6f9455d607709da736dc011ef0156bc0c8d35a664fa0b2350019`
  - `approved_manifest.json`：
    `bca594b70d1d33e491375aeda12276d48610b8f8a0ed352e99f87bde6eb49e22`
  - `rollback/receipt.json`：
    `23b01b5bca9dd86d9590be6d29e3352196be505e3fe4e14fa3e3c6e6c646daa0`
  - `rollback/rollback_manifest.json`：
    `067c73e5fe6f149f4fb2924e392c8d0ba52d1d64d2dce5bcd71d062193d3e4ce`
- `apply-b3-03/`
  - `candidate_manifest.json`：
    `5df4d8468753b4e8975d341e3a6fe49c48e6c04ee4dbbf63095e673b996f0332`
  - `approved_manifest.json`：
    `4525089e4886f554acb29d84fe681b5776f9fb80d36433f2ca01ae473350a21a`
  - `rollback/receipt.json`：
    `6bae78c3dc3d9e93caf3fe114a4b710996b7fcc30df817aeec0b8b88cdae19ca`
  - `rollback/rollback_manifest.json`：
    `b69f23be9dd5a1854f7b51b8df4567044daa16fab97056cfddc5ec2d5812e6d3`
- `apply-term-retry-01/`
  - `candidate_manifest.json`：
    `c711e0caac96f737b29a51a3586fde68d9375394497974ef90110cf6e20dab7a`
  - `approved_manifest.json`：
    `39f204d9dd10b192eed7c7626a5be9756f322e587ddfde968286ab5abf892130`
  - `rollback/receipt.json`：
    `94d2657cbedb5e085389942175e3f9ac345c560ac24834e163e4816890f2adca`
  - `rollback/rollback_manifest.json`：
    `12dd25563f4612b4cb0ecf7de85e28044dc7b78d889888b77f51a82317295d15`

## Post-deploy 新发现 8 篇

新解析器使下列文章从旧解析器下的 `source_clean` 变为 `source_changed`：

`5724,5737,6801,8506,9041,9621,9653,9783`

逐篇 diff 证明旧正文比新正文只多 `Race Video` 与 `×` 四行。8 篇均重新 prepare、逐篇审查、
apply 和 verify；`9783` 已公开且已有 sent delivery，本次只更新数据库与网页，没有重发 QQ。

- 独立 ID-set SHA-256：
  `f70b56c3aaa4d988c827f28aee076c43199312132be9774c1ccd010a4e51e137`
- artifact 目录：
  `/opt/umanewsbot/runtime/horse_profile_completion/news_body_history/hrn-residual-20260725/apply-discovered-dialog-01/`
- candidate SHA-256：
  `a049dc6eda61f31d71c4f5263952cc63768edc0e44b73d8fa0b1aa584cbeb794`
- approved manifest SHA-256：
  `7520ee9bd9ee785253c0813fd8146377dffbb01f81c388232e9645a25e387b34`
- receipt SHA-256：
  `73c5b5fac249563cdcf91fa5c46188658817e77a040ea0fd1094b7c9be19a95e`
- rollback SHA-256：
  `02a40848d33a9f265bd7c23198e29129a61deac4f824af309c8f950b4e52e062`
- completion SHA-256：
  `5e3702903dc7f7107d5e99e6287f864474b4c18baf84fd6145645c0877ec36ca`

## 最终验证

282 篇 HRN cohort 的 ID-set SHA
`3b297aaa2049e7d041882df77bcdb56523d56980d958aeb2d32f3222a7b08c0d`
未漂移。

最终 inventory：

- `source_clean: 171 -> 183`
- `source_changed: 111 -> 99`
- `source_blocked: 0`
- `published: 68`
- `qq_sent article count: 47`
- manifest SHA-256：
  `fc70db4dc49b37ed4ab4a94caa2db749882792e176027f97bf930ed23d0f70b9`

全部 5 个 apply 批次的独立 verifier 再次返回 `status=ok`；递归验证器核对 24 个
candidate/approved/receipt/rollback/inventory 文件 SHA 后返回 `status=ok`。
20 篇 applied 文章的 `body_ja_raw/body_ja_normalized` 与当前解析器逐字一致。
13 篇已公开文章详情均为 HTTP 200。写前/写后逐篇对比确认 20 篇的
`qq_delivery_count/qq_sent_count/qq_failed_count/workflow_status/published_to_web_at`
零漂移。

总体 closure：

- 路径：
  `/opt/umanewsbot/runtime/horse_profile_completion/news_body_history/hrn-residual-20260725/hrn-residual-20260725-overall-closure.json`
- SHA-256：
  `ab0d93035afc593ccb5822323c2e27ffa1f48b53ec8c53030023cbcd21d33328`

## 回滚边界

- 代码异常：使用旧镜像标签重建当前应用服务，并复核 Django、Celery、healthz 和文章页面。
- 单批数据异常：必须使用对应 receipt 与 rollback manifest SHA 执行 CAS rollback；外部编辑后
  rollback 会 fail closed。
- 只有确认本轮数据写入造成数据库级损坏时才考虑恢复整库 dump。
- `race_live_worker` 在本次发布前后均未出现在当前低成本运行容器中，本轮未擅自启动。
