# 测试矩阵

- V01：原超限INSERT继续触发23514/指定CHECK且零写；SQL文本有界，完整PG日志小于原512KiB，batch-012生命周期通过。原失败记录保留。
- V02：8个原缓存native在新profile执行，原manifest/hash/来源/descriptor验证不变；篡改字节、换源、宿主env注入、跨组/额外ID、路径越界均拒绝。
- V03：exact-ID profile优先、alias去重、普通类不转root、未知profile失败；collection不创建fixture或外部动作。
- V04：root仅精确单用例、uid/gid与cap集合固定；PG实际10001、正常stop和失败清理、无网络/socket、只读source；错UID/cap/选择拒绝。原root权限用例真实PASS。
- V05：镜像固定原始SHA/tree/字节pin、archive权限/成员、image ID/revision/marker/audit精确校验；证据缺失/漂移/额外字段/上限/错误testtree拒绝，不信宿主环境注入。
- V06：原镜像用例真实执行准备及离线断言，收集无执行副作用，重入不重建；构建失败、读取失败及清理失败保留失败。
- V07：现有lifecycle/source binding/fixture/外部verifier相关回归，P01不扩大业务改动。固定新SHA全量所有批次与native集合一致、无skip，verify_test_plan通过；独立review关闭finding。

- V08：旧exact3/exact2/remaining3 API实际读取冻结资源；旧server-only入口收集原迁移类；Linux源码uid10001、复制目标uid0时保留字节/执行位且无需CHOWN。
- V09：serial collection及候选外PG校验程序重建相同proof绑定输入；缺失/篡改proof拒绝；普通collect-only无构建，prepare-images明确准备。
- V10：准备进程走OwnedObserver预算；reader timeout后精确CID清理，清理异常保留主异常且继续回收本操作image；root回执UID/GID拒绝bool伪装。
