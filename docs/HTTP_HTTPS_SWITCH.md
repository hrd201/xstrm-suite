# HTTP / HTTPS Mode Switch

## 结论

从 HTTP 切换到 HTTPS，或从 HTTPS 切换回 HTTP：

- **不需要重新安装 nginx**
- **不需要重新安装 Docker**
- **不需要重装整个 xstrm-suite**

只需要：
1. 更新 `config/runtime.yaml`
2. 重新渲染配置
3. 重新应用配置
4. 重启 Docker 容器

---

## HTTP -> HTTPS

需要修改：
- `nginx.https_enabled: true`
- `nginx.ssl_cert`
- `nginx.ssl_key`
- 必要时修改 `nginx.server_name`
- 必要时修改 `nginx.https_port`

然后执行：

```bash
python3 scripts/render_runtime.py
python3 scripts/apply_runtime.py
scripts/docker_ctl.sh restart
```

---

## HTTPS -> HTTP

需要修改：
- `nginx.https_enabled: false`
- 清空 `nginx.ssl_cert`
- 清空 `nginx.ssl_key`

然后执行：

```bash
python3 scripts/render_runtime.py
python3 scripts/apply_runtime.py
scripts/docker_ctl.sh restart
```

---

## 原则

模式切换属于**配置切换**，不是**软件重装**。
