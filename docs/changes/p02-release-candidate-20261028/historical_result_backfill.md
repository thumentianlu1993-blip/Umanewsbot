# TRA 一次性历史赛果补采

## 用途与边界

全批赛事仍按原覆盖口径交付。自然 TRA 赛果调度只覆盖当天和过去七天；本入口为已纳管但缺少历史结果的精确目标补采，普通调度的日期条件不变。当前目标数量上限为 19，每场最多一次 `result_by_id` 请求，不跨来源、不恢复 retired 登记、不改变 v1 authority。

manifest 绑定镜像 commit、有效时间、event/source ID、namespace、external race ID、region、真实 local_date、owner/enrollment generation 和 standing policy/registry/route 摘要。命令从镜像 `/app/.umanews-release-commit` 读取代码身份。有效期最长 30 分钟；以获准的最终 manifest SHA 和发布包为准，本文不是执行授权。人工门禁仅引用根 `AGENTS.md`。

## 命令与执行顺序

入口为 `python manage.py backfill_historical_tra_result`，必须传入：

- `--manifest`：最终私有 manifest 路径。
- `--manifest-sha256`：获准文件的字节摘要。
- `--event-id`：manifest 内单个 event。
- `--receipt-directory`：manifest 绑定的持久私有目录，属当前 UID，权限不向组或其他用户开放。
- 默认只读检查；`--apply` 执行一次请求及写入。

发布 coordinator 在已有发布互斥范围内逐个执行，所有调用使用同一个持久收据目录。不得通过更换目录、复制 manifest、改摘要或删除占用文件重新请求。命令不会领取其他目标的 claim；目标自身有未过期 claim 时延后。

执行顺序为：校验 manifest 与当前业务准入 → 来源 registry 与 host 配置 → 再次核验身份并持久占用 → 既有日额度与 host 限速下单场请求 → 保存响应材料 → 新时钟检查合同并锁行重验身份 → 共享 parser/observation/标准 writer → 公开 reader 验证。

写入外层事务按 registry barrier/membership、lifecycle、event、projection、tracking、enrollment、source 顺序取得锁。只有实际 `projected` 且公开验证通过才记录成功。普通许可、内容完整性、并列名次和终态判定继续由标准链路执行。实际 transport 调用前（host 等待之后）复核合同、准入和写入开关；取锁后重新取时钟并复核合同和许可。已知结果写入/公开开关关闭时，dry-run 与执行均在占用前拒绝。

## 材料与失败处置

请求前以 O_EXCL 创建 `<manifest_sha>-<event_id>.json` 并 fsync；它表示请求已占用、结果可能未知，重跑不能再次请求。随后分别保存 `.response.json` 和 `.outcome.json`。响应文件含解析后的 provider JSON、来源 URL 和原响应 SHA；不声称该 JSON 文件字节本身与原响应 SHA 相同。

404、套餐拒绝、非终态、身份漂移、许可过期、完整性或公开校验失败均保留 gap。网络失败和执行中断不自动重试。已下载材料供后续受控离线处置；当前命令没有离线重放选项。失败不应删除占用或伪造成功回执。业务投影失败回滚事务，文件材料继续保留；不改动已有 A/B 库、备份或其他目标。

## 当前验证边界

直接离线组合 32 项通过：manifest/重复与并发占用、网络关闭、404与失败收据、重跑不重复 fetch、默认只读命令、普通七日边界，以及 20 日前完整终态通过真实 admission、writer 和公开 reader。使用隔离 SQLite 与禁止 socket 的测试入口；不代表 PostgreSQL 并发行锁验证、真实 TRA 套餐可用性或线上验收。

完整新增链路正在独立 review；最终 commit、镜像、精确 manifest、生产检查和发布包仍需更新。尚未执行真实补采或生产发布。
