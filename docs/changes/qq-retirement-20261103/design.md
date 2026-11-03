# 实现与来源

生产窄候选为`680639625dee9d6ab70ae31f7e095cd5f0c85155`，基于实测运行镜像标签及4份容器源码逐字核对的`ad50abdb74b89669ab8ada2958b040877c1a1849`。

回移来源：Q01发送入口及末端保护`5b30966f`、并发领取凭证`f606ef7d`、Q02界面退出`cc5eb8e7`/`370c2093`、调度与Compose退出`e70724c9`，连同原合成测试`bc30d403`/`07ae0ee6`/`faf3b62c`。冲突只涉及旧测试文件末尾和不适用的历史交付文档，保留生产业务代码基线。新增零次离线重试回归及原子claim拒绝停用记录修复。

总许可QQ_CHANNEL_ENABLED默认false，发布时三个QQ开关均显式false。业务入口与BotPusher末端均判断许可；保留旧Celery注册名，使已入队消息被正常消费为终止结果，而非未知任务或新的重试。标记停用采用既有CAS，保护已发送回执、在途owner以及尝试次数；原子claim同时排除SKIPPED且last_error=qq_channel_disabled，不能仅依赖旧内存实例检查。

两个production Compose删除QQ专属占位服务，Beat移除QQ周期；独立真实OneBot容器另行按固定ID/image操作。所有共享DB/Redis/新闻/赛事服务保留。没有模型、迁移、requirements或Dockerfile变化；数据库保持0079。

主线修复与生产候选的`qq_auto_push.py`应逐字一致；测试方法相同。主线CI与窄候选120项PG回归分别绑定各自源码，不能互相替代。主线的其他未发布业务不得被误带入本包。
