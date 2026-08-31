# 350 场 reviewed-held 冠军 seed 扩展提案（2026-08-30）

> 历史版本：本页记录的 `d810272f…2441` 已被当前生成器重放拒绝并由 v2 取代。v2 发现两条旧第三方 winner
> 与 France Galop 唯一官方 winner 冲突，现为 311 复用 + 37 新增 + 2 替换；不得批准或消费本页旧提案。
> 当前事实见 `held_winner_seed_extension_v2_20260830.md`。

## 结论

当前 350 个 reviewed held target 均具备 SHA/size 完整的冻结赛果缓存和 actual-starter 名单。其中 313 个
target 已逐 target 对回既有 COMPLETE winner seed；剩余 37 个 target 均来自 2026 France Galop organizer
official 赛果，存在唯一 `finish_position=1`，可形成新的 winner seed candidate。

本轮只生成 `PREPARED_NOT_EXECUTABLE` 扩展提案和独立批准发布器。没有创建决定、COMPLETE seed、网络批次，
也没有调用 TRA 或写数据库。

## 冻结提案

- root：`/Users/mentianlu/.codex/umanews-held-winner-seed-extension-final-v1-20260830.3jfdjM`
- proposal manifest SHA-256：`d810272fe945316a0dbdf2aff6f3eaa86bf434c7d005e88cb8f0efeac1032441`
- existing bindings：313 行，SHA-256
  `f18b6a1b3b507e05f31d8372e842a3429825628ea59e9f0d139bba7ea4cb249b`
- new candidates：37 行，SHA-256
  `5f7d37833586ed82c45edb6284e752820051e0f5be6b97bbaadbaef8c817705e`
- combined seed candidates：350 行，SHA-256
  `f4d568e82809c4d7e82cb536d0f3f6433372f01d8692b0f13e38bb62ffc224cd`
- generator SHA-256：`bbb9fcf0d821b41b5ced10ff9dbafdc644b0d48ea6a03b65cbfba6fcbab649cc`
- 状态：`PREPARED_NOT_EXECUTABLE / approval=false / execution_ready=false`。

第二个空目录重放得到完全相同的 manifest 和三份 output SHA。

## 37 条新增候选的分布

- region/year：France 2026，37；
- grade：G1 1、G2 4、G3 32；
- discipline：flat 26、jumps 11；
- `Bright Picture` 在两个不同 target 获胜，保留两条 occurrence seed；只有取得相同 TRA horse ID 后才去重，
  不以同名预合并。

每条候选均重新验证：COMPLETE target、held proposal、France Galop source URL、cache path、SHA、size、唯一
冠军、日期、地区、等级和 discipline。313 条既有 seed 逐字保留，不能借扩展提案改写旧审核事实。

## 非执行请求投影

若 37 条全部独立批准，350 条 winner seed 的保守投影为：

- 14 个 region + edition-year group；
- batch size 20，共 26 批；
- 每 seed 最坏 16 GET，总上限 5,600 GET；
- 单并发、最短间隔 250 ms（不超过 4 req/s）、批间 30 分钟；
- 每批仍需 fresh exclusive-account proof 与 exact G3。

这不是网络计划或批准；publisher 产出的 COMPLETE seed 仍只能进入新的
`PROPOSED_NOT_APPROVED` batch plan。

## 独立批准合同

`publish_held_winner_seed_extension_approval.py` SHA-256 为
`606b38cefaaea16255366be69795c062e8ed553ec2cbd9d3368bb23976a1d303`。publisher：

1. 重读 COMPLETE target、PREPARED held proposal、313-seed COMPLETE artifact；
2. 在临时空目录完整重放 proposal 并比较 manifest/三份 output SHA；
3. 只接受带时区、非实现者 acknowledgement、immutable decision reference、exact proposal/output SHA 的
   regular decision file；
4. 批准后逐字节发布 350 行 `targeted-horse-seeds.jsonl` 与 COMPLETE manifest；
5. 不发网络请求、不写数据库。

当前没有真实 decision 或 APPROVED artifact，禁止由实现者自建 approve JSON。

## 验证

- proposal/publisher 专项：`8/8`；
- `runtime/research` 完整：`350/350`；
- py_compile、diff check：通过；
- 350 份 held cache：`350/350` path/size/SHA 匹配；ZEturf 81 与 Sporting Life 197 的离线 parser
  `278/278` 成功，parser 数字名次 name set 与旧 occurrence name set `278/278` 完全一致；该旧集合只用于
  winner seed，不是全体 actual starters，PU/F/UR 等另由 actual-starter census 补齐；
  France Galop 71 场 embedded starters 与 declared actual-starter count `71/71` 一致。

中途新增投影测试发现 fixture 只有 `edition_year` 时默认表达式仍提前取缺失 `year`；已改为显式两步读取，
专项重新全绿，最终 artifact 在修复后重新生成。旧中间目录不作为批准输入。
