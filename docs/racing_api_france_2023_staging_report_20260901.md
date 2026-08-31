# Racing API France 2023 五马 External staging 生产报告

## 结论

截至 2026-09-01，France 2023 已选定的 5 个 The Racing API stable ID 已完整写入 Umanews 的
External staging/candidate 层，并通过独立只读 verifier。写入没有创建 canonical identity、HorseProfile、
RaceEvent、registry 或公网内容；常驻 staging 写开关已恢复为关闭，赛事自动化运行态已完整恢复。

本报告只证明以下 5 个目标及其不可变 materialization，不代表其他马匹、年份或地区已经获准导入：

| stable ID | 来源展示名 | 出生日期 | 性别 | 父系 | 母系 |
| --- | --- | --- | --- | --- | --- |
| `hrs_26036913` | Westover (GB) | 2019-04-24 | H | Frankel (GB) | Mirabilis (USA) |
| `hrs_26368342` | Malabu Drive (GB) | 2019-05-26 | G | Frankel (GB) | Tates Creek (USA) |
| `hrs_26395453` | Zagrey (FR) | 2019-04-21 | H | Zarak (FR) | Grey Anatomy (GB) |
| `hrs_27593440` | Tunnes (GER) | 2019-04-04 | H | Guiliani (IRE) | Tijuana (GER) |
| `hrs_29132222` | Junko (GB) | 2019-04-29 | G | Intello (GER) | Lady Zuzu (USA) |

## 不可变输入

| 输入 | SHA-256 |
| --- | --- |
| execution ledger | `aa3d51d4b21716a10680bab164a0aa391e10b3348191d8b787dc1935cf5d3095` |
| batch COMPLETE manifest | `ed0295d95097908aef507b2c59b1da6e571586c48b5e00d4d48f63d94ddf7973` |
| 5/5 materialization manifest | `f7a1fa5e091f8a642b8ae348a2736493bf452b34ba3f1cc5b23f170f3ce51b99` |
| selected postprocess plan | `90d5613f5a5d8f5c4d97506b90f5630f1fbfb9b0291670676c24e922851e2f61` |

服务器 materialization 共 37 个普通文件、无 symlink；manifest 与 COMPLETE 相同，完整相对路径树 SHA 为
`757319b13504b83185ee630aa803fd2e3e150dae7ed5f6814e4e2c5ebb4c379e`。目录归 root:root 所有，目录
0500、文件 0400。

## Foundation 发布

- PR #137 merge revision：`1312c8de131bba6e5a6a3ee1b52a6a2d2fc14a03`
- production image：`sha256:85b94626e302036598cf67194d4c3bf7cb8f9f2ddda2e8de288df42fce4af253`
- migration leaf：`stable.0077_racing_api_horse_identity_staging`
- verified backup：494113960 bytes、0600、root:root、SHA
  `c72b594551e81a8f7f8a4f941594c07d2ffada2e20a0dba68c5feb3a4991f6a9`
- PostgreSQL 16 `pg_restore --list`：1359 行

发布入口在停止服务前生成 admission handoff 和 candidate-bound recovery manifest，在所有应用服务停止后
重新生成 closed-state bound handoff，再应用 0076/0077。release task 没有使用 host 上不存在的
`pg_restore`，而是通过当前 Compose 的唯一运行中 DB 容器验证备份。

## 零写 dry-run

dry-run 输出 SHA：`1344fe691f889b535d07320570896abd4f2b781f9a5a01b4d7bfadd785cdf7a1`。

| 类型 | 唯一行数 | create | update | skip | conflict |
| --- | ---: | ---: | ---: | ---: | ---: |
| import lock | 1 | 1 | 0 | 0 | 0 |
| import run | 5 | 5 | 0 | 0 | 0 |
| ExternalHorse | 5 | 5 | 0 | 0 | 0 |
| ExternalRace | 60 | 60 | 0 | 7 | 0 |
| ExternalRaceResult | 67 | 67 | 0 | 0 | 0 |
| ExternalHorseHistory | 67 | 67 | 0 | 0 | 0 |
| HorseNameVariant | 5 | 5 | 0 | 0 | 0 |

总计为 `create=210 / update=0 / skip=7 / conflict=0`，`database_writes=0`。7 个 skip 都是批次内不同目标马
共享的同一赛事操作；重复赛事 raw payload 已逐项一致。dry-run 明确报告 canonical identity 写与
out-of-scope horse 写均为 0。

## 正式 apply

常驻 release `.env` 一直保持 `RACING_API_STAGING_WRITE_ENABLED=false`。正式写入只给 no-deps one-shot
容器临时覆盖 true，并同时传 `--apply --allow-write`；全部 5 个 run 由一个外层数据库事务包裹。

- apply 输出 SHA：`3e8b167979f81aff41fac4146f6f06e3abf768524950ae57f3a31cfa3c1bab2e`
- run ID：1961、1962、1963、1964、1965
- terminal status：5/5 `applied`
- 报告逐 run 逻辑写操作：214；dry-run 的 210 是唯一表 action，差额 4 来自同一 import lock 在 5 个
  run 中各计一次、但全局只新增 1 行
- 批次内去重赛事操作：7

## 独立 verifier

verifier 输出 SHA：`ead2dc16b8fe964c0880384d9d26992ba5401a033e434e4e5872c00b489eef1b`。

写前到写后的全局表计数精确变化：

| 表 | 写前 | 写后 | 增量 |
| --- | ---: | ---: | ---: |
| `stable_externaldataimportlock` | 2 | 3 | +1 |
| `stable_externaldataimportrun` | 1960 | 1965 | +5 |
| `stable_externalhorse` | 12407 | 12412 | +5 |
| `stable_externalrace` | 4100 | 4160 | +60 |
| `stable_externalraceresult` | 56884 | 56951 | +67 |
| `stable_externalhorsehistory` | 0 | 67 | +67 |
| `stable_horsenamevariant` | 0 | 5 | +5 |

其余关键断言：

- 5 个 stable ID、5 个成员 manifest、run 1961–1965 一一对应；全部 SUCCESS 且已结束。
- 60 个唯一 race ID、67 result、67 history、5 variant 只绑定这 5 个目标马。
- STARTED import run=0，active import lock=0；TRA lock 行已释放。
- `HorseExternalIdentity=0`，name variant 只绑定 ExternalHorse，不绑定 HorseProfile。
- event 956 的 event/10 runners/10 results 写前写后 SHA 均为
  `e832c573727760bd1785604a74520f4f5c969166139894633abbe4b9be4bfb9a`。
- reference registry `740a9377…cff2` 与 TRA canonical registry `3bac3b64…a6da` 均未改变。

## 最终生产运行态

- shared deployment lock：absent
- canonical、active、runtime 的 10 个 `RACE_DATA_SYNC_*` flags：全 true
- `RACING_API_STAGING_WRITE_ENABLED=false`
- Web：Gunicorn 1 worker × 4 threads
- ordinary worker：concurrency/prefetch 1/1、1 GiB cgroup、20 task/262144 KiB child recycle
- race-sync worker：concurrency/prefetch 1/1、384 MiB cgroup
- 四服务：同一 PR #137 image/revision，restart=0、OOM=false
- Redis：`celery=0 / race_sync_v2=0 / race_live=7543`
- 资源：`MemAvailable=5785308 kB`、`SwapFree=1310716 kB`、磁盘可用 9867190272 bytes
- root、www、healthz、event 956：全部 HTTP 200

## 当前限制与下一阶段

本阶段没有解决跨语言 canonical 合并，也没有尝试按英文名直接关联日文或香港中文名。5 个 `hrs_*` 是
provider namespace 中的稳定身份，HorseNameVariant 只是来源展示证据；后续若要把它们桥接到 Umanews
HorseProfile，必须重新验证出生日期、性别、父母、国家/注册地、官方 ID 与多语言名称，并对冲突和一对多
候选进行人工审核。

后续 identity/module publish、verified HorseExternalIdentity、canonical apply、registry 变更和公网展示都
不在本次完成范围；扩大到 pre-2005、UK/USA、Ireland 或其他 France 批次也必须重新生成独立 manifest、
零写 dry-run、备份、apply 与 verifier，不能复用本批权限。
