# xstrm + alist 恢复说明

## 当前已验证结构

- `alist`：Docker bridge 网络，宿主机仅绑定 `127.0.0.1:5244`
- `xstrm-nginx`：Docker host 网络
- `xstrm` 内部 API 调用地址：`alistAddr = http://127.0.0.1:5244`
- `xstrm` 当前兼容恢复方案：`alistPublicAddr` 跟随当前 `alist` 容器 IP（如 `http://172.17.0.3:5244`）

## 常见故障

### 1. 5244 被外网直接访问
根因通常不是宝塔防火墙，而是 `alist` 容器被发布成：

```text
0.0.0.0:5244->5244/tcp
```

正确目标应为：

```text
127.0.0.1:5244->5244/tcp
```

### 2. xstrm 的 302 / 直链失效
高概率是 `alist` 容器 IP 变化后，`alistPublicAddr` 没同步更新。

## 检查

```bash
bash scripts/check-alist-xstrm.sh
```

## 一键修复

```bash
bash scripts/fix-alist-xstrm.sh
```

## 修复脚本会做什么

1. 读取 `alist` 当前容器 IP
2. 检查 5244 是否误暴露到公网
3. 更新这两个文件中的 `alistPublicAddr`
   - `nginx/conf.d/config/constant-mount.js`
   - `nginx/conf.d/config/constant-mount.runtime.js`
4. 重启 `xstrm-nginx`

## 注意

- 当前方案依赖 `alist` 容器 IP，属于短期稳定方案
- 若后续重建容器或 Docker 网络变化，建议重新执行修复脚本
- 长期更优方案：给 `alist` 提供稳定网络名/服务名，避免依赖裸 IP
