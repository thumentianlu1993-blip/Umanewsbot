# 验证记录

- 原校验器对三个外项目同名常驻服务的正向用例真实RED。
- 两轮独立review发现socket父目录/别名、依赖资源保护遗漏、非默认socket和扫描间依赖消失；逐轮真实RED后修复。新增权限反例同样先RED。
- 最终相关组合回归74项通过，零失败/错误/跳过。中间r3误填不存在模块导致加载错误，日志保留；已由正确入口的完整regression-final覆盖，不将失败记录写成成功。
- shell/Python/JSON解析、策略登记、diff检查通过。两份guard均触发完整测试计划，并包含新增ownership模块。
- 生产真实元数据只读检查成功，helper SHA `2958d80060ea50f88b593f9c7b166ea84040d93ffe4fa6162c1dbf866cd6d976`。只读取docker元数据，未替换运行校验器、未执行服务或数据库变更。
- 新候选661a0859仅含两份guard及promotion失败恢复，均与PR逐字一致。新只读单成员快照在本地SQLite演练promote/activate/verify成功、956赛事行不变；`production_shape=false`，不能代替线上续期验收。
- 原reviewer已关闭源码finding；最终恢复包review、固定HEAD完整CI与候选外交付核验仍待完成。

证据目录：`/Users/mentianlu/.codex/runtime/lifecycle-census-fix-20261104/`。生产仍为旧候选保护关闭态，恢复包尚未执行。
