# 2025 分级赛参赛马补全与生产导入设计

## 总体链路

```text
已冻结 2025 artifact + 生产只读 identity census
                  |
       官方赛历/赛果 source caches
                  |
      八地区 participant artifact v2
                  |
    provider-bound horse identity candidates
                  |
   分地区完整资料/血统/生涯补全 checkpoint
                  |
       reviewed production mapping
                  |
 prepare -> dry-run -> backup/maintenance -> apply -> verifier
```

## 最小改造原则

- 保留现有 UmaFans collector 的 checkpoint/fan-in/finalize，不把 Django 或生产凭据带进 GitHub
  Actions。
- 新增官方来源阶段输出统一的 provider-neutral race/participant rows；不把每个站点逻辑塞进现有
  HTML parser。
- 生产 identity census 由独立 Django 只读命令生成，artifact 只携带脱敏业务身份和数据库 identity
  SHA，不携带凭据。
- 复用现有 P0 HorseProfile reviewed-artifact apply；新增的是“年度参赛 artifact → P0 候选/映射”的
  桥和三个新地区/四个中东国家的 source adapters，不另写无门禁导入器。

## 阶段

### A. Gap census

只读工具验证七文件 SHA/行数，输出按地区的赛事、participant、unique horse、名称脚本、profile state
和 error code。生产 census 输出 HorseProfile 完整度、候选匹配多重性及已有 source identity 分布。

### B. Participant v2

- `umafans_races`：沿用五地区结果。
- `official_catalogs`：发现 AU/DE/UAE/SA/QAT/BHR 2025 分级赛。
- `official_results`：逐场抓正式结果并规范实际参赛状态。
- `merge_participants`：按 provider race/horse identity 合并，不按同名跨 provider 自动合并。
- `finalize`：生成 v2 artifact；旧 checkpoint 因 policy/tool version 改变必须 fresh start。

### C. 生产身份映射

只读命令针对 participant v2：

- 从现有 RaceEventResult `source_refs` 取既有 provider horse identity；
- 对候选 HorseProfile 构建 provider ID 和四字段索引；
- 输出 `bind_existing/create_new/ambiguous/blocked`，不修改数据库；
- reviewed mapping 必须逐项绑定候选 fingerprint，变更输入后失效。

### D. 完整资料补全

按 provider-bound candidate 使用现有 P0 batch checkpoint。新增 adapter 仍输出现有
`p0-horse-completion.v1` 规范 payload；若字段权限不足则 blocker，不制造 placeholder。每匹马独立
checkpoint，允许按地区/批次恢复。

### E. 生产导入

扩展现有 reviewed P0 apply 以接受年度 scope manifest；先 dry-run，再由精确 G3 执行。所有新档案
保持 draft/ready，`auto_first_publish_enabled=false`，不触发 QQ、邮件或自动发布。

## RacingRegion

生产模型新增 `australia`、`germany`、`middle_east` choices；中东具体国家仍存 `country`。这是 choices
和业务枚举变化，不依赖把新增地区降级成 `other`。迁移只改变字段 choices state，不改既有行。

## 回滚

- artifact/网络阶段：丢弃新 output，不影响生产。
- 部署阶段：回滚代码；choices migration 不改实际数据结构。
- apply 前：恢复写前 dump 或停止。
- apply 后：优先使用 artifact 生成的 exact reverse ledger；只有 verifier 无法安全反向时才恢复完整
  dump。不得删除不在 scope 内的 HorseProfile/TermEntry/HorseRaceRecord。
