# xstrm-suite

[English](README.md) | [中文](README.zh-CN.md)

面向网盘 Emby 媒体库的 Web 管理中心：从 AList/OpenList 生成本地 STRM、安排定时扫描、诊断跳转，并使用 Emby 自身接口修复电影识别。播放支持 MediaWarp 或原有 Nginx/njs/emby2Alist。

## 工作结构

```text
AList/OpenList 目录 → xstrm → 本地 STRM 和可选外挂字幕 → Emby
VidHub / Emby 客户端 → Nginx 网关 → 播放后端 → OpenList → 网盘 CDN
```

STRM 保留原逻辑网盘路径，播放时再由后端取链。识别修复通过 Emby API 更新元数据并保存绑定，不改网盘视频名称，不重写 STRM。

## 页面功能

| 页面 | 用途 |
| --- | --- |
| 概览 | 扫描状态、队列概况、最近日志 |
| 扫描任务 | 扫描媒体源或指定目录、浏览网盘、显式重建本地 STRM |
| 定时任务 | 每源间隔、每日或 Cron 计划，启停、立即运行、有限重试和历史 |
| 媒体识别 | 筛选未识别或信息不完整的电影 STRM，查看候选并确认 |
| 媒体源 | 保存远程目录和输出前缀 |
| 设置 | 连接、密钥、字幕同步、播放后端 |

保存媒体源不会触发扫描。保存播放设置不会自动重载网关，需要核对后用部署脚本应用。

## 扫描方式与限制

- **全部文件**：遍历所选目录树，生成缺失 STRM，跳过已有文件。首次导入已有网盘媒体库时使用。
- **最近新增或修改**：仍遍历目录树，只生成时间窗口内的媒体和字幕。结果为 0 表示范围内没有符合条件的项目，不代表目录没有电影。
- **队列式增量刷新**：保留的独立 CLI 工作流，按本地索引和请求预算调度候选目录。
- **字幕同步**：开启后下载受支持的外挂字幕到对应 STRM 目录。

请求间隔和写入串行化有助于减少压力，但不能保证避免网盘限流或风控。最近扫描仍读取旧目录，当前会刷新列表，大媒体库应合理安排频率。

## 环境要求与安装

需要 Linux、Bash、flock（util-linux）、OpenSSL、**Python 3.10+** 和 [requirements.txt](requirements.txt) 中的依赖。管理镜像使用 Python 3.13。容器部署需要 Docker Engine 与 Compose v2。管理服务和 Emby 必须以配置中的同一路径读取共享 STRM 目录。

推荐先按[独立 Docker 部署说明](deploy/README.md)准备管理、网关、Emby、OpenList 容器，再按需启用固定版本的 MediaWarp：

```bash
git clone https://github.com/hrd201/xstrm-suite.git
cd xstrm-suite
docker compose -f deploy/compose.test.yaml build admin
# 接着按 deploy/README.md 准备目录、设置独立密码并初始化网盘。
```

端口默认绑定 127.0.0.1。局域网访问设置 XSTRM_BIND_IP；外部 TLS 访问前先配置证书及 XSTRM_HTTPS_BIND_IP。实际连接、密钥、证书和数据库不进入 Git 或镜像构建上下文。

原生安装器维护旧的 Nginx/njs 部署，与独立 Docker 栈分开：

```bash
sudo bash scripts/install.sh
# scripts/bootstrap.sh 是同一安装器的兼容入口。
```

提前准备 Python 3.10+、venv 支持、rsync、Docker 和系统工具。安装/升级脚本将全部 Python 依赖装入安装目录的 .venv，systemd 和任务脚本使用此环境。单独安装 API 服务前必须先运行主安装器创建 xstrm 用户。使用网关前设置独立 Basic Auth 密码，仓库不提供可用的通用密码。

## 首次使用顺序

1. 初始化 Emby、OpenList 并授权网盘，在设置页保存连接。签名下载需要 OpenList 长期令牌，不能用临时登录 JWT 替代。
2. 保存一个小范围媒体源。逻辑 STRM 内容必须对应实际 OpenList 路径，使用相同的 scan_path 和 output_prefix 最容易核对。
3. 执行“全部文件”，将共享输出目录加入 Emby 电影或剧集库，启用相应元数据和图片提供器。
4. 应用后端，VidHub 连接网关地址，验证 302 播放。
5. 首次扫描确认后再创建计划。调度在管理服务内运行，无需额外的宿主机 Cron。
6. 在“媒体识别”点击“搜索影片及海报”，弹出候选窗口并自动搜索明确片名；年份或 ID 冲突先提示核对。检查片名、年份和海报后确认。

## 识别修复与健康检查

第一版支持配置输出目录内的电影 STRM。已有错误身份的条目可在“全部影片”中纠正。海报在候选弹窗展示，加载失败有重试入口；部分提供器不返回候选简介，界面会标记“暂无简介”。

确认后提交 Emby，回读 ID、标题、简介和海报。提交超时或图片替换未核对完成时不会误报完全成功。绑定按服务器、原 STRM 路径及内容指纹保存；重建后可复用同路径、同内容的绑定，重新搜索并确认恢复。原路径或内容变化时需要重新关联。

健康扫描检查文件和 HTTP(S) 跳转，不跟随 CDN 链接，不能证明一定能播放、拖动、切字幕或音轨，这些需要在 VidHub 中验收。

## 备份、升级与检查

备份配置、STRM、Emby 数据、data/scheduler.sqlite3、data/identity/ 和扫描状态/索引。识别记录包含原媒体路径和提供器响应，应私下保存；任务终结后会清除执行快照。

Docker 升级前核对活动任务，再重建 admin 镜像并仅重建该服务。播放切换用 deploy/apply_playback.sh mediawarp 或 emby2alist；旧后端回退需要已保存的旧网关和带 njs 的 Nginx。原服务器保留到客户端验收和并行观察期结束。

- [部署说明](deploy/README.md) / [Deployment](deploy/README.en.md)
- [定时任务](docs/SCHEDULER.md) / [Scheduling](docs/SCHEDULER.en.md)
- [识别修复](docs/IDENTITY.md) / [Identity repair](docs/IDENTITY.en.md)
- [更新日志](CHANGELOG.zh-CN.md) / [Changelog](CHANGELOG.md)

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
for script in scripts/*.sh deploy/*.sh bin/xstrm bin/xstrm-admin; do bash -n "$script"; done
node --check web/admin/identity.js
```

完整进程组和内核锁检查在 Linux 运行。CI 覆盖 Python 3.10、3.13。临时数据测试不能代替客户端验收。

## 致谢与许可

播放集成基于 [embyExternalUrl](https://github.com/bpking1/embyExternalUrl)。调度参考 [AutoFilm](https://github.com/AkimioJR/AutoFilm)，[MediaWarp](https://github.com/AkimioJR/MediaWarp) 是可选独立后端。参见 [LICENSE](LICENSE) 与各上游许可。
