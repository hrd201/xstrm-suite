# Local ChangeLog

## 2026-03-29

### Fixes
- 修复管理页默认 `profile_root` 仍指向旧路径 `/root/emby2Alist/nginx` 的问题，改为当前项目 nginx 路径。
- 修复 `scripts/load_nginx_profile.py` 默认 `--root` 仍为旧路径的问题。
- 修复 `scripts/admin_api.py` 中返回/接收 `profile_root` 时仍使用旧默认值的问题。
- 修复 `scan_path` 任务在 `/emby-strm` 不存在或不可写时导致 HTTP 500 的问题（部署侧已创建并授权目录）。
- 修复 Emby 未挂载 `/emby-strm` 导致无法直接读取 STRM 目录的问题（部署侧已补挂载验证）。

### Improvements
- 为 AList 目录扫描增加温和节流：每个目录请求后随机延时 `1.5~3.5s`，每扫描 10 个目录额外停顿 `5~10s`。
- 为扫描过程增加目录级进度日志：输出当前目录、已扫目录计数、待扫目录数。

### Verified
- `strm_x.py --scan-path` 已可成功生成 `.strm`。
- Emby 容器已可读取 `/emby-strm` 中生成的 `.strm` 文件。
- 实测播放链路已确认走 302。
