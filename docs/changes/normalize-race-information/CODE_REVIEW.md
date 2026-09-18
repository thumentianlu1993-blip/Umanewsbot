# 独立代码审阅记录

审阅上下文：`01a0b33a-eb46-7bb3-85be-e4636240c72b`。首轮 `codex review --uncommitted`，返修后两次 `codex exec resume` 回到原上下文。内部始终 `sandbox_mode=read-only`，未启动新的实现子代理。CLI仅自身会话状态需要本机沙箱外落盘。

| 轮次 | 结论 | 处理 |
| --- | --- | --- |
| 1 | 5项P2 | raw/display双侧脱敏；冠军骑师条件；历史同着；预览日期名次适配；SQL召回折叠内部空白。全部返修。 |
| 2 | 原5项已解决，另5项P2 | URL大小写及userinfo；关联赛事空日期回退；候选结果名次；主要胜场关联加载；报告原赛名映射。全部返修。 |
| 3 | APPROVED（前轮5项及直接回归路径） | 14项独立无磁盘写入测试通过（9项纯函数＋5组内存验证），无新增actionable finding。 |

第三轮独立确认：原payload/diff不变，普通数据库行排序占位保护保持；主要胜场只有新开关开启才批量加载关联，隐藏赛事不泄露；报告保留原赛名/ISO日期，未确认计时不展示。数据库路径在独立review中使用替身，没有独立连接测试库。93项PostgreSQL实际通过记录由主线程提供，不能归因于独立reviewer；review输出所说“尚未完成”对应其输入时点，不覆盖主线程后续完成事实。

## 指纹

- 第1轮前：`985db5680f8076e4f96b3cdd26802fdc9e8c9f05283df949b4a49fc27b29bca2`；后：`ccce7767cd29cd98c9daed5efd1f7c33e9a73466115258c992146a06e38b179e`。
- 第2轮前：`0c65bbf19e2d5c56e38f97138c4c35dae743ed1afce7e33dd325d51c50e89bbb`；后：`0c65bbf19e2d5c56e38f97138c4c35dae743ed1afce7e33dd325d51c50e89bbb`。
- 第3轮前：`1f2db7a8eeeb46a380846d948934a1f5f2edd2fa7dc5617824957d21d3642cf5`；后：`1f2db7a8eeeb46a380846d948934a1f5f2edd2fa7dc5617824957d21d3642cf5`。

首轮整体指纹因全量测试新增 runtime 工件变化；逐项核对 tracked diff 和所有新增server文件hash相同，审阅中的业务代码未变化。第二、第三轮前后完整指纹相同。测试生成的runtime文件不提交。批准后只补测试结果、状态和交付文档，并移除新文件两处行末空格；清理前后两个文件的Python AST完全相同，业务行为未变。

计划的子agent独立审阅属于上一阶段，见 [REVIEW.md](REVIEW.md)，不冒充代码审阅或发布验收。

## 2026-09-18 上线前单位适配增量

原reviewer上下文继续只读审核两个应用/测试文件。第一轮REVISE发现候选继承旧来源单位、HKJC reviewed_import真值判断两项P2。已修复候选距离证据隔离；生产聚合确认reviewed_import为字符串，它已完全退出单位判断，HKJC合同只依赖明确官方来源、地区、年份、官方HTTPS地址及数字+m，发布权限不变。第二轮APPROVED，reviewer独立13项测试及反例通过；主线程35项限定测试通过。没有整仓复跑。原日志保存在本机/private/tmp/normalization-release[-r2]-review.log。

公开格式增量首轮发现候选等级继承来源P2及徽章入口不一致P3，均已修复；最终复审APPROVED，独立15项局部测试及合法/非法近似格式反例通过。等级文案/徽章共用无查询适配；候选等级/距离须用自身来源；源单位不明仍拒绝。日志 /private/tmp/normalization-release-r4-review.log。最终overlay实际25场聚合已复核：等级25正常，距离24正常/1原缺失，未知与冲突0。

最终复审日志SHA256 `92cf456ae5c7405fd4ee91b38eb0a56793ebe3b238bd9bd3eba1ed37ee8ee0ee`；37项限定测试日志SHA256 `4eee83aebc7cda8029ada0da654f3de3015de043060b880fdb9fbdfb493d687d`。最终固定镜像与正式发布验收见[发布记录](release.md)，已替代早期overlay待验证状态。
