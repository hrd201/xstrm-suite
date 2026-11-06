# 独立 Docker 部署

[中文](README.md) | [English](README.en.md)

此栈包含 admin、Nginx/njs 网关、Emby、OpenList，以及按需启用的 MediaWarp。与已有服务器使用不同目录、数据卷和端口；不自动导入旧配置，不自动迁移网盘授权。

## 从头准备

需要 Docker Engine、Compose v2、OpenSSL，以及运行 htpasswd 的工具（例如 Debian/Ubuntu 的 apache2-utils）。在 Linux 源码目录执行：

```bash
docker compose -f deploy/compose.test.yaml build admin
docker run --rm -v "$PWD:/bootstrap" xstrm-test-admin python /bootstrap/deploy/prepare_test.py
sudo chown 1001:1001 deploy/test-openlist
htpasswd -cB deploy/test-nginx/conf.d/.htpasswd-xstrm-admin admin
chmod 644 deploy/test-nginx/conf.d/.htpasswd-xstrm-admin
docker compose -f deploy/compose.test.yaml up -d
```

prepare_test.py 会拒绝覆盖已有测试目录。管理密码由你交互设置，仓库不包含可用的密码文件。网关 worker 需要读取加盐哈希；不要公开它。

默认绑定 127.0.0.1，入口为：

| 服务 | 地址 |
| --- | --- |
| 管理中心 | http://127.0.0.1:18091/admin/xstrm/ |
| 网关 / VidHub | http://127.0.0.1:18091 |
| Emby 初始化 | http://127.0.0.1:18096 |
| OpenList 初始化 | http://127.0.0.1:15244 |

局域网部署在项目根目录的私有 .env 中设置 XSTRM_BIND_IP 为实际 LAN IP，然后重建端口受影响的服务。XSTRM_DNS_SERVER 默认 1.1.1.1，可改为该主机实际可达的可信 DNS。检查当前端口占用，勿与原服务混用。

## 初始化与小范围验证

1. 分别完成 Emby、OpenList 向导和网盘授权，创建 Emby API Key。
2. 在设置页保存内部地址 http://emby:8096、http://openlist:5244、Emby Key 和 OpenList 长期令牌。public_url 使用客户端可访问的下载入口。
3. 添加小范围源，scan_path 和 output_prefix 直接使用实际 OpenList 路径，例如 /mnt/cloud/movies。先执行“全部文件”建立基线，再使用最近扫描或定时计划。
4. Emby 中添加 /emby-strm 电影或剧集库，并配置元数据/图片提供器。管理服务与 Emby 均已挂载 deploy/test-media。
5. 管理账号与 Emby 用户不同。VidHub 使用 Emby 用户连接网关，而非直接连接 18096。

通过 API 建库时不能假定 Emby 自动启用默认提供器。可先核对库设置，再在 admin 内运行 python deploy/configure_emby_metadata.py --library YOUR_LIBRARY --tmdb-only；该脚本备份原设置，显式指定 --tmdb-only 才覆盖提供器选择。

## MediaWarp 与回退

默认准备的是旧 njs 网关。保存有效连接后执行：

```bash
bash deploy/apply_playback.sh mediawarp
# 回退需要已经保存的旧网关：
bash deploy/apply_playback.sh emby2alist
```

应用脚本生成私有配置，启动固定版本 akimio/mediawarp:v0.2.5，检查就绪状态和 nginx -t，通过后重载；失败恢复原文件。Web 只保存选项，不直接应用配置。切换不会重建 Emby、OpenList 或 STRM。

MediaWarp 的 9000 端口只在容器网络可见。边缘网关验证播放客户端凭据后才允许跳转。逻辑 STRM 继续保存原网盘路径；OpenList /d/ 签名下载地址再跳转 CDN。无原视频挂载时不能保证回源或转码。字幕同步由 xstrm 处理。

网关访问日志不记录下载查询参数；可能包含签名链接的 MediaWarp 日志关闭。运行配置、回退快照和密钥保存在私有 test-* 目录，不进入 Git 或构建上下文。

## HTTPS 和网络

自行准备指向主机的域名和有效证书，将私钥和证书链分别放入 deploy/test-nginx/cert/privatekey.pem、fullchain.pem，再把 deploy/https-test.conf 的配置安装到 test-nginx/conf.d/includes/https.conf。安装 deploy/download-test.conf 到对应自定义 location 目录时，需要确认它的 OpenList 地址和下载签名配置。

把 OpenList public_url 改为实际 HTTPS 网关地址；设置 XSTRM_HTTPS_BIND_IP 后才在需要的网卡发布 18443。默认 TLS 端口只绑定回环地址。公网使用前核对路由器端口转发、防火墙、证书校验和管理鉴权。执行 nginx -t 后再重载；部署者自行配置续期。

deploy/test_firewall.sh、dns_relay.py、xstrm-test-dns.service 和 Mihomo 示例是实验环境网络辅助，不能直接套用其他主机。DNS 中继默认网桥 172.18.0.1/16、上游 127.0.0.1:1053；须先按实际网桥修改和核对再启用。不要为普通部署无条件开启 TUN 或修改系统 DNS。

## 扫描、识别与检查

定时任务在 admin 内运行，计划存于 config/strm-sync.yaml，队列/历史存于 data/scheduler.sqlite3；手动任务与定时任务共用写入队列和内核锁。

媒体识别通过 Emby 候选搜索/应用接口工作，无需额外插件或 TMDB 密钥。点击“搜索影片及海报”打开候选弹窗，确认后才更新元数据。私有绑定保存在 data/identity/，需一并备份。详见 [识别说明](../docs/IDENTITY.md) 与 [定时任务](../docs/SCHEDULER.md)。

健康扫描只检查本地 STRM 和播放入口的 HTTP(S) 跳转，不下载视频。真实字节读取、拖动、字幕、音轨、续播仍需单独在 VidHub 验收。

## 升级

核对活动任务并备份私有配置、STRM、Emby 数据、扫描索引、scheduler.sqlite3 和 identity/。然后：

```bash
docker compose -f deploy/compose.test.yaml build admin
docker compose -f deploy/compose.test.yaml up -d --no-deps admin
docker compose -f deploy/compose.test.yaml exec -T gateway nginx -t
```

离线构建时把 requirements.txt 及其依赖的匹配 wheel 放入 deploy/wheels，使用 build --build-arg PIP_NO_INDEX=1 admin。仓库只保留目录占位文件，不包含平台相关 wheel。

不要在此容器栈上运行原生 upgrade.sh 来覆盖宿主机服务。原服务器保留到至少一个完整日常观察周期和真实客户端验收完成，再单独安排迁移和回退。
