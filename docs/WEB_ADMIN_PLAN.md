# xstrm Web Admin 接入说明（第一版）

## 已提供 API

默认监听：`127.0.0.1:18095`

### 1. 查看状态
```http
GET /api/admin/xstrm/status
```

### 2. 查看最新日志
```http
GET /api/admin/xstrm/logs/latest
```

### 3. 扫描新增
```http
POST /api/admin/xstrm/scan
```

### 4. 扫描指定目录
```http
POST /api/admin/xstrm/scan-path
Content-Type: application/json

{"path":"/115/电影/泰坦尼克号"}
```

### 5. 全量重建
```http
POST /api/admin/xstrm/rebuild
```

## 建议的 nginx 转发

后续可把 `/api/admin/xstrm/` 反代到：
- `http://127.0.0.1:18095`

## 当前安全边界

第一版仅监听 `127.0.0.1`，适合：
- 本机 nginx 反代
- 内网受控接入

不建议直接暴露公网。
