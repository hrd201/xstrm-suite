# 更新日志

本文件记录此项目的所有重要变更。

## [0.2.1]2026-04-26

### Added
- **字幕同步功能**：新增 `src/subtitle_syncer.py` 模块，扫描时可自动从 AList 下载字幕文件（`.srt`, `.ass` 等）到服务器本地对应的 `.strm` 目录。
- **Web 界面目录浏览排序优化**：管理后台 AList 目录浏览现已支持按修改时间降序排列（新文件夹排在最前），并在界面显示修改时间戳。
- **配置项扩展**：在 `strm-sync.yaml` 中新增 `scan.subtitle_sync` 和 `scan.subtitle_exts` 配置。
- **扩展媒体格式支持**：扫描白名单新增更多视频与音频扩展名
  - 视频：`.mov`、`.wmv`、`.flv`、`.webm`、`.m4v`、`.mpg`、`.mpeg`、`.rmvb`、`.iso`
  - 音频：`.mp3`、`.m4a`、`.flac`、`.aac`、`.ape`、`.wav`、`.ogg`、`.opus`、`.wma`、`.alac`、`.aiff`、`.aif`、`.amr`
- **配置模板同步扩展**：`config/templates/strm-sync.yaml.template` 现在也包含上述扩展名，避免新部署遗漏。

### Fixed
- **字幕下载 403 错误**：将下载方式改为 AList 代理接口 (`/d/<path>`)，解决直接请求 115 等云盘直链时因缺少 Cookie 导致的 403 问题。
- **字幕下载 URL 编码问题**：修复了路径中包含空格或特殊字符时下载失败的问题。
- **扫描器扩展名读取逻辑**：`src/scanner.py` 现在优先读取 `scan.include_ext` 配置，而不是仅依赖内置常量。
- **音乐目录扫描问题**：修复了配置已添加扩展名但扫描器未实际生效的问题，使 `/mnt/115/音乐` 这类目录可以正确识别音频文件。

## [0.2.0] - 2026-03-16

### Added
- **AList 目录浏览器**：管理后台现在支持直接浏览 AList 目录
  - 新增 API：`GET /api/admin/xstrm/alist/list?path=/`
  - 前端支持面包屑导航
  - 支持点击选择扫描路径
- **扫描模式重构**：从本地挂载扫描改为 AList API 扫描
  - 通过 `src/alist_client.py` 直连 AList API
  - 通过 AList API 递归遍历目录
- **路径映射**：自动把 AList 挂载路径映射为逻辑 STRM 前缀
  - 例如：`/mnt/115/电影` → `/115/电影`
- **模块化架构**：核心逻辑抽离到 `src/` 包
  - `src/config.py`：配置加载与推断
  - `src/state.py`：状态管理
  - `src/alist_client.py`：AList API 客户端
  - `src/scanner.py`：核心扫描逻辑
  - `src/generator.py`：STRM 文件生成
  - `cmd/cli.py`：CLI 入口

### Fixed
- **管理 API 路由**：修复访问 `/api/admin/xstrm/*` 时的 404 问题
  - 将 `backend_port` 从 8095 修正为 18095
  - 正确路由 `/admin/xstrm/` 和 `/api/admin/xstrm/*` 到内部 API
- **空文件同步问题**：修复 `strm_x.py` 被同步成空文件的情况
- **陈旧状态清理**：新增对缺失 STRM 文件的状态自动清理
- **任务锁清理**：修复因过期锁文件导致扫描任务卡住的问题

### Changed
- **扫描源配置**：从基于挂载路径改为基于 AList 路径
  - 现在使用 `scan_mode: alist`，而不是本地文件系统扫描
  - sources 使用 `/mnt/115/电影` 这类 AList 路径，而不是逻辑路径
- **Token 管理**：更新 AList token 处理逻辑

### Dependencies
- 兼容 AList v3+

---

## [0.1.0] - 2026-03-11

### Added
- `xstrm-suite` 项目初始版本
- `xstrm` / `xstrm-admin` 命令入口
- 与 `emby2alist` 的源配置集成
- 镜像模式 STRM 文件生成
- 从已发现源中选择目录
- 指定目录扫描
- STRM 文件去重
- 基于 Docker 的 nginx/emby2alist 控制脚本
- 运行时配置与模板渲染
- HTTP/HTTPS 支持与证书路径配置
- bootstrap/安装脚本
- 升级与修复脚本

### Features
- 基于配置驱动的运行时生成
- 通过 bootstrap.sh 进行交互式初始化
- nginx 测试与重载工具
- Docker Compose 集成
- 基于 profile 的 nginx 配置
