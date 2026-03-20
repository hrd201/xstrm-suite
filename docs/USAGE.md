# xstrm-suite 使用说明

> 当前文档基于已经跑通的可用状态整理：
> - rclone 挂载媒体可正常 302
> - STRM 媒体可正常 302
> - Web 管理页可用
> - HTTP / HTTPS 可用
> - STRM 健康扫描可用

---

## 1. 项目作用

`xstrm-suite` 现在承担两件核心事情：

1. **独立生成 `.strm` 文件**
2. **通过 nginx + emby2alist 把播放请求重定向为 302 直链**

适用的两类媒体：

- **rclone/CD2 等挂载媒体**
- **`.strm` 文件媒体**

---

## 2. 当前目录职责

### 核心目录

- `config/`
  - 配置文件和模板
- `scripts/`
  - 安装、渲染、应用、扫描、健康检查脚本
- `nginx/`
  - nginx / emby2alist 主配置目录
- `web/admin/`
  - Web 管理页
- `data/`
  - 状态、日志、缓存、运行报告

### 当前关键文件

- `config/runtime.yaml`
  - 统一主配置源
- `config/strm-sync.yaml`
  - xstrm 实际运行配置
- `scripts/strm_x.py`
  - `.strm` 生成主脚本
- `scripts/render_runtime.py`
  - 从 runtime 渲染运行配置
- `scripts/apply_runtime.py`
  - 把 runtime 应用到 live nginx 配置
- `scripts/strm_health_check.py`
  - STRM 健康扫描脚本
- `scripts/admin_api.py`
  - 管理 API

---

## 3. 当前已确认可用的运行方式

### Web 管理入口

- HTTP:
  - `http://<你的域名或IP>:8091/admin/xstrm/`
- HTTPS:
  - `https://<你的域名或IP>:8095/admin/xstrm/`

### 管理 API

- `GET /api/admin/xstrm/status`
- `GET /api/admin/xstrm/logs/latest`
- `GET /api/admin/xstrm/settings`
- `POST /api/admin/xstrm/settings`
- `GET /api/admin/xstrm/sources`
- `POST /api/admin/xstrm/sources`
- `POST /api/admin/xstrm/scan`
- `POST /api/admin/xstrm/rebuild`
- `POST /api/admin/xstrm/scan-path`
- `POST /api/admin/xstrm/change-password`
- `GET /api/admin/xstrm/strm-health`

---

## 4. 当前环境中的实际关键配置

### HTTPS 证书

宿主机证书路径：

- `/path/to/fullchain.pem`
- `/path/to/privkey.pem`

容器内实际使用路径：

- `/etc/nginx/conf.d/cert/fullchain.pem`
- `/etc/nginx/conf.d/cert/privkey.pem`

### 当前端口

- HTTP 管理/服务入口：`8091`
- HTTPS 管理/服务入口：`8095`
- 本地管理 API：`127.0.0.1:18095`
- Emby：`YOUR_EMBY_HOST:8096`
- AList：`YOUR_ALIST_HOST:5388`

### profile_root

当前实际使用的 nginx profile 根目录：

- `/root/emby2Alist/nginx`

---

## 5. STRM 输出模式说明

系统支持三种输出模式：

- `auto`
- `logical_path`
- `local_path`

### logical_path
输出内容类似：

```text
/115/电影/xxx.mkv
```

### local_path
输出内容类似：

```text
/mnt/115/电影/xxx.mkv
```

### auto
自动根据 nginx profile 推导。

当前这套环境里，302 运行链路已经验证通过；管理页会显示：

- 当前读取到的 nginx profile
- 当前推导出的 `resolved_strm_mode`
- 预期生成示例

---

## 6. 日常使用方法

### 6.1 增量扫描

用途：扫描已有扫描源中的新增媒体并生成 `.strm`

管理页按钮：
- `扫描新增影片`

对应 API：

```bash
curl -X POST http://127.0.0.1:18095/api/admin/xstrm/scan
```

---

### 6.2 扫描指定目录

用途：只处理一个指定目录，适合单片补修、合集补扫、局部验证。

管理页输入示例：

```text
/115/电影/泰坦尼克号
```

或：

```text
/mnt/115/电影/泰坦尼克号
```

对应 API：

```bash
curl -X POST http://127.0.0.1:18095/api/admin/xstrm/scan-path \
  -H 'Content-Type: application/json' \
  -d '{"path":"/115/电影/泰坦尼克号"}'
```

---

### 6.3 全量重建

用途：删除旧 `.strm` 并重新生成。

⚠️ 注意：这是高影响操作，会重建全部 `.strm`。

管理页按钮：
- `全量重建`

对应 API：

```bash
curl -X POST http://127.0.0.1:18095/api/admin/xstrm/rebuild
```

---

### 6.4 STRM 健康检查

用途：检查 Emby 中的 STRM 条目是否健康。

检查内容：
- Emby 中 STRM 条目总数
- `.strm` 文件是否存在
- 播放入口是否能返回 302
- 失败明细

管理页按钮：
- `执行健康扫描`

对应 API：

```bash
curl http://127.0.0.1:18095/api/admin/xstrm/strm-health
```

也可以直接执行脚本：

```bash
python3 scripts/strm_health_check.py
```

报告输出位置：

```text
data/strm-health-report.json
```

---

## 7. 当前已经验证通过的链路

### rclone 挂载媒体
已验证：
- 可以正常命中 nginx / emby2alist
- 可以返回 302 直链

### STRM 媒体
已验证：
- Emby PlaybackInfo 可被改写为 `stream.strm`
- 真实播放请求可进入 `redirect2Pan`
- 最终可以返回 302 直链

已验证通过的样本包括：
- `27957` 城市猎人
- `27952` 泰坦尼克号
- `27955` Iron Man 3

---

## 8. 本轮排障中确认过的关键坑点

### 8.1 AList token 失效会导致“看起来不走 302”
症状：
- 日志出现：
  - `alist_path_api 401 token is invalidated`
- 然后会回退：
  - `fallback use original link`
  - `use original link`

结果：
- 客户端看起来像“不走 302”
- 实际是因为拿不到 AList 直链

### 8.2 route cache 会制造“假阴性”
如果之前失败过，nginx 内存里的 `routeL1Dict` 可能把条目缓存为：

```text
@root
```

这会导致：
- 后续即使配置修好了
- 该条目仍然继续回源

处理方法：
- 重启 `xstrm-nginx` 容器清空内存 route cache

### 8.3 STRM 文件缺失会导致单条目失效
有些条目不是配置坏，而是：
- Emby 里仍保留媒体项
- 但对应 `.strm` 文件实际已不存在

处理方法：
- 使用 `scan-path` 对单目录补扫
- 再重启 nginx 清坏缓存

### 8.4 runtime 模板不能覆盖成“阉割版 constant.js”
此前若 `constant.js.runtime` 只保留极少变量，会导致：
- `config.getEmbyHost` 丢失
- `redirectConfig` 丢失
- 最终播放链路 500

当前已修复为：
- runtime 模板保留原 emby2alist 聚合结构
- 只替换运行变量

### 8.5 runtime.yaml / strm-sync.yaml / live nginx 必须一致
如果三者漂移，会出现：
- nginx 正常但 xstrm 判断错误
- token 正确但扫描配置仍旧值
- profile_root 指向旧目录

所以后续修改配置后，应保持：
1. 改 `runtime.yaml`
2. `render_runtime.py`
3. `apply_runtime.py`
4. 必要时重启 nginx / admin API
5. 必要时重跑健康检查

---

## 9. 推荐操作顺序

### 修改配置后

```bash
python3 scripts/render_runtime.py
python3 scripts/apply_runtime.py
```

如果涉及 nginx / 302 行为：

```bash
docker restart xstrm-nginx
```

如果涉及管理 API：

```bash
systemctl restart xstrm-admin-api.service
```

如果怀疑 STRM 条目异常：

```bash
python3 scripts/strm_health_check.py
```

如果怀疑单目录 `.strm` 丢失：

```bash
python3 scripts/strm_x.py --scan-path '/115/电影/某目录'
```

---

## 10. 目前最推荐的排障顺序

当你感觉“某个片子不走 302”时，按这个顺序排：

1. 先看是不是 **单条目** 问题，不要先怀疑整套坏了
2. 执行 STRM 健康检查
3. 查 AList token 是否失效
4. 查对应 `.strm` 文件是否存在
5. 如果前面修过配置但结果没变，重启 `xstrm-nginx` 清 route cache
6. 再用真实客户端 UA 复测

---

## 11. 当前状态总结

当前项目已经达到：

- xstrm 可正常生成 `.strm`
- nginx / emby2alist 可正常工作
- HTTP / HTTPS 可用
- 管理页可用
- STRM 健康检查可用
- rclone 挂载链路可 302
- STRM 链路可 302

可视为：

**当前版本已经进入“可正常使用”状态。**
