# 英国 racecard Group 后缀精确匹配发布报告

## 发布结论

冻结代码已部署生产，Group 后缀匹配能力进入运行镜像；scheduler、真实 runner 与公开门禁
继续关闭。event `924` 的新受控 prepare 因 tomorrow GB 请求 HTTP 429 fail closed，没有
manifest、initializer 或业务事实写入。

## 冻结身份

- review fingerprint：
  `f9b40a0ec60f3a75dbfcbaa36739e564575def8e5c88f56833b71419f6cb92f8`
- reviewed parent：`12d76e61850f1f847aba13ac1c07004040191728`
- approved content manifest：
  `aa92ba27a17592287c101aa16380fb80e1293a2f5e4ddf9510c35ed2b94b87f7`
- release commit：`ebab4aa8e4e855d644771584c010fa6b07b9992b`
- tree：`f9a04eccc5bbda31a2619f3642e32c51275f0cc2`
- source archive SHA-256：
  `75939622bb5a31b524fc7e339109c64565ef038f8ead1734d20905ece5a937b5`
- production image：
  `sha256:4443a9c418dd696c7faa4afec0ae34551bceec2e85d6c917fa27de706fe155dc`

## 恢复点

- 数据库：
  `/opt/umanewsbot/backups/db/pre-racecard-grade-ebab4aa8-20260718T090735Z.dump`
- 大小/权限：`198,033,727` bytes，`root:root 0600`
- SHA-256：`17ba9ccbe0e28fe765f0f449c78452664f39f204011a1b8decb873240afd3db0`
- 格式：`pg_restore -l` 通过
- 环境：`/opt/umanewsbot/.env.backup.pre-racecard-grade-ebab4aa8-20260718T090735Z`
- 回滚标签：`umanewsbot:rollback-pre-racecard-grade-ebab4aa8-20260718T090735Z`
- 回滚 image：
  `sha256:7f188f8fc85979ad6df3504c49e42aed4e0c41696f64301b2a33c6c888722981`

## 部署验证

- 镜像为 AMD64，OCI revision/tree 与生产 checkout 一致。
- registry SHA-256 为 `60fcc081a1e9f08b1fbe90633b5256bba05635199f34d2068aefea51d86ad402`。
- Django check、migration check、model drift、镜像 racecard sync `20/20` 通过。
- web、普通 worker、Beat、`race_live_worker` 均运行新镜像；内外 healthz 为 200。
- 只有 live worker 挂 secret ro 与 artifact rw；其余 app service 无这两类挂载。
- scheduler false、runner disabled、live queue 0、publication policy/allowlist 0。
- 生产保持 `9,867 events / 100,132 runners / 91,897 results`，全部 live fact 表为 0。

## 受控 prepare

run：
`/opt/umanewsbot/runtime/race_live_racecards/production-racecard-gb-924-grade-fix-20260718T091135Z`

- today GB：HTTP 200，`215,645` bytes，`1,379 ms`，response SHA-256
  `e0e32e0df476df8949a9a7b5be6a60db0be9e527b5904c9d63a4da8514274efd`。
- tomorrow GB：HTTP 429，`47` bytes，`374 ms`，response SHA-256
  `e4c164264df24ba41848041ac37a930dd9157e3b66081293922c1d354dc091e9`。
- 结果：`completed=false / request_count=2 / blocker=http_429`。
- 目录 `0700`；`report.json/requests.jsonl` 为 `0600`。
- report SHA-256：
  `3e37ecef79545aae09fa4609b89cd246a383ff4bf20c8ea268b2d3b242f1d91b`。
- requests SHA-256：
  `7c0ca959e9a70f10374a4f4713ee424494457e67635f0878bd4d191111a3d5d5`。
- `manifest.json` 不存在，initializer 未执行。
- HostBudget 只记录一次 `http_429`；业务/live 事实零变化。

## 下一门禁

本 blocker artifact 不得复用或手工补 manifest。退避后新 run 会再次产生最多两个真实请求，
需要用户新的显式联网重试授权；若以后得到成功 manifest，仍须单独审核后才能决定
initializer dry-run/apply/verify。
