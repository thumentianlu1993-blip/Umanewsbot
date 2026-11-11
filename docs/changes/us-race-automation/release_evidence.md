# 美国采集层验证记录

## 当前完成边界

本批实现来源解析、只读采集和离线重放，并在既有来源分发入口增加 Del Mar 分支；没有新增生产 route、任务或发布开关。美国整体完整采集、生产写入和自然调度未完成。

方案 review：会话 01a1c709-9fcb-77f3-b73f-ec9bf92d9d3d，首轮发现缺编号候选键碰撞和等级过滤丢冲突；修订后同会话 APPROVED。

## TDD

命令统一使用本地隔离 SQLite，DB_ENGINE=sqlite、SQLITE_DB_PATH=:memory:；测试基类 SimpleTestCase 禁止业务数据库查询。命令入口只写临时输出目录；所有请求由 fake/mock 替代。

| 轮次 | RED（退出1） | GREEN（退出0） |
|---|---|---|
| Del Mar来源入口 | source_identity_missing、source_parser_proof_required，4项中3项失败 | 4/4 |
| TOBA/报名/changes/NSA | us_source_format_unsupported，8项失败 | 分组2/2、3/3、3/3 |
| 缓存和采集 | us_transport_unimplemented、us_collection_unimplemented | 4/4 |
| 验收命令 | Unknown command: verify_us_sources | 命令测试通过；合计17/17 |
| 同轮失败URL去重 | timeout被调用2次而非1次 | 5/5采集测试 |
| 真实格式差异 | NSA分组编号合并、灰花毛行、G1后缀，3项失败 | 合计21/21 |

原始命令、review及报告保存在本机 runtime/us-implementation-20261111。

## 独立审核和隔离范围回归

代码 reviewer 会话 01a1c722-3bdc-79c3-a1be-882ee6ecd155，保持只读。首轮四个P2均有真实反例：失败刷新替换回放入口、损坏PDF逃逸整批、跨年重放报名丢失、Montpelier重叠用药标记损坏马名。新增回归先得到3个失败和1个错误，再修复；复审指出目录入口也需校验表头，两个目录subtest均先RED再GREEN。当前美国模块26项通过。原三个解析finding已关闭，目录回执补修在同一会话复审APPROVED，四项finding全部关闭。

固定快照fd488c1b8b335ff5389faeeeeb3dd128151c3759（目录补修前）在Linux无网络容器完成273项范围回归、零跳过，verify_test_plan通过。包括美国、日港法来源分派、跨来源身份/地区和core/infrastructure。镜像sha256:262b3d18c36e8457263c9a63c6eb74c8f5c2ced725d87510bba08692adb67ca7，隔离PostgreSQL；未接触生产。目录补修后固定快照c00fb41503501d3a9e7f0f6956ad920a398c63c8（tree 2ff600156fa34d6c715b460a8d632cba5e6a590b）完成274项、零跳过，verify_test_plan通过；收据位于runtime/us-implementation-20261111/linux-v4。此后仅回写本节、任务/状态文档及ci-scope字节清单，业务与测试代码未变；远端CI另按PR精确head绑定。

工作流合同、4项合同测试和diff检查通过；没有跑全量CI。

## 来源实测与回放

- 一次有界真实 HTTP：31次请求，不访问Equibase、不读取生产或付费凭据。原始字节和fetched_at写入cache/receipts.json；已成功原件可按SHA复验。
- 使用同一缓存修正真实格式差异和审核发现后零网络回放：151条来源候选、29份已解析文档/目录、2类明确失败；当前报告仍返回 us_source_acceptance_incomplete。
- 151不是生产分母：TOBA有143条分级来源记录（Glen Cove同日第5/8场的两行均保留待核），NSA另有8场。研究阶段按赛名覆盖后的142+8口径已被纠正。
- NSA七场已举行分级赛的名单已解析，包含PU/LR等非完赛。赔率、逐匹着差、独立总名单校验等仍有缺口。
- Del Mar已解析5份报名（16/12/12/7/11匹）和8场出马资料；2个未来日期明确未发布。HTML不含独立总名单计数，observation不授予roster_complete。
- 等级冲突：Bob Hope TOBA Listed vs Del Mar G3；Mariann De Tejeda NSA条件册G3 vs赛果G2。均保留双方来源，不自动采用一方。
- 两类剩余失败：Virginia Fall普通赛的OC状态尚未映射，明确拒绝该文档；changes正文仍是11月8日，拒绝把旧日变更用于当前日期。
- 全窗口平地完整结果主源、所有赛场报名覆盖、生产身份、5/10分钟延迟和七天更正仍未验收。当前不形成生产发布包。

## 复验入口

在隔离环境执行：

    DB_ENGINE=sqlite SQLITE_DB_PATH=:memory: python server/manage.py test stable.test_us_automation
    DB_ENGINE=sqlite SQLITE_DB_PATH=:memory: python server/manage.py verify_us_sources --start 2026-09-01 --end 2026-12-31 --cache-dir <既有缓存> --output-dir <新报告目录>

离线为默认行为。来源/完整性不满足时命令保存report.json并非零退出，这是验收未通过，不是已上线。真实HTTP需要显式allow-network，并按根AGENTS.md既有授权范围执行。

## 平地完整赛果增量（2026-11-11）

新增纯 chart/补源解析与 `verify_us_flat_results` 只读验收入口。全窗口候选143条，已到日期104场
全部结果来源重放通过：877匹实际出走、139匹退赛、39场未来待赛、零错误、零网络。
实现与边界见 [平地赛果记录](flat_results.md)。这是来源层结果，生产身份、调度、写入及公开页
仍未验收；本批无迁移、配置或生产动作。独立 review 和固定树范围验证已完成，详见下文。


首轮独立审核会话 `01a1c876-cac3-7070-ae94-2c4cc18ba389` 提出两项 finding：赛程冲突遗漏分母、
ABR 必需节点缺失逃逸整批。真实反例先得到1失败/3错误，修复后39项美国模块通过；另补ABR退赛
名单一致性，缺失名单的真实反例先RED后GREEN。同一reviewer复审APPROVED，review前后指纹一致。

固定快照 `f4be31e641c0f9aa8d8821c14eae942a88815df1`，tree
`ad846606014c514786727040b105c8038d14ab0d`，在Linux无网络容器和隔离PostgreSQL完成287项、零跳过；
`verify_test_plan`通过，plan digest `7202b8b52bacfa2587d950c6eca23050105d3eeb23b35b8d6d4c99e43c18bcd3`。
镜像沿用 `sha256:262b3d18c36e8457263c9a63c6eb74c8f5c2ced725d87510bba08692adb67ca7`。
首次启动因macOS默认临时目录未向Docker共享而在运行任何测试前失败；将本次临时目录移到runtime后
完成上述验证，没有更改运行器或扩大网络权限。产物位于本机runtime/us-flat-results-20261111/linux-v2。

此后仅回写文档和ci-scope字节清单，不改变受测业务/测试代码；远端CI仍按PR精确head绑定。
本批保持Draft交付，无合并或生产上线。全量结果JSON保留各份来源URL/SHA/抓取时刻，CSV导出1016行，
包括877匹出走和139匹退赛；源文件及报表位于本机runtime/us-flat-results-20261111。
