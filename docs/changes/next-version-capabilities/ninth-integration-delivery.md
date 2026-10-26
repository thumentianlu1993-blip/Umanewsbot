# 第四批累计候选 PR243：只合并交付包

2026-10-07，Asia/Shanghai。独立审核、正式 CI 及候选外受信交付验证均已完成；G2 尚未获准，未合并或发布。人工门禁仅引用根 AGENTS.md。

## 固定绑定

- PR：https://github.com/thumentianlu1993-blip/Umanewsbot/pull/243；实时 OPEN / Draft / MERGEABLE / CLEAN。
- base：`6e6aded22764ebee3d6a97f2834f47d4b4baa7bb`。
- head：`8b9e1b9d7de2d265c9671dab761b8b86b5fd778f`。
- tree：`2aee73a3ec0d76fd03856f85e8b128d492f83798`。
- 受测 merge：`5a202b579f63198b88b6acd9c0ca7c60b6b2907a`。

## 能力与边界

累计包含 PR240/241/242：离线 HKJC 缓存复用、私有基本资料处理、既有单条赛绩强身份补连、新闻清洗追踪、翻译 claim/deadline 防护与完整结果 checkpoint、SQLite 时间兼容及马匹搜索空态。

第四批新增 A036 prepare-only 命令生成私人待审产物、B041 离线翻译预算审计核心、C041 首页有头条而普通新闻为空时的准确提示。预算核心包含 TranslationRetryBudget / TranslationRequestAttempt 两模型及 `0080_translation_retry_budget.py`；没有生产回填，也未接入真实翻译调度/费用 guard。prepare 命令没有 apply 或数据库写入口。C046～C049 修复历史迁移测试夹具和恢复断言，未改变生产恢复服务或迁移字节。

后续 A042/A043 reviewed-input 和 B046 离线消费者不在本候选。完整 H03/M02、可靠 outbox、真实覆盖和生产验收不能据此宣称完成。

## 验证证据

- C043 原 R `792d241747d597dbcc635c390c3857c20d246b7b` 批准集成准备；来源文件与原各线独立审核关联保留。
- 历史夹具完整复审 R `32a700e0daa1778533b844a68baf3ab200f81aaa` 批准，无 actionable finding；ROOT 实核 527 输入指纹。
- 正式 pull_request CI：https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/37498154616；48 批，6755 唯一 ID，6745 通过、10 项原白名单跳过，新增52项实际执行无skip。原分母、隔离探针、600/2100秒及max4控制保留。
- ROOT 由固定 main 提取候选外受信校验器，下载实际 CI 镜像、重新收集并核完整 IDs/分批、artifact、strict branch protection、base/head/merge；exit0，status verified。
- 收据：`/Users/mentianlu/.codex/runtime/pr243-trusted-delivery-001/delivery-receipt.json`，SHA256 `6ea2fa6c748948760dfe89bcb291a2b319e25b4c12e8278c224a6b6f61123464`。
- ROOT 实核监督/执行 PID29205/29208 均已退出、专用 Docker 空、FD 锁可重新取得。原失败和修复证据均保留。

## 提议 G2 范围

推荐仅将上述固定 PR 合入远端 main，不发布。获准后再核精确 head/base、required checks/保护规则，短时 integration lock 内将 Draft 转 ready、执行受保护远端合并并核 main 包含候选。已有旧 PR 的批准不适用于本包。

| 动作 | 本包范围 |
| --- | --- |
| 迁移 | 仓库新增0080迁移文件随代码合入；不在生产执行迁移 |
| 配置、服务重建/重启 | 无 |
| 生产数据、回填 | 无 |
| 功能开关、自动发布、真实费用guard | 无启用 |
| 真实抓取、付费、QQ/通知 | 无 |
| 验证 | 合并前精确绑定/required checks；合并后main包含关系 |
| 回滚 | 生产版本保持不变；主线如需撤销，按实际merge准备revert PR并依根AGENTS交付 |

本次没有可执行生产发布包：生产运行态、资源互斥、0080备份恢复与发布适用性尚需单独落实。选择发布方向时先补齐可审精确包，不能将“只合并”解释为发布许可。PR240/241/242保持原状，不包含关闭旧PR。

10/06容量节点的真实分母/吞吐证据缺口仍在；B034计数和A隔离资源具体批准仍待。10/09、10/16联调及后续观察窗口不因本地/CI通过而缩短。
