# xstrm-suite

独立项目骨架，包含：

## 正式目录
- `nginx/`：整合后的 nginx / emby2alist 配置语义目录（默认由 Docker 挂载使用）
- `bin/`：`xstrm` / `xstrm-admin` 命令入口
- `scripts/`：安装、升级、修复、渲染、应用、Docker 控制脚本
- `config/`：统一主配置、运行配置、模板
- `data/`：状态、日志、缓存等运行数据
- `docs/`：部署、切换、设计、发布清单等文档

## 迁移期保留目录
- `emby2alist/`：旧目录（仅作迁移期参考，后续逐步淡出）

## 运行期生成物
以下内容属于运行/渲染阶段产物：
- `nginx/conf.d/*.runtime*`
- `nginx/sites-enabled/*`
- `data/` 下的状态、日志、缓存

## 安装

### 基础安装
```bash
cd scripts
sudo ./install.sh
```

### 一键部署（推荐）
```bash
cd scripts
sudo ./bootstrap.sh
```

当前 bootstrap 会在安装过程中执行：
- 依赖检查
- Docker / Docker Compose 检查
- 交互式配置采集
- runtime 校验
- 端口冲突检查
- runtime 渲染与应用
- nginx 配置测试

运行过程中会交互式填写：
- Emby 地址 / API Key
- AList 安装方式（Docker / 本机 / 自定义）
- AList 协议 / 主机 / 端口 / Token / 公网地址
- nginx 端口 / HTTPS 开关 / 证书路径
- 媒体挂载根路径
- xstrm 输出目录与扫描源列表

说明：
- 如果选择 HTTP-only，则不会要求 SSL 证书/私钥
- 只有启用 HTTPS 时，才会强制校验证书路径

安装后运行：

```bash
xstrm
```

管理入口：

```bash
xstrm-admin
```

支持：
- 安装 / 升级 / 修复 / 卸载
- nginx test / reload
- Docker up / down / status
- 重新渲染并应用配置
- 查看 HTTP / HTTPS 切换说明

也可以直接运行安装目录里的命令：

```bash
/opt/xstrm-suite/bin/xstrm
/opt/xstrm-suite/bin/xstrm-admin
```

## 默认主方案

- `xstrm / xstrm-admin`：本机安装
- `nginx + emby2alist`：Docker 运行
- `AList / Emby`：外部依赖接入

## 当前能力

- 读取 emby2alist 配置实现同源整合
- 镜像型 `.strm` 生成
- 从已发现目录中选择扫描（默认两层）
- 扫描指定目录（适合三层以上复杂目录）
- 已存在 `.strm` 文件去重
- 检查 python3 / PyYAML
- 安装 `xstrm` / `xstrm-admin` 命令入口
- 提供 Docker 方式运行 nginx/emby2alist 的控制脚本
- `runtime.yaml` 会驱动生成 HTTP / HTTPS 两种 Docker 运行配置

## 说明

- 菜单 1：只列出两层目录（如 `/115/电影`），不显示 `/mnt`
- 菜单 2：处理更深层目录，例如合集、复杂目录
- 当前 bootstrap 已能完成第一版部署，但 nginx 生产启用、emby2alist service 化、定时任务等还会继续补强
