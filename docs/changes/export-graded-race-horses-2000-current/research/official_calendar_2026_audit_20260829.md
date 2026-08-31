# 2026 英法官方赛历与目标账本只读审计

## 结论

本轮使用冻结的 BHA 2026 flat、BHA 2025/26 jump Jan–Apr、France Galop 2026 flat/jumps
PDF 及其已保存 CSV，对 AQPS 语义修正后的 `12,047` 行 PREPARED 目标账本做了全离线审计。
AQPS 显式行固定为 flat/turf，不再继承页面 jumps 上下文；独立 AQPS 信息段不计入法国主表声明总数。
最终得到：

- 官方赛历输入 `375` 条；
- 唯一目标候选 `373` 条，其中已过赛历日期 `260`、未来 `113`；
- 来源侧未匹配 `2` 条：`Commonwealth Cup Trial` 不属于当前目标；`Betvictor EBF Nov. H’Cap
  Hurdle` 的 BHA 等级为 G2，而 TJCIS 通用目标为 G3，必须作为等级冲突审核；
- 英法 2026 目标 `497` 条，其中 `373` 条有官方候选日期，`124` 条仍为目标侧问题：
  `119 missing + 5 source_reused`；
- 旧英法结果证据中的 2026 赛果 `48/48` 场全部命中最终官方日期，合计 `314` 匹 actual
  starters，日期 `48/48` 一致，无遗漏、无日期冲突。

这只是赛历候选审计。`past_schedule_needs_result` 不能编译成 held occurrence，也不能生成实际参赛马；
只有完整赛果、取消/延期终态或 TRA 单马 history 中唯一赛事 occurrence 才能关闭该层。

## 冻结输入

- target ledger SHA-256：
  `88313a59972196ddd6a275c22a09f7c9c7b8ae9b23efc5f67045a34076961a49`
- target manifest SHA-256：
  `b507d21d0f7bc5eef9785cb9a230200bbdbdb81a63686f5f63476a26add1ec5d`
- BHA flat CSV SHA-256：
  `e3360e6a8723ebcf33b7f50a9587bef402d22ed041143e3938314736e983d401`
- BHA jump CSV SHA-256：
  `dd35ffeb704fbae40f617943b648c196d1f6dddcd24214ce145412686b784dbf`
- France Galop CSV SHA-256：
  `d0cb6017d5d0feb61990f79fbcbf3df883425ca02c5f7239e384e045d88d95a5`

底层四份官方 PDF 的 SHA、size、URL 均写入最终 manifest，并在审计时重新验证。全程
`network_requests=0 / database_writes=0 / approval=false`。

## 最终产物

目录：

`/Users/mentianlu/.codex/umanews-official-calendar-aqpsfix-2026-20260829.5y4PTf`

- manifest SHA-256：
  `2e78d352b1da3bf240d5b48e7d122dd7a6ca6b31e9f75bbf60f8df8aec81071f`
- `PREPARED` 内容与 manifest SHA 完全一致。
- candidates、target issues、source unmatched 及两份工具的完整 path/size/SHA 均由该 manifest 绑定。

产物继续是 `candidate_review_required / PREPARED`，不构成 target COMPLETE、held result、API 调用或
数据库写入授权。

最终本地验证：source discovery 整模块 `88/88`、本变更纯离线研究组合 `61/61`、本审计测试 `2/2`；
受影响 Python 文件只读 AST 解析、Django system check、`makemigrations --check --dry-run` 和
`git diff --check` 均通过。完整 `stable` 仍沿用此前未完成且未通过的结论，不能被这些聚焦绿灯替代。

## 匹配器修复与差分

1. 增加 7 个由既有 2026 赛果日期证明的赛事别名，候选从 `298` 增至 `305`。
2. 将 `Royal Ascot/Windsor/Lingfield Park` 等 BHA 品牌场地归一到 canonical 场地，候选增至
   `324`，并把 Commonwealth Cup 从 5 月 trial 修正为 6 月 Royal Ascot 正赛。
3. 增加 `50` 个逐条、来源可见的 2026 冠名/缩写/OCR 断词赛事别名；不引入通用 fuzzy 自动合并。
4. 唯一名称完全匹配优先于 OCR 距离。BHA 1000 Guineas 的 9f OCR 不再把目标错指到前一天的
   2000 Guineas。
5. 当目标和来源都给出 G1/G2/G3 时，等级改为硬门禁。由此移除 G3 generic 目标对 G1 Broadway、
   G1 Mersey 等来源的抢占；`source_reused` 从 `65` 降至 `5`。
6. 英国最低名称分数统一为 `0.5`，低分 Gordon Richards → Coral Charge 错配被移除；Coral Charge
   由显式历史名 `Sprint` 正确接管。

最终一对一守恒为：

| 范围 | 目标 | 候选 | 目标问题 | 官方来源 | 来源未匹配 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 英国 flat | 156 | 137 | 19 | 138 | 1 |
| 英国 jumps | 150 | 63 | 87 | 64 | 1 |
| 法国 flat（含 AQPS） | 129 | 113 | 16 | 113 | 0 |
| 法国 jumps | 62 | 60 | 2 | 60 | 0 |
| 合计 | 497 | 373 | 124 | 375 | 2 |

## 剩余问题分类

- 英国 jumps 的本批官方 PDF 只覆盖 2025/26 赛季 Jan–Apr 片段；`87` 个目标问题不能自动解释成
  未举行，需补后续赛季官方书或结果来源。
- 英国 flat 有 `19` 个目标侧问题，而当前 BHA 书已将其 `138` 条来源全部守恒为 `137` 个范围内
  候选加 `1` 个范围外 trial；这些目标需要逐项检查降级、改名、取消或 TJCIS/BHA 版本差异。
- 法国 `18` 个目标侧问题包括 `15` 个 AQPS flat 系列、jumps 的早季 Grand Prix de Pau/Nice 两项，
  以及已进入 source-conflict 删除提案的 flat Penelope。AQPS 已固定为 flat/turf；其 held 状态必须接
  France Galop 官方公报/结果，不能因主 Group/Listed programme 未列而推断未举行。
- 2 条来源未匹配均有明确原因，不能为了追求 source unmatched=0 强制塞入当前目标。

## 下一步

1. 独立审核 9 项 source-conflict proposal，发布新的 reviewed COMPLETE target 后重跑本审计。
2. 获取 BHA 2026/27 jump 后续窗口、France Galop obstacle、HRI 及美国剩余 official-held 输入；当前
   法国官方 flat 公报已确认 52 场、405 条实际出赛记录并生成 52 个非 runnable 冠军锚点。
3. 对已过日期的 `260` 个候选逐场补完整结果；先复用已有 `48` 场/`314` 匹证据，其余保持
   `past_schedule_needs_result`。
4. 账号登录/凭据和 entitlement 可用后，先执行 Montjeu 最多 16 GET、零业务写入 proof；成功后再由
   reviewed target/seed census 计算分批请求上限。
