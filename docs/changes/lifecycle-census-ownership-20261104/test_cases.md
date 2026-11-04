# 验证

- 真实 RED：原 shell 对隔离的外项目 web/worker/beat 三种形态均失败，原因是 unexpected Compose project。
- Docker 实际形态 RED：无 Labels/Labels=null 的镜像初版 helper 拒绝；单独回归后兼容 Docker 的无标签表示。
- 正向：三个独立同名常驻服务；本项目 Beat 停止时外部独立 Beat 仍可运行。
- 反向：同镜像、OCI revision、UMANEWS/lifecycle/race-live 环境标记、同仓库别名、共享 network name/ID、host namespace、共享/父子 bind、Docker socket、特权/PID/volumes-from、发布目录漂移。
- 不明态：inspect 失败、缺少网络/挂载/运行态/Env、停止竞争、镜像 ID 漂移、空仓库来源、标签变化、缺失 NetworkID、非绝对挂载路径。
- 保留原跨项目 Umanews、重复容器、one-off、缺少 Beat、commit/flags/目录不一致及关闭态恢复测试。
- 所有测试使用假 Docker 元数据，不访问真实 Docker/生产/第三方。现场 helper 只读核验与测试分开记录，不能作为生产激活证明。

- 独立review两项P1均真实RED：Docker socket父目录/符号链接别名；仅保护应用进程资源导致共享db/redis卷及网络漏检。补覆盖运行和停止依赖容器。
- 额外权限RED：宿主proc/sys/dev挂载、CapAdd、Devices、DeviceRequests不能被判为独立应用。

- 第二轮review反例真实RED共6项：非默认/rootless socket改名及父目录；两次census间db消失或归属标签变化。
