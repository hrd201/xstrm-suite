# PRIVATE REPO ACTIONS

## 建私有仓库前建议动作

### 1. 确认提交范围
- 保留：
  - `bin/`
  - `scripts/`
  - `config/`
  - `nginx/`
  - `docs/`
  - `README.md`
  - `CHANGELOG.md`
  - `LICENSE`
- 检查是否要继续保留：
  - `emby2alist/`（迁移期目录）

### 2. 确认运行期文件策略
- `constant.js.runtime` 这类文件是否保留在私有仓库：
  - 当前可保留，方便调试
  - 公开前可再决定是否清理
- `sites-enabled/` 当前属于渲染输出目录：
  - 私有仓库阶段可以保留
  - 公开前建议再确认

### 3. README 待补说明
- 项目用途
- 典型部署拓扑图
- HTTP / HTTPS 两种使用方式
- Docker 运行方式
- 与现有 AList / Emby 的关系

### 4. 建库策略
- 当前建议：先建 **私有仓库**
- 等实际部署完全成功、README 补全后，再决定是否公开

### 5. 当前建议不做
- 立即公开发布
- 删除所有迁移期内容
- 过早追求最终目录洁癖
