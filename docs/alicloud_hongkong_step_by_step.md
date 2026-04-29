# 阿里云香港上云手把手指南（含低成本方案）

你现在可以选两条路：

1. 标准方案：`ECS + RDS + OSS`（更稳，成本更高）
2. 低成本方案：`ECS + 本机 PostgreSQL + OSS`（明显省钱，单点风险）

你刚刚确认要省成本，本指南优先按方案 2 写。

## 0. 资源准备（低成本）

必买：

- ECS（香港）
- OSS（香港）

可以暂不买：

- RDS PostgreSQL
- 正式域名（可先用公网 IP 验证上线）

## 1. 购买 ECS（香港）

建议规格：

- 起步：`2 vCPU / 4 GB`
- 稳妥：`4 vCPU / 8 GB`
- 系统盘：`40GB+`
- 系统：`Ubuntu 22.04 LTS`

安全组放行：

- `22`（SSH）
- `80`（HTTP）
- `443`（HTTPS）

官方参考：
- [Create an ECS instance on the custom buy page](https://www.alibabacloud.com/help/en/ecs/user-guide/create-an-instance-on-the-custom-buy-page)
- [Add security group rules](https://www.alibabacloud.com/help/en/ecs/user-guide/add-a-security-group-rule)

## 2. 购买 OSS（香港）

1. 创建 Bucket，地域选香港。  
2. 记录 Bucket 名称与 Endpoint。  
3. 开启版本控制（建议）。  

官方参考：
- [Create a bucket](https://www.alibabacloud.com/help/en/oss/developer-reference/create-buckets-2)
- [Regions and endpoints](https://www.alibabacloud.com/help/en/oss/user-guide/regions-and-endpoints)

## 3. 域名解析

把域名 `A` 记录指向 ECS 公网 IP。  

官方参考：
- [Add an A record](https://www.alibabacloud.com/help/en/dns/add-an-a-record)

## 4. ECS 初始化

SSH 登录后执行：

```bash
sudo apt update
sudo apt install -y git docker.io docker-compose
sudo usermod -aG docker $USER
newgrp docker
```

拉代码：

```bash
sudo mkdir -p /opt/umanewsbot
sudo chown -R $USER:$USER /opt/umanewsbot
cd /opt/umanewsbot
git clone <your_repo_url> .
```

## 5. 配置环境变量

```bash
cp .env.example .env
```

低成本模式必填：

- `SECRET_KEY`
- `ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS`
- `SITE_URL`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `MEDIA_STORAGE_BACKEND=oss`
- `OSS_ACCESS_KEY_ID`
- `OSS_ACCESS_KEY_SECRET`
- `OSS_BUCKET_NAME`
- `OSS_ENDPOINT`
- `OSS_PUBLIC_BASE_URL`
- 翻译 API Key（`SILICONFLOW_API_KEY` 或 `OPENAI_API_KEY`）
- OneBot 配置（如果要推送）

## 6. 放证书并启动

证书路径：

- `deploy/certs/fullchain.pem`
- `deploy/certs/privkey.pem`

如果还没有正式域名，可以先给公网 IP 生成临时自签证书，再走低成本部署验证后台、翻译与 OSS。

启动（低成本）：

```bash
chmod +x deploy_lowcost.sh deploy/*.sh deploy/docker/*.sh
./deploy_lowcost.sh
```

## 7. 验证

1. `https://your-domain/healthz/`
2. `https://your-domain/admin/login/`
3. `https://your-domain/`
4. 发布一篇并检查前台
5. 触发一次抓取和翻译任务

日志查看：

```bash
./deploy/docker/compose-wrapper.sh -f docker-compose.prod.lowcost.yml logs -f web
./deploy/docker/compose-wrapper.sh -f docker-compose.prod.lowcost.yml logs -f worker
./deploy/docker/compose-wrapper.sh -f docker-compose.prod.lowcost.yml logs -f beat
```

## 8. 低成本模式必做运维

每日备份并上传 OSS：

```bash
BACKUP_TARGET=oss ./deploy/backup_db.sh
```

建议配 cron（每天凌晨 3 点）：

```bash
0 3 * * * cd /opt/umanewsbot && BACKUP_TARGET=oss ./deploy/backup_db.sh >> /var/log/umanewsbot_backup.log 2>&1
```

## 9. 将来升级到 RDS（平滑迁移）

当流量上来时：

1. 新购 RDS PostgreSQL
2. 从当前本机 PostgreSQL 导出并导入 RDS
3. 修改 `.env` 的 `POSTGRES_HOST` 指向 RDS
4. 运行标准部署：`./deploy.sh`

代码层已经支持，不需要改业务逻辑。
