# 最近赛事赛果定时收集与邮件审阅测试用例

## 1. RED 证据要求

实现前新增测试并真实运行，失败必须来自以下目标行为尚未实现：

- 最近 72 小时 selector 和 machine-bound target snapshot；
- 动态 route registry，不再接受静态 40 场映射；
- prepare 无额外人工 target approval；
- 完整名次/Also ran fail closed；
- durable email intent、附件和去重；
- 精确 bundle SHA 的 apply/verify。

RED/GREEN 命令、失败摘要、测试数量和时间写回本文件；不得用 import error、fixture 错误或未配置
数据库冒充 RED。

## 2. 时间与目标选择

- `race_datetime` 在窗口起点、终点和窗口外的半开/闭合边界。
- 上海调度时间与赛事当地 DST 转换正确。
- 只有 `local_date + timezone_name` 时，当地日期未结束不入选、结束后入选。
- 缺时区/日期进入 `time_identity_missing`，transport=0。
- cancelled/postponed、非公开、非 canonical duplicate 排除。
- missing、provisional、incomplete confirmed 入选；complete confirmed 不入选。
- complete confirmed 但 status scheduled 进入 status repair，不联网。
- pending event 离开 72 小时窗口后仍在 14 天内重试；完成/取消/延期/duplicate 后终结。
- Beat/Codex 漏过最多 14 天 28 个 slot 时，旧 slot 全部留下
  `coalesced_to_latest_due_slot` 终态，仅最新到期 slot 执行一次联网 prepare 和一份全局请求预算；
  超过 14 天明确异常。
- snapshot 保存 event/result identity SHA；任一字段漂移后 prepare fail closed。
- 调用者不能通过参数扩展 selector 以外 event ID。

## 3. route 与网络

- JRA/NAR namespace 唯一分流；冲突时零 transport。
- HKJC、英国、法国、美国按 region/provider/identity 唯一选择。
- 官方 route 优先规则不会覆盖 namespace 冲突。
- third-party candidate 明确保存 authority，邮件不得显示“官方”。
- route disabled、contract 过期、robots/terms/host/path 不符全部零 transport。
- route 与 adapter manifest 的 key/region/source/authority/modules/command transport 任一不一致时
  子进程未启动、transport=0。
- Sporting Life 正例使用 canonical `uk_sporting_life_detail`；使用
  `uk_sporting_life_results` alias 或其他 key 漂移时零 transport。
- HTTPS、redirect、超时、响应大小、请求预算、host 间隔和磁盘预算生效。
- 总开关或网络开关关闭时网络 0、邮件 0、业务写 0。
- provider 局部失败不丢失其他 event，但失败 event 不进入 reviewable scope。

## 4. 完整赛果

- 正常 1..N 完整名次通过。
- 同着按导入合同通过且展示明确。
- scratched/withdrawn/did_not_start 等不要求正常名次，但结构化状态保留。
- did_not_finish/pulled_up/fell/disqualified 等不会被文本占位符伪造成顺序。
- `Also ran`、`others`、`unplaced`、空名次、0/负数、非数字名次全部 blocked。
- 缺 runner roster、缺一匹应出赛马、结果数不匹配、重复马号、重复马名、无身份结果全部 blocked。
- 同一 event 多候选、来源/地区不匹配、unexpected event/module 全部 blocked。
- blocked event 不进入 dry-run apply scope。

## 5. bundle 与文件安全

- generation 不可覆盖；相同 canonical payload 可识别为同一 bundle。
- 任一文件 SHA、manifest、registry SHA 或 code revision 漂移时 verifier 失败。
- 临时目录未完成时 current/reviewable bundle 不可见。
- artifact root、generation、附件拒绝 symlink、`..`、越界、目录、特殊文件和超限文件。
- JSONL/CSV 稳定排序、UTF-8/LF 和 canonical SHA 可复算。
- review.csv 包含 event、时间、来源 authority、所有结果行和 blocker。
- dry-run 证明业务表、receipt 均零增量。
- review CSV 与 review payload 双向等价；候选变化但 review payload/CSV 不变、CSV 漏字段或漏行
  均在 apply 前零写入。

## 6. 邮件与重试

- 无缺口成功 noop，不创建 delivery、不发邮件。
- 缺口但 reviewable=0 时发送 blocked 摘要，不能包含伪赛果附件。
- 收件人为空或不恰好为一个地址时 fail closed。
- 新 bundle 先持久 `QUEUED` 再 SMTP；主事务 rollback 时 SMTP=0。
- 成功发送写 `SENT`，SMTP 返回非 1 视为失败。
- 失败写脱敏 `FAILED`，下一运行创建 retry intent 并可转 SENT。
- intent commit 后、SMTP 前崩溃可恢复；SMTP 成功后、SENT 前崩溃以同一 Message-ID
  at-least-once 重试。
- 已知 SENT 的相同 bundle/recipient 不重发；stale SENDING lease 可恢复。
- 两个并发运行只有一个联网/生成/发信，另一个返回 `already_running`。
- 附件 allowlist 精确为 `review_payload.json`、`review.csv`、`dry_run.json`、`manifest.json`；
  缺少、替换或 SHA 漂移的 `review_payload.json` 时不发送、不可批准且 apply 零写入。
- 邮件和日志不含 credential、cookie、header、原始 body 或未脱敏 exception。

## 7. 审阅后 apply

- 未提供完整 expected bundle SHA、approved event IDs、reviewer 或双确认参数时零写入。
- SHA 与文件、数据库 baseline、route registry 或 code revision不匹配时零写入。
- blocked/未批准/unexpected event 无法进入 apply。
- 子集批准只写批准 event。
- official approval 继续要求 official receipt；内部参考来源只能通过
  `human_reviewed_reference` approval，来源仍显示 internal reference。
- 人工审核写入不填写 official-only 字段/receipt，公开标签为“已人工审核赛果”。
- 每 event 单事务写 results、平台确认时间、status finished、approval/receipt；故障注入时该 event
  全部回滚。
- 批次第二个 event 中后段失败时，第一个 event 的数据库/ledger 保持一致，第二个 event 零写入，
  summary 为 applied + blocked。
- 已有完整正式赛果只执行 status repair，不重复结果。
- apply 后 verify 核对完整顺序、非完赛状态、event 状态、receipt。
- 同 bundle/scope 重放幂等。

## 8. 调度、部署与回归

- Celery Beat 与 Codex automation 两个北京时间触发点解析正确，使用同一 schedule slot。
- Beat/Codex 并发只允许一个 claim；Mac/SSH 离线时 Beat 仍执行；Beat 故障时 Codex 可执行。
- automation 只调用固定 wrapper，不接受 prompt 注入的任意 shell/目标服务器。
- wrapper SSH/目录/container/timeout 任一失败均非零且脱敏。
- Compose 两套生产配置均挂载持久化 artifact root。
- 默认关闭部署 smoke：network=0、email=0、business_write=0。
- 启用后一次受控 prepare 产生预期 bundle、单封邮件、业务写 0。
- `python server/manage.py check`。
- migration 正向/反向通过，之后 `python server/manage.py makemigrations --check --dry-run` 无漂移。
- 现有 recovery inventory/orchestration/importer 和 race-event lifecycle 回归通过。

## 9. 待记录证据

- RED：
  - `2026-07-27 22:57 CST` 新增
    `server/stable/tests/test_scheduled_race_result_review_contracts.py`，共 `8` 项契约测试，覆盖：
    72 小时边界与 pending、28 个遗漏 slot 合并、canonical route 与 alias 漂移零 transport、
    完整数字顺序与 `Also ran` 拒绝、`review_payload.json` / `review.csv` /
    `reviewed_row_digest` 双向等价、delivery lease / 稳定 Message-ID / at-least-once、
    `human_reviewed_reference` 与 `official` 分流，以及逐 event 原子 apply。
  - 语法验证：

    ```sh
    python3 -m py_compile \
      server/stable/tests/test_scheduled_race_result_review_contracts.py
    ```

    结果：退出码 `0`。
  - 有效 RED 命令：

    ```sh
    DB_ENGINE=sqlite CELERY_TASK_ALWAYS_EAGER=true \
      /Users/mentianlu/Code/umanews/.venv/bin/python \
      server/manage.py test \
      stable.tests.test_scheduled_race_result_review_contracts \
      --verbosity 2 --noinput
    ```

    结果：发现并运行 `8` 项；`1` 项通过、`7` 项按预期失败，退出码 `1`。通过项证明既有
    recovery order 审计已经拒绝 `Also ran` 并接受完整 `1..N`；七项失败均由目标服务
    `stable.services.scheduled_race_result_review` 尚未实现而触发受控 assertion，分别把 selector、
    slot coalesce、route、bundle/CSV/digest、delivery、authority planner 和原子 apply 的公开合同
    冻结为后续 GREEN 目标。测试数据库完整应用 migration，Django system check 为 `0` issue；
    不存在语法、fixture、数据库配置或网络错误。
  - 首次裸 `python3 server/manage.py test ...` 因系统 Python 缺 Django 被识别为环境问题，已改用
    仓库既有 `/Users/mentianlu/Code/umanews/.venv/bin/python` 消除；该次结果不计入 RED。
- GREEN：
  - `2026-07-27` 聚焦契约与 GREEN 集成验证 `11/11` 通过；加 recovery
    inventory/projection 与 lifecycle 相邻回归共 `94/94` 通过。
  - `manage.py check`、`makemigrations --check --dry-run`、目标 `py_compile`、
    wrapper `sh -n`、三份 Compose `config` 和 `git diff --check` 均通过。
  - Compose 验证仅临时创建指向 `.env.example` 的 `.env` 符号链接，结束即删除；未启动容器、
    未联网、未发邮件、未执行生产迁移或业务写入。
- 独立代码 review：
  - 首次独立代码 review session：
    `019fa425-c6fc-7e72-9483-5afa281fcfeb`，结论 `REVISE`，共 4 项 P1：
    apply 后 verify 错用写前 baseline、有效 schedule-slot lease 可重复进入 prepare、
    apply 未在 event/result 锁内重算 baseline、人工审核 authority 未贯通公开 renderer。
  - 四项 finding 均先补真实 RED。命令：

    ```sh
    /Users/mentianlu/Code/umanews/.venv/bin/python server/manage.py test \
      stable.tests.test_scheduled_race_result_review_contracts \
      --verbosity 2 --noinput
    ```

    结果：共 `16` 项，既有 `12` 项通过；四类 finding 分别表现为 `2 failures + 2 errors`，
    均来自目标合同缺失，不是 fixture、环境或网络错误。stale lease 接管正例同时保持通过。
  - GREEN 后聚焦契约扩展为 `17/17`：verify 只核对写后 approval/result/digest/authority，
    exact replay 返回 `already_applied`；同 slot 有效 lease 返回 `already_claimed`，
    stale lease 使用 claim token CAS 接管且旧 worker 不能写终态；apply 按 event -> results
    锁序重算 baseline；详情页按精确 approval ledger + 当前结果 digest 显示
    “已人工审核赛果”，官方结果保持“正式赛果”。
  - 真实 PostgreSQL 临时容器中运行
    `stable.tests.test_scheduled_race_result_review_postgres`，`2/2` 通过：并发同 slot 仅一次
    prepare；持有 event 行锁的并发 writer 提交后，apply 等待并在锁内识别
    `database_baseline_drift`。临时容器及测试库均已删除。
  - 聚焦、recovery inventory/projection/public pages 与 lifecycle 相邻组合共 `107/107`
    通过。下一门禁是复用同一 reviewer session 对四项 finding 做限定复审。
  - 同一 reviewer 限定复审确认原四项 P1 已关闭，但新增两项命令退出码 P1：
    `--verify` 空 approval scope 会以 `verified` 退出 0；apply 的 blocked、缺失 event 或
    unexpected event summary 也会静默退出 0。
  - 两项新增命令测试先真实运行：共 `2` 项，得到 `4 failures`（空 verify 一项，apply
    blocked/missing/unexpected 三个 subtest），精确证明旧命令未抛 `CommandError`。
    GREEN 后两项 `2/2`，完整聚焦 `19/19`；命令现在要求 verify 至少一个 `--approve`，
    apply 先输出逐 event JSON summary，再在 returned scope 不守恒、存在非
    `applied/already_applied` 或 unexpected 时抛 `CommandError`。
  - 最新聚焦与直接相邻组合 `109/109`，Django check、migration drift、`py_compile` 和
    diff 检查通过。待同一 reviewer 再次限定复审。
