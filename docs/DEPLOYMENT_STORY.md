# 从 0 到可用：xstrm-suite 部署故事版说明

这份文档不是严格的参数手册，而是按真实使用顺序，讲清楚如何把 `xstrm-suite` 从空目录逐步带到可用状态。

---

## 第一步：理解这套方案到底安装什么

先记住一句话：

## 默认主方案
- `xstrm / xstrm-admin`：本机安装
- `nginx + emby2alist`：Docker 运行
- `AList / Emby`：作为外部依赖接入

这意味着：

- 你不需要让本项目替你安装 Emby
- 你不需要让本项目替你安装 AList
- 本项目主要负责：
  - `.strm` 生成
  - nginx/emby2alist 配置管理
  - Docker 运行入口

---

## 第二步：准备现有环境

在开始前，最好已经具备：

- 一个可用的 Emby
- 一个可用的 AList
- 已知的 AList Token
- 已知的 Emby API Key
- 已挂载好的媒体目录（如果走当前推荐链路）

如果你想后续启用 HTTPS，还需要：
- 域名
- 证书
- 私钥

如果你只是先打通链路，可以先走 HTTP。

---

## 第三步：执行安装

进入项目目录后，运行：

```bash
cd scripts
sudo ./bootstrap.sh
```

安装过程中，系统会做几类事情：

### 1. 环境检查
- python3
- PyYAML
- Docker
- Docker Compose

### 2. 收集运行配置
会交互式询问：
- Emby 地址 / API Key
- AList 安装方式（Docker / 本机 / 自定义）
- AList 协议 / 主机 / 端口 / Token / 公网地址
- nginx 端口 / HTTPS 开关 / 证书路径
- 媒体挂载根路径
- STRM 输出目录与扫描源列表

### 3. 做配置校验
- 校验运行配置是否合理
- 如果启用 HTTPS，则强制检查证书与私钥路径
- 检查端口配置是否冲突

### 4. 生成运行配置
- `runtime.yaml`
- `strm-sync.yaml`
- nginx 运行配置
- Docker compose

### 5. 应用配置并安装入口
- 安装 `xstrm`
- 安装 `xstrm-admin`

---

## 第四步：第一次运行时最常用的两个命令

### 1. 业务入口
```bash
xstrm
```

### 2. 管理入口
```bash
xstrm-admin
```

你可以把它理解成：

- `xstrm`：生成和扫描 `.strm`
- `xstrm-admin`：安装、升级、修复、Docker 管理、配置重渲染

---

## 第五步：如何生成 `.strm`

### 日常最常见方式
进入：

```bash
xstrm
```

然后：

### 方式 A：从已发现目录中选择扫描
适合两层目录，例如：
- `/115/电影`
- `/115/剧集`
- `/115/动画`

### 方式 B：扫描指定目录
适合更深层目录，例如：
- 合集目录
- 多层复杂目录
- 单个片名目录

---

## 第六步：如何启动 nginx/emby2alist 容器

默认主方案下，nginx/emby2alist 是跑在 Docker 里的。

可以通过：

```bash
xstrm-admin
```

使用：
- Docker 启动
- Docker 停止
- Docker 查看状态

或直接用脚本：

```bash
scripts/docker_ctl.sh up
scripts/docker_ctl.sh down
scripts/docker_ctl.sh status
```

---

## 第七步：如果一开始是 HTTP，后来想切 HTTPS

这是项目里专门考虑过的场景。

### 结论
不需要重装 nginx，不需要重装 Docker。

你只需要：
1. 修改 `runtime.yaml`
2. 启用 `https_enabled`
3. 填证书和私钥路径
4. 重新渲染并应用配置
5. 重启 Docker 容器

也就是：

### 这是配置切换，不是重装

---

## 第八步：如果以后要维护

后续你常用的维护动作主要会集中在：

### 1. 更新配置
- 改 `runtime.yaml`

### 2. 重新渲染并应用
可以通过 `xstrm-admin` 完成。

### 3. 检查 nginx
- test
- reload

### 4. 升级项目
- `upgrade.sh`

### 5. 修复安装
- `repair.sh`

---

## 第九步：当前适合什么阶段

目前这套项目最适合：

- 先进入私有仓库
- 继续补 README 和使用说明
- 再做更多真实环境验证
- 最后再决定是否公开

---

## 一句话总结

`xstrm-suite` 当前已经不是“一个脚本”，而是一套围绕 `.strm` 生成、nginx/emby2alist 配置、Docker 运行、以及 AList/Emby 接入的完整部署思路。
