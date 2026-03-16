# xstrm-suite

[English](./README.md) | [中文](./README.zh-CN.md)

STRM 文件管理系统，用于 Emby + AList 集成。自动生成 `.strm` 文件指向 AList 托管的媒体文件，使 Emby 能够直接从 AList 存储播放媒体。

## 功能特性

- **AList 集成**：直接集成 AList 进行媒体扫描
- **自动 STRM 生成**：自动为媒体库生成 `.strm` 文件
- **管理后台**：浏览 AList 目录并从网页界面触发扫描
- **增量同步**：仅生成缺失的 STRM 文件，跳过已存在的
- **状态管理**：跟踪已生成的文件以避免重复
- **灵活扫描**：扫描所有来源或指定单独目录
- **HTTPS 支持**：支持 Let's Encrypt 或自定义证书的完整 HTTPS 配置

## 架构

```
xstrm-suite/
├── src/                      # 核心运行时代码
│   ├── config.py             # 配置加载
│   ├── state.py              # 状态管理
│   ├── alist_client.py       # AList API 客户端
│   ├── scanner.py            # 媒体扫描逻辑
│   └── generator.py          # STRM 文件生成
├── cmd/                      # CLI 命令行入口
├── scripts/                  # 安装和运维脚本
├── config/                   # 配置模板
├── nginx/                    # Nginx 配置
├── web/admin/                # 管理后台网页
└── data/                    # 运行时数据（状态、日志）
```

## 环境要求

- **Python 3.8+**
- **PyYAML**
- **Docker & Docker Compose**
- **AList v3+**（外部或自托管）
- **Emby Server**（用于媒体播放）

## 安装

### 快速开始

```bash
# 克隆仓库
git clone https://github.com/hrd201/xstrm-suite.git
cd xstrm-suite

# 运行一键安装
cd scripts
sudo ./install.sh
```

安装脚本会交互式提示以下内容：
- Emby 服务器地址和 API Key
- AList 安装方式（Docker/本机/自定义）
- AList 协议、主机、端口、Token 和公网地址
- Nginx 端口和 HTTPS 配置
- 媒体挂载根路径
- STRM 输出目录
- 扫描源列表

### 手动安装

如需手动安装：

#### 1. 安装依赖

```bash
# 安装 Python 依赖
pip3 install pyyaml

# 安装 Docker（如未安装）
curl -fsSL https://get.docker.com | sh
systemctl enable docker
systemctl start docker

# 安装 Docker Compose
pip3 install docker-compose
```

#### 2. 配置 AList

确保 AList 服务器正常运行，并准备好：
- AList 基础 URL（如 `http://YOUR_ALIST_HOST:5388`）
- Admin Token

#### 3. 创建配置

```bash
# 复制配置模板
cp config/strm-sync.yaml.example config/strm-sync.yaml

# 编辑配置
vim config/strm-sync.yaml
```

必要配置示例：

```yaml
output_root: /emby-strm
mode: mirror
alist:
  base_url: http://YOUR_ALIST_IP:5388
  token: YOUR_ALIST_TOKEN
  public_url: https://your-domain.com:5388
scan:
  default_depth: 1
  incremental_only: true
  include_ext:
    - .mp4
    - .mkv
    - .avi
    - .ts
    - .m2ts
sources:
  - path: /115/电影
    library_type: movie
    watch_depth: 1
    output_prefix: /115/电影
    scan_path: /mnt/115/电影
  - path: /115/剧集
    library_type: series
    watch_depth: 1
    output_prefix: /115/剧集
    scan_path: /mnt/115/剧集
```

#### 4. 渲染并应用配置

```bash
# 渲染运行时配置
python3 scripts/render_runtime.py

# 应用配置
python3 scripts/apply_runtime.py
```

#### 5. 启动服务

```bash
# 通过 Docker 启动 nginx 和 emby2alist
docker-compose up -d

# 启动管理 API
systemctl enable xstrm-admin-api
systemctl start xstrm-admin-api
```

### Docker 安装

运行整个系统最简单的方式：

```bash
# 使用 docker-compose
docker-compose up -d
```

## 使用方法

### 命令行界面

```bash
# 运行 xstrm CLI
xstrm

# 或直接运行
/opt/xstrm-suite/bin/xstrm
```

选项：
- `1` - 从已配置的 AList 目录扫描
- `2` - 扫描指定的 AList 目录
- `3` - 查看集成配置
- `4` - 配置定时任务
- `5` - 查看当前配置
- `6` - 查看状态文件
- `0` - 退出

### 管理后台

访问管理后台：`http://YOUR_SERVER:8095/admin/xstrm/`

功能：
- 查看扫描状态和日志
- 浏览 AList 目录
- 触发指定目录扫描
- 查看配置

### API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/admin/xstrm/status` | GET | 获取扫描状态 |
| `/api/admin/xstrm/sources` | GET | 列出配置的来源 |
| `/api/admin/xstrm/scan-path` | POST | 扫描指定路径 |
| `/api/admin/xstrm/scan-all` | POST | 扫描所有来源 |
| `/api/admin/xstrm/alist/list` | GET | 浏览 AList 目录 |
| `/api/admin/xstrm/logs` | GET | 获取扫描日志 |

## 扫描工作流程

### 工作原理

1. **配置**：在 `config/strm-sync.yaml` 中定义媒体来源
2. **AList 扫描**：扫描器连接 AList API 并递归遍历目录
3. **路径映射**：AList 挂载路径（如 `/mnt/115/电影`）映射为逻辑路径（如 `/115/电影`）
4. **STRM 生成**：对每个找到的媒体文件，在输出目录创建 `.strm` 文件
5. **状态跟踪**：在状态中跟踪已生成的文件以避免重复

### 路径映射示例

```
AList 路径:    /mnt/115/电影/角斗士2 Gladiator II/GladiatorII.mkv
               ↓ (路径映射)
逻辑路径:      /115/电影/角斗士2 Gladiator II/GladiatorII.mkv
               ↓ (STRM 生成)
STRM 文件:     /emby-strm/115/电影/角斗士2 Gladiator II/GladiatorII.strm
               ↓ (内容)
STRM 内容:     /115/电影/角斗士2 Gladiator II/GladiatorII.mkv
```

### 增量模式

默认启用增量模式：
- 跳过已存在的 STRM 文件
- 仅新媒体文件触发 STRM 生成
- 自动重新生成缺失的 STRM 文件

禁用增量模式：

```yaml
scan:
  incremental_only: false
```

## 故障排查

### 检查服务状态

```bash
# 检查 xstrm-admin API
systemctl status xstrm-admin-api

# 检查 Docker 容器
docker-compose ps

# 检查 nginx
nginx -t
```

### 查看日志

```bash
# 管理 API 日志
journalctl -u xstrm-admin-api -f

# 扫描日志
tail -f /opt/xstrm-suite/data/tasks/logs/scan_path-*.log
```

### 常见问题

1. **Token 无效**：在 `config/strm-sync.yaml` 中更新您的 AList token
2. **路径未找到**：确保 AList 存储路径与配置匹配
3. **权限拒绝**：确保输出目录可写

## 开发

### 项目结构

```
src/
├── config.py       # 配置加载和推断
├── state.py        # 状态文件管理
├── alist_client.py # AList API 客户端
├── scanner.py      # 媒体扫描逻辑
└── generator.py   # STRM 文件生成
```

### 运行测试

```bash
# 测试扫描
python3 -m cmd.cli --scan-path "/mnt/115/电影"

# 查看配置
python3 -m cmd.cli --config
```

## 更新日志

详细更新日志请参阅 [CHANGELOG.md](CHANGELOG.md)

## 许可证

MIT License

## 支持

如有问题，请在 GitHub 上提交 Issue。
