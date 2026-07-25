# 测试用例

## 资格与选择

- 覆盖 G1/G2/G3、J-G1/J-G2/J-G3、JpnⅠ/JpnⅡ/JpnⅢ的一期资格范围、去重、最高等级与稳定排序。
- 验证日本训练证据、唯一 Netkeiba ID、第二层官方赛事上下文、旧 blocker 排除、批次上限和查询预算。
- profile、P0 来源、qualification 或配置发生漂移时必须阻断。

## 官方锚点与身份共识

- JRA 与 NAR 分别覆盖直接马匹锚点和“赛事索引/详情 → 马号+精确马名 → 唯一马匹链接”路径。
- URL 必须为对应 allowlist 主机上的 HTTPS；每次请求必须有连接/读取超时，重定向逐跳复验。
- JRA `CNAME`、NAR `k_lineageLoginCode` 必须非空；零个或多个候选、缺字段、页面结构变化均阻断。
- Netkeiba 与 JRA/NAR 对马名、父、母、完整出生日期逐字段一致才可生成 A/A+ 候选。
- 年份级日期、国别后缀冲突、文字体系 alias 未解决、任一来源冲突均保持 partial 或 blocker。

## 网络与 artifact

- `--allow-network` 与环境开关必须同时开启；分 provider 限速，单匹总计不超过 6 URL/18 次传输，
  官方链不超过 3 URL/6 次传输。
- 覆盖缓存、checkpoint/resume、429/访问拒绝即停、parser/config fingerprint 漂移和请求账本。
- qualification、candidate、blocker、source evidence、summary、state、账本和 xlsx 全部绑定 SHA。

## 审核与提交

- approve 只接受 A/A+ `candidate_pass`，并从冻结的 Netkeiba/JRA/NAR 身份证据重新计算共识；
  只修改 candidate 字段并重算文件 SHA 也必须拒绝。
- 真实 prepare 候选必须携带 commit 复验使用的全部冻结选择字段；内嵌 candidate/blocker 必须与
  已哈希 JSONL sidecar 的规范字节完全一致。
- commit 复验精确批准 SHA、独立批准人、profile 快照、人工锁、资格、锚点、来源 ID/URL/SHA。
- 事务只填充仍为空的父、母和出生日期；任一漂移整批回滚，公开状态、履历和 P0 来源不变。
- 相同 SHA 只有在唯一 receipt、OperationLog、字段和结果完全一致时才返回零写 replay。

## 公开履历回归

- 公开马匹详情每页显示 20 场，升序和降序都能翻到后续页，翻页保留排序参数。
- 数字及已归一化的非数字名次展示不因本次身份补证改动发生回归。
