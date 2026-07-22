## ADDED Requirements

### Requirement: 新闻主表索引修复必须先完成生产预检 <!-- id: req-index-repair-preflight -->
系统 MUST 在修复新闻主表索引前确认生产代码版本、数据库版本、索引定义与依赖、磁盘、活动写入、备份身份和回滚入口；任一关键证据缺失时 MUST 阻止修复。

#### Scenario: 预检证据完整
- **WHEN** 运维人员准备修复已报告物理错误的新闻索引
- **THEN** 系统 SHALL 输出服务器 HEAD、索引定义与状态、活动任务、磁盘、备份路径、大小、校验结果和 SHA-256
- **AND** 只有全部必需门禁通过后才允许进入重建步骤

#### Scenario: 备份或索引身份不确定
- **WHEN** 备份不可读、索引不属于预期表或索引承担未声明的约束
- **THEN** 修复流程 MUST 停止
- **AND** 系统 MUST NOT 删除、重建或替换该索引

### Requirement: 索引修复必须在受控写入窗口执行 <!-- id: req-controlled-reindex -->
系统 MUST 在暂停新闻写入的维护窗口内使用 PostgreSQL 原生索引重建能力修复目标索引，不得通过删除文章、修改 slug 或跳过索引写入掩盖故障。

#### Scenario: 目标普通索引满足原位重建条件
- **WHEN** 预检确认目标为普通非约束 B-tree 索引且备份有效
- **THEN** 运维流程 SHALL 暂停相关 worker、beat 和后台文章编辑后执行原位重建
- **AND** 公开读服务 MAY 保持运行

#### Scenario: 重建失败
- **WHEN** PostgreSQL 重建命令失败或锁等待超过运行手册阈值
- **THEN** 流程 MUST 停止恢复写入
- **AND** 运维记录 SHALL 保留错误、锁状态和回滚决定，不得继续删除索引

### Requirement: 索引修复必须通过三层验证 <!-- id: req-index-repair-verify -->
系统 MUST 以索引目录状态、可用时的物理检查、事务内写入探针和恢复后的真实抓取共同验证修复，且写入探针不得污染生产数据。

#### Scenario: 修复验收通过
- **WHEN** 索引重建完成
- **THEN** `indisvalid`、`indisready` 和 `indislive` SHALL 为真
- **AND** 事务内写入探针 SHALL 成功并回滚
- **AND** 恢复后观察窗口内同类 B-tree 错误 SHALL 为 0

#### Scenario: amcheck 不可用
- **WHEN** 生产数据库没有可用的 `amcheck` 扩展
- **THEN** 验收记录 MUST 明确标记物理检查降级
- **AND** 系统 MUST NOT 把未执行的 `bt_index_check` 声称为通过

### Requirement: 索引物理错误必须触发 P0 可见信号 <!-- id: req-index-error-alert -->
系统 SHALL 在滚动任务和数据库错误摘要中识别 B-tree 插入或索引物理错误；任一命中 MUST 触发 P0 运维异常并保留索引名和首末发生时间。

#### Scenario: 最新抓取成功但近期有索引错误
- **WHEN** 某来源最后一次抓取成功但最近 2 小时存在索引物理错误
- **THEN** 地区或来源健康摘要 MUST 继续展示 P0 异常
- **AND** 最新成功不得清除该滚动信号
