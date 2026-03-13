# xstrm Web Admin 入口保护建议

## 当前状态

当前第一版 Web 管理页可通过：
- `/admin/xstrm/index.html`
- `/api/admin/xstrm/*`

访问。

默认适合：
- 内网
- 反代后受控环境
- 自己使用

## 推荐保护顺序

### 方案 A：先做来源限制（推荐起步）

仅允许内网 / 指定来源访问：

```nginx
location /admin/xstrm/ {
    allow 127.0.0.1;
    allow 192.168.0.0/16;
    allow 10.0.0.0/8;
    deny all;
    alias /opt/xstrm-suite/web/admin/;
}

location /api/admin/xstrm/ {
    allow 127.0.0.1;
    allow 192.168.0.0/16;
    allow 10.0.0.0/8;
    deny all;
    proxy_pass http://127.0.0.1:18095;
}
```

### 方案 B：Basic Auth

生成密码文件：

```bash
printf 'admin:$(openssl passwd -apr1 "你的密码")\n' > /opt/xstrm-suite/nginx/conf.d/.htpasswd-xstrm-admin
```

然后加到 nginx：

```nginx
auth_basic "xstrm admin";
auth_basic_user_file /opt/xstrm-suite/nginx/conf.d/.htpasswd-xstrm-admin;
```

建议页面和 API 两边都加。

## 建议

如果当前先求稳：
1. 先开来源限制
2. 再补 Basic Auth

不要直接裸露到公网。
