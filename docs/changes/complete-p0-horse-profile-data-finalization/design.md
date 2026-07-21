# P0 马完整资料补全收尾设计

## 现状

现有地区服务已经具备受控网络客户端、来源解析器、请求计数和 `ExternalHorse` 本地索引；P0 服务已经具备候选提取、身份判定、事务写入门禁、履历幂等去重和完整度计算。当前缺口位于两者之间：没有统一的单马补全 adapter 协议，也没有把完整生涯来源转换为完整审核 artifact。

## 架构

新增独立的 P0 补全 adapter 服务，避免把网络逻辑塞入 `p0_horse_profiles.py`：

1. `P0HorseCompletionRequest` 描述候选身份、地区、来源 URL、缓存和请求预算。
2. 地区 adapter 返回统一 `P0HorseCompletionPayload` 字典；adapter 只负责采集和规范化，不写数据库。
3. 规范化器把来源逐场结果转换为 `HorseRaceRecord` payload，并调用既有规范键函数做 dry-run 去重。
4. artifact writer 原子输出逐马 JSONL、审核 CSV、失败/冲突 JSONL、summary 和 SHA-256 manifest。
5. 现有 `complete_horse_profiles` 命令增加显式候选审核输入和 dry-run 路由；网络仍需单独 `--allow-network`。

## 来源路由

- 日本：JBIS/既有 netkeiba 外部马匹索引，官方单场来源仅用于核验。
- 中国香港：HKJC Horse Information 与往绩。
- 英国：Sporting Life Full Form，Racing Post/BHA 作为补充证据。
- 法国：Geny Carriere，France Galop 作为权威核验。
- 美国：Equibase Results，Horse Racing Nation 作为补充。

实现先允许 fixture 或缓存输入形成完整 payload；真实网络必须继续经过现有来源客户端、限速、缓存和请求预算，不新增绕过开关的 HTTP 路径。

## 身份与履历

候选纳入和身份确认分离。只有外部马匹 ID、既有 profile，或完整“多语种马名 + 父名 + 母名 + 出生年份”可跨赛事归并。海外远征的多来源记录合并为一条履历并保留全部来源证据。

履历状态映射固定为 `won`、`placed`、`finished`、`did_not_finish`、`disqualified`、`scratched`、`withdrawn`、`unknown`。只有实际出赛状态计入 `collected_start_count`。

## Artifact 与审核

artifact 目录不得覆盖已有有效 run。manifest 记录输入审核文件、adapter 版本、请求参数和所有输出文件 SHA-256。审核决定按模块保存：

- `apply`：满足门禁后进入既有事务写入入口。
- `ignore`：保留候选并记录原因。
- `conflict`：保留候选和原始证据，不写主表。

## 主线集成

当前 P0 worktree 与实时赛果主线存在迁移和模型分叉。本轮先在 P0 worktree 完成行为与测试；发布前必须将最新主线集成到新的发布候选，解决迁移编号冲突后重新运行测试和只读代码审核。
