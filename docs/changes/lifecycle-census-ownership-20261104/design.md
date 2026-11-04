# 设计

宿主 census 仍枚举所有带 Compose service 标签的运行容器，不使用 project filter。Umanews 本项目继续沿用原校验。任何运行 one-off 仍阻断。外项目常驻 web/worker/beat 仅在以下条件全部成立时排除：

- census 与重新 inspect 的容器 ID、service/project/working directory/one-off 标签、运行状态一致。
- 本项目必须有可核对的 web 锚点，最多三个不同服务；锚点镜像和发布目录完全符合预期。不能以缺失或重复的本项目容器建立归属依据。
- 外部容器镜像不是候选镜像；容器和镜像都没有 OCI revision、UMANEWS、lifecycle、race-live、race-sync 环境标记；镜像仓库不与本项目重合。
- 以本项目全部 Compose 容器（含停止容器、db/redis/nginx等依赖）建立受保护网络及挂载清单，与应用镜像锚点分开。两次 census 之间首次出现的全部本项目容器必须保持 ID 和归属标签一致，否则拒绝本次证明。停止容器保留声明网络名；外部网络名称和 NetworkID 均不得重合。拒绝 host/container/service 网络命名空间、宿主 PID/IPC、特权、额外capability/设备和 volumes-from。
- 外部发布目录及 bind/volume 来源与本项目发布目录、挂载来源没有相等或祖先/后代关系；解析宿主路径别名，拒绝 Docker socket及其父目录、proc/sys/dev宿主伪文件系统及/run/user运行时目录；非默认路径的docker.sock来源即使改名挂载也拒绝。只读时区文件允许共用。
- 缺失、畸形、漂移或无法检查的必要元数据均拒绝。Docker 镜像省略或 null Labels 表示无标签；容器身份标签仍不可省略。

新增只读 helper 由原 shell checker 调用。只在外项目分支运行，原本项目镜像、commit、环境键计数与 trust-root 校验不变。只允许 docker ps/inspect/image inspect，不执行 stop/up/exec。错误输出使用固定分类，不回显环境或 Docker 原始输出。

生产修复不得改写旧签名 checkout 或替换 Docker 输出。必须准备新固定候选和新 approved_commit 的续期 artifact，再经过更新后的精确发布包交付。新包需处理原失败留下的关闭态与恢复锁，不能直接重跑已有 deploy intent。

恢复包入口在锁内、排空前只读记录Beat是否运行。原本停止时，备份前失败禁止启动Beat，仅恢复worker后核验关闭态；失败保留锁/证据并停止消费者。原本运行时保留既有备份前恢复行为，不引入新配置开关。
