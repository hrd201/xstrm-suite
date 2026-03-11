# PROJECT LAYOUT

## 正式目录

### `bin/`
对外命令入口：
- `xstrm`
- `xstrm-admin`

### `scripts/`
安装、升级、修复、渲染、应用、Docker 控制等脚本。

### `config/`
统一配置与模板：
- `runtime.yaml`：统一主配置
- `strm-sync.yaml`：xstrm 当前运行配置（由 runtime 派生）
- `templates/`：渲染模板

### `nginx/`
正式主目录，供 Docker 方式挂载使用：
- `nginx.conf`
- `conf.d/`
- `sites-enabled/`

说明：
- `sites-enabled/` 当前属于渲染输出目录
- `conf.d/*.runtime*` 当前属于运行期派生文件

### `data/`
状态、日志、缓存等运行时目录。

### `docs/`
部署、切换、设计、发布清单等文档。

---

## 迁移期保留目录

### `emby2alist/`
迁移期保留，仅用于参考和对照。

目标方向：
- 逐步淡出对 `emby2alist/` 目录的依赖
- 以 `nginx/` 作为正式目录语义

---

## 当前默认主方案

- `xstrm / xstrm-admin`：本机安装
- `nginx + emby2alist`：Docker 运行
- `AList / Emby`：外部依赖接入
