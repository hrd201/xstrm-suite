# Runtime Config Design

## 目标

统一收口以下配置来源：
- nginx / emby2alist 配置
- xstrm 配置
- 安装脚本交互输入

统一主配置文件：
- `config/runtime.yaml`

---

## 当前策略

第一阶段先建立统一主配置文件，不立即全面替换现有 nginx/conf.d 配置逻辑。

也就是说当前是：
- `runtime.yaml` 作为未来唯一真源
- `config/strm-sync.yaml` 作为 xstrm 当前运行配置
- `nginx/` 目录作为 vendored nginx/emby2alist 配置语义目录

---

## 后续演进方向

1. bootstrap/install 过程收集必填项
2. 写入 `config/runtime.yaml`
3. 由模板渲染：
   - `nginx/conf.d/constant.js.runtime`
   - `nginx/conf.d/config/constant-mount.runtime.js`
   - `nginx/nginx.runtime.conf`
   - `config/strm-sync.yaml`
4. xstrm 与 nginx/emby2alist 均从同一份 runtime 配置派生

## 当前已完成

已新增：
- `scripts/configure_runtime.py`
- `scripts/render_runtime.py`
- `config/templates/constant.js.template`
- `config/templates/constant-mount.js.template`
- `config/templates/strm-sync.yaml.template`
- `config/templates/nginx.conf.patch.template`

当前已可实现：
- 安装时交互填写 `runtime.yaml`
- 再从 `runtime.yaml` 渲染出：
  - xstrm 当前运行配置
  - nginx/emby2alist 关键运行时片段
- 再通过 `scripts/apply_runtime.py` 把关键运行时片段应用到实际启用文件：
  - `nginx/conf.d/constant.js`
  - `nginx/conf.d/config/constant-mount.js`
  - `nginx/nginx.conf`（当前先以保守 patch 注入 runtime 元信息）

---

## 当前必填项（建议）

- Emby host
- Emby api key
- AList scheme / host / port
- AList token
- nginx http port
- 是否启用 https
- 若启用 https：ssl cert / ssl key

---

## 当前目录语义

- `nginx/`：整合后的 nginx / emby2alist 配置目录（主方案由 Docker 挂载使用）
- `xstrm`（当前仍由 `scripts/strm_x.py` 承担）
- `config/runtime.yaml`：统一主配置文件

---

## 注意

当前还未完全切掉旧的 `emby2alist/` 目录引用；后续需要逐步切换脚本和文档到 `nginx/` 目录。先建立新语义，再完成迁移。
