"""AList API client."""
import json
from typing import Any, Dict
from urllib import request, error


class AlistClient:
    """AList API client."""

    def __init__(self, base_url: str, token: str):
        """Initialize AList client.

        Args:
            base_url: AList server base URL (e.g., http://YOUR_ALIST_HOST:5388)
            token: AList authentication token
        """
        self.base_url = base_url.rstrip('/')
        self.token = token.strip()

    def _request(self, api_path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Make POST request to AList API."""
        url = f'{self.base_url}{api_path}'
        req = request.Request(url, method='POST')
        req.add_header('Content-Type', 'application/json')
        req.add_header('Authorization', self.token)
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        try:
            with request.urlopen(req, data=body, timeout=60) as resp:
                raw = resp.read().decode('utf-8', 'ignore')
        except error.HTTPError as e:
            raw = e.read().decode('utf-8', 'ignore') if e.fp else ''
            raise RuntimeError(f'AList API HTTP {e.code}: {raw[:200]}')
        except Exception as e:
            raise RuntimeError(f'AList API 请求失败: {e}')
        try:
            data = json.loads(raw)
        except Exception:
            raise RuntimeError(f'AList API 返回非 JSON: {raw[:200]}')
        if data.get('code') not in (200, None):
            raise RuntimeError(data.get('message') or data.get('msg') or f'AList API 错误: {data}')
        return data

    def list_dir(self, path: str, per_page: int = 0, refresh: bool = False) -> Dict[str, Any]:
        """List directory contents.

        Args:
            path: Directory path to list
            per_page: Items per page (0 for all)
            refresh: Whether to refresh cache

        Returns:
            API response with 'content' list
        """
        return self._request('/api/fs/list', {
            'path': path,
            'password': '',
            'page': 1,
            'per_page': per_page,
            'refresh': refresh,
        })

    def get_storage(self, path: str) -> Dict[str, Any]:
        """Get storage info for a path.

        Args:
            path: Path to check storage for

        Returns:
            API response with storage info
        """
        return self._request('/api/fs/get', {
            'path': path,
            'password': '',
        })

    def me(self) -> Dict[str, Any]:
        """Get current user info."""
        return self._request('/api/me', {})


def alist_request(config: dict, api_path: str, payload: dict) -> dict:
    """Legacy function for backward compatibility."""
    base_url = (config.get('alist', {}) or {}).get('base_url', '').rstrip('/')
    token = (config.get('alist', {}) or {}).get('token', '')
    if not base_url:
        raise RuntimeError('alist.base_url 未配置')
    if not token:
        raise RuntimeError('alist.token 未配置')
    client = AlistClient(base_url, token)
    return client._request(api_path, payload)
