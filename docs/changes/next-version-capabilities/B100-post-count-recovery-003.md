# B100 计数后现场核验包 003

状态：修订候选，等待原 R 只读复审；不含现场执行授权。用户授权仍仅为准备只读恢复包并交原 R 审核。此次未执行候选脚本、测试、SSH、Docker 或生产读取。

## 固定绑定

- 原 B100 manifest：`8ed1d55bb73b6fa680637f8769f8e037113717f32d739fccf42b033203221325`
- 原 B100 commands：`e15ca35a300f65447062d921cf0043854aec0752d9bc0f7d353709ecc19380d2`
- 原 count summary：`7189c774c154ce5975f38edc5c8a73be9db8eea13aea1f40ffb94f4d9f3b1064`
- 新 manifest SHA-256：`3ace75461053b349257804504baf9111b2dd3e48c7c86e57d96012054d4b7a84`
- 新 commands SHA-256：`26d297ddcc3db8b3714f9f55cb73b830dfa02059faa85e0062c82dc78f83b208`
- host-inspect.py SHA-256：`555df017f7f426290571bbe35f38f0d8c1b9c92339af74410b3087c00834ff80`
- run-once.py SHA-256：`96015ec0c4e7fb5e03b8d839056f41602269c260d3a338dfa88022d5c683b452`

## 对 002 复审 findings 的处理

002 原件保留。003 建立 fail-closed 状态路径：非预期路径、unsafe 文件属性、目录枚举变化/限额、文件竞态/限额、JSON绑定或schema错误、PID身份unknown/mismatch，均产生 STOP 并在后续文件/PID/Docker 观察前终止；仅显式 absent 的可选项继续。每个文件读取前先按总预算剩余量限制 `os.read` 大小，达到单文件极限不额外读取超限字节。目录项到达每目录或全局界限即停止，不取下一项。

本地 carrier 将 manifest/commands 各读取一次，以同一份已哈希 byte snapshot 解析和选取 SSH argv；不再第二次打开 JSON 来决定实际执行对象。SSH 命令中的base64 payload、commands字段与host脚本必须逐字节一致，并与manifest member SHA绑定。

远端 20 秒信号抛出 `DeadlineExpired(BaseException)`，不被 `except Exception`吞掉；专用 Docker 客户端 teardown 最多增加 1.5 秒，remote observer 上限因此写成 21.5 秒。SSH客户端30秒终止仍不证明远端脚本在transport断开时已结束；Docker client终止仍不证明daemon侧请求已结束。

## 精确范围

单次固定 SSH host snapshot：先比较固定boot id，再逐层 fd 锚定访问 H、固定子目录与部署锁；固定文件仅摘要或输出受限白名单字段；最多4个精确 PID身份；之后至多一次固定 CID 的 Docker inspect。**不执行 docker exec，容器 BASE 明确 `NOT_OBSERVED`**。不读DB、业务数据、日志、token内容、cmdline、环境、cwd、exe、mounts或labels。无清理、生产信号、锁/文件变更、重跑count或抓取。

客户端30秒、stdout32KiB、stderr4KiB；远端观察20秒，owned docker-client teardown grace 1.5秒；Docker inspect 5秒；读入总计256KiB、每文件64KiB、总列表160项/每目录128项、远端JSON32KiB。未知、超限或不匹配停止，不重试。当前现场、镜像内容、容器BASE和锁终态均未观察。

## 静态验证

仅完成 Python AST 解析、JSON与sealed SHA检查、commands payload逐字节相等、单次读取结构与命令参数绑定检查。未导入/执行脚本，未进行模拟调用、SSH、Docker、生产探测或数据访问。旧001/002报告及封存对象均保留。原R复审通过后，仍需用户对该精确manifest单独批准执行；本次不包含该许可。
