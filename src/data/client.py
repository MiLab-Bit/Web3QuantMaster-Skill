"""
Shared Data Client Module
Unified HTTP client for all data-fetching modules.
Eliminates duplicated requests.Session() setup across 7+ modules.
Provides: rate limiting, retries, timeout defaults, error handling.
"""

import time
import requests
from typing import Dict, List, Optional, Any, Union

class DataClient:
    """
    Shared HTTP client with built-in rate limiting and retry logic.
    
    Usage:
        client = DataClient(base_delay=1.0, max_retries=3)
        data = client.get("https://api.example.com/data", params={"key": "val"})
    """

    def __init__(
        self,
        base_url: Optional[str] = None,
        base_delay: float = 1.0,
        max_retries: int = 3,
        timeout: int = 15,
        user_agent: str = "Web3QuantMaster/0.1.0",
        proxy_routing: Optional[Dict[str, Optional[str]]] = None
    ):
        self.base_url = base_url.rstrip('/') if base_url else None
        self.base_delay = base_delay
        self.max_retries = max_retries
        self.timeout = timeout
        self._last_request_time = 0.0
        self.proxy_routing = proxy_routing or {}
        self._default_proxy = None

        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": user_agent,
            "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Connection": "keep-alive",
        })

    def _rate_limit(self) -> None:
        """Enforce minimum delay between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.base_delay:
            time.sleep(self.base_delay - elapsed)
        self._last_request_time = time.time()

    def _handle_response(self, resp: requests.Response) -> Union[Dict, str]:
        """Parse response with error handling."""
        if resp.status_code == 200:
            content_type = resp.headers.get("Content-Type", "")
            if "application/json" in content_type:
                return resp.json()
            return resp.text
        elif resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", 30))
            return {"error": f"Rate limited", "retry_after": retry_after}
        elif resp.status_code == 404:
            return {"error": "Not found (404)"}
        elif resp.status_code >= 500:
            return {"error": f"Server error ({resp.status_code})"}
        else:
            return {"error": f"HTTP {resp.status_code}", "body": resp.text[:300]}


    def _get_proxy_for_url(self, url: str) -> Optional[Dict[str, str]]:
        """
        Get proxy config based on URL host.
        Returns: {'http': proxy, 'https': proxy} or None for direct connection.
        """
        host = url.replace('https://', '').replace('http://', '').split('/')[0].split('?')[0]
        
        if host in self.proxy_routing:
            proxy = self.proxy_routing[host]
            if proxy is None:
                return None
            return {'http': proxy, 'https': proxy}
        
        for pattern, proxy in self.proxy_routing.items():
            if pattern.startswith('*') and host.endswith(pattern[1:]):
                if proxy is None:
                    return None
                return {'http': proxy, 'https': proxy}
        
        if self._default_proxy:
            return {'http': self._default_proxy, 'https': self._default_proxy}
        
        return None

    def get(self, url: str, params: Optional[Dict] = None,
            is_json: bool = True, timeout: Optional[int] = None,
            headers: Optional[Dict] = None) -> Any:
        """
        Rate-limited GET request.
        Returns parsed JSON (dict/list), text (str), or error dict.
        
        Args:
            headers: Optional custom headers (merged with session defaults)
        """
        # PREPEND BASE_URL IF URL IS RELATIVE
        if self.base_url and not url.startswith(('http://', 'https://')):
            url = f"{self.base_url}/{url.lstrip('/')}"
        
        self._rate_limit()
        to = timeout or self.timeout

        req_headers = None
        if headers:
            req_headers = {**self.session.headers, **headers}

        for attempt in range(self.max_retries):
            try:
                proxies = self._get_proxy_for_url(url)
                resp = self.session.get(url, params=params, timeout=to, headers=req_headers, proxies=proxies)
                result = self._handle_response(resp)
                if isinstance(result, dict) and "error" in result:
                    if attempt < self.max_retries - 1:
                        time.sleep(2 ** attempt)
                        continue
                return result
            except requests.exceptions.Timeout:
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return {"error": f"Timeout after {to}s"}
            except Exception as e:
                if attempt < self.max_retries - 1:
                    time.sleep(1)
                    continue
                return {"error": str(e)}

        return {"error": "Max retries exceeded"}

    def get_json(self, url: str, params: Optional[Dict] = None,
                 timeout: Optional[int] = None) -> Dict:
        """Convenience: always return dict (never raw text)."""
        result = self.get(url, params=params, is_json=True, timeout=timeout)
        if isinstance(result, dict):
            return result
        return {"error": "Expected JSON, got text", "raw": str(result)[:200]}

    def get_text(self, url: str, params: Optional[Dict] = None,
                 timeout: Optional[int] = None) -> str:
        """Convenience: always return text."""
        result = self.get(url, params=params, is_json=False, timeout=timeout)
        if isinstance(result, str):
            return result
        return ""

    def post(self, url: str, json: Optional[Dict] = None,
             data: Optional[bytes] = None,
             params: Optional[Dict] = None,
             timeout: Optional[int] = None,
             headers: Optional[Dict] = None) -> Any:
        """
        Rate-limited POST request.
        Returns parsed JSON (dict/list), text (str), or error dict.
        
        Args:
            headers: Optional custom headers (merged with session defaults)
        """
        # PREPEND BASE_URL IF URL IS RELATIVE
        if self.base_url and not url.startswith(('http://', 'https://')):
            url = f"{self.base_url}/{url.lstrip('/')}"
        
        self._rate_limit()
        to = timeout or self.timeout

        req_headers = None
        if headers:
            req_headers = {**self.session.headers, **headers}

        for attempt in range(self.max_retries):
            try:
                if data is not None:
                    proxies = self._get_proxy_for_url(url)
                    resp = self.session.post(url, data=data, params=params, timeout=to, headers=req_headers, proxies=proxies)
                else:
                    proxies = self._get_proxy_for_url(url)
                    resp = self.session.post(url, json=json, params=params, timeout=to, headers=req_headers, proxies=proxies)
                result = self._handle_response(resp)
                if isinstance(result, dict) and "error" in result:
                    if attempt < self.max_retries - 1:
                        time.sleep(2 ** attempt)
                        continue
                return result
            except requests.exceptions.Timeout:
                if attempt < self.max_retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return {"error": f"Timeout after {to}s"}
            except Exception as e:
                if attempt < self.max_retries - 1:
                    time.sleep(1)
                    continue
                return {"error": str(e)}

        return {"error": "Max retries exceeded"}

    def post_json(self, url: str, json_body: Optional[Dict] = None,
                  params: Optional[Dict] = None,
                  timeout: Optional[int] = None) -> Dict:
        """Convenience: always return dict."""
        result = self.post(url, json=json_body, params=params, timeout=timeout)
        if isinstance(result, dict):
            return result
        return {"error": "Expected JSON, got text", "raw": str(result)[:200]}

    def batch_get(self, urls: List[str], max_workers: int = 3) -> List[Any]:
        """Fetch multiple URLs with rate limiting (sequential, respects delay)."""
        results = []
        for url in urls:
            results.append(self.get(url))
        return results

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.session.close()

_default_client: Optional[DataClient] = None

def get_default_client() -> DataClient:
    """Get or create the default shared client (singleton pattern)."""
    global _default_client
    if _default_client is None:
        _default_client = DataClient()
    return _default_client

if __name__ == "__main__":
    client = DataClient(base_delay=0.5)

    print("=== Test: CoinGecko ping ===")
    result = client.get_json("https://api.coingecko.com/api/v3/ping")
    print(f"Result: {result}")

    print("\n=== Test: Get text ===")
    text = client.get_text("https://example.com")
    print(f"Text length: {len(text)}")

    print("\nDataClient ready.")