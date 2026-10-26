# B100 计数后现场核验包 001

状态：准备交原 R 只读审核；**不含执行授权**。用户只批准了“准备本包并交原 R 审核”。本次未执行 SSH、Docker inspect/exec、生产探测或任何清理/信号/锁动作。

## 固定绑定

- 原 B100 manifest：`8ed1d55bb73b6fa680637f8769f8e037113717f32d739fccf42b033203221325`
- 原 B100 commands：`e15ca35a300f65447062d921cf0043854aec0752d9bc0f7d353709ecc19380d2`
- 原执行 outcome SHA：`c61f48693060ad2bf215552d627ef7b45fa41def5746fe2791b4323cb8556cc6`
- Count summary SHA：`7189c774c154ce5975f38edc5c8a73be9db8eea13aea1f40ffb94f4d9f3b1064`
- 新 manifest SHA-256：`208df6e22bc9b52e989ad04b36a98b935cf1facd0520747bebabfb7231871699`
- 新 commands SHA-256：`62718e0ebfe4b0ae8691afb621de167e74a0b671bd06373c850002e5bc8bfa7b`
- Host inspect script SHA-256：`cd515460b9d9698031d94984a18b9856a76e48f3f75ca7c22ee9022f4cf25c95`
- Container transport script SHA-256：`a2381a4f0c0b7e3b00af1fb363d6ffc1ba5216c801a6edd4c85a7d957cb1fb26`
- Container inspect script SHA-256：`055878798de565e798804cb3e0d382261b7ff90279f187a0117b81c412965728`

## 目的与范围

只确认 B100 异常后的当前现场事实，用于后续决定是否需要另行制定最小收尾包。目标固定为原 boot、CID、image/release、H、容器 BASE 与部署锁。host-snapshot 有界读取固定路径/目录的一层、固定文件摘要、owner/恢复记录的白名单字段、两个已观察 PID 的最小身份字段，以及固定 CID 的 Docker inspect。container-snapshot 先重验 boot/CID/image/state，仅在完全匹配且容器运行时才启动一次容器内 Python 只读检查 release marker、固定目录元数据和六个固定文件的摘要。

单步SSH每次最多30秒、stdout 32 KiB、stderr 4 KiB、连接尝试1次、自动重试0；Transport沿用固定 SHA `7db9878f247cc904178be0f5a4f59691b1cbd19465011b9c8c544dbb5dd03ad1` 的 bounded carrier。远端 Python `-I -B`。无需SQL/DB；不扫描全机进程，只核两个既有PID和精确绑定owner记录中的PID。不读cmdline、environment、exe、cwd、数据库、日志、Docker环境/挂载/labels；token文件只看路径属性，不读取内容或哈希。

## 顺序与 fail-closed 条件

1. ROOT取得新的独立执行批准后，才可运行 `host-snapshot`。
2. 只有 ROOT 确认 host 收据中的 boot、CID、image 与 owner范围精确绑定且字段合格，才可运行 `container-snapshot`；脚本还会再次核对身份。否则跳过容器内检查，记 `NOT_OBSERVED`。
3. 任一身份变化、软链接/路径异常、owner/token绑定不明、数据格式或输出上限异常、超时/非零结果，立即停止，不重试、不清理、不发信号、不释放锁。

本包明确不包括 `cleanup-container`、`cleanup-host`、`finish-owner`、`owner-stop`、backend recover、partial/precount abort，也不授权重跑 count。任何现场清理或锁动作必须在真实观测后另行形成精确包和确认。

## 本地检查

只对三份新脚本做 Python 3.12 AST 语法解析；没有 import/exec、测试、SSH 或运行远端命令。后续由原 R 审查固定 manifest/commands/脚本内容、信息最小化、命令有界性与停止条件。
