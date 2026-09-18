# PR205 最终版本验证

应用提交 `7e111914d57083299ce452b6222ab9d38476e420`，CI头 `070fe61a154c5669480166d657c1fd5eb4a6cc19`；两者之间只有文档变化。

- 70项隔离PostgreSQL定向测试完整通过，退出0。
- [最终Linux/PG16 CI](https://github.com/thumentianlu1993-blip/Umanewsbot/actions/runs/35306749487) 候选5053项：16 failures、29 errors、20 skipped；45项发布合同通过。
- 同run固定历史基线a88bcbf6共4886项，314个唯一失败；候选45个失败均在此集合内。
- 另与此前生产d0bb40fb的5012项CI参考比较，45个失败ID完全相同。该生产参考不是同run主线重跑，保留此边界。
- 本机独立差集和固定子代理复核均为新增0；不称全量测试全部通过。原始result SHA和完整失败ID见[CI摘要](ci-summary.json)。GitHub汇总作业的最终状态另记入发布完成记录。
- 候选ZIP SHA256：`bcd525e3d3d0d8308dbb85fd71a77dc6d22c2224bfb8f451a3844620feed7cf7`；历史基线ZIP SHA256：`389b9f20105c4c7cd8af71aea72398909e9d6efc6d1fa5d9ed7d3647f16309b2`。

验收脚本经固定子代理复核，已修复配置了Healthcheck但未断言healthy、赛时只查页面全局片段、JRA缺时检查使用旧文案三处误判。现按字段核对完整北京/当地日期时间及名单；103/104/105明确12/13/11行。运行态补验两个worker队列及Nginx配置。

## 汇总日志延迟与等价门槛

GitHub汇总job105487455469在比较步骤输出约2.14MB日志，其中一个历史subTest ID长2,097,431字符。前生产run35242927242同一步骤曾耗时69分钟后成功，日志处理拖慢是有证据支持的推断，不能称远端汇总已经成功。

用户批准的门槛要求最终应用代码完成全量基线/候选失败比较，未要求所有平台job success。本次已取得同run、attempt1的完整原始结果，候选及基线job和45项发布合同job均success；两位固定reviewer独立复算完整ID差集并批准。临时发布wrapper改为在服务器重新核验固定result SHA、提交、计数、原始测试exit-code=1及完整差集，准确保留远端summary `in_progress/null`，没有填写all_jobs_success。

只读GitHub核实main保护未启用、required checks为空、rulesets为空；通过expected-head普通合并，没有修改规则或伪造check。完整工件、比较输出与哈希链保留在本次服务器受限evidence目录；仓库保留精简摘要。此调整仅改变同一技术门槛的证据取得方式，不改变应用提交、部署范围或既有测试结果。
