"""
Dune Analytics API Integration Module v2.0
Provides functions to execute and retrieve Dune Analytics queries

变更日志：
- v2.0 (2026-05-26): 改用 DataClient 统一HTTP客户端
"""

import os
import time
from typing import Dict, List, Optional, Any
from dotenv import load_dotenv
from .data_client import DataClient

load_dotenv()


class DuneAPI:
    """Dune Analytics API client for executing and retrieving queries.

    注意：本类不是 OHLCV 数据提供方（Dune 查询客户端），
    不实现 ``core_lib.interfaces.DataProviderProtocol``。
    已在 ``NON_OHLCV_PROVIDERS`` 中显式排除。
    """
    # 显式标记：非 OHLCV 源（供装配点与测试断言）
    data_provider_protocol: bool = False

    BASE_URL = "https://api.dune.com/api/v1"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("DUNE_API_KEY")
        if not self.api_key:
            raise ValueError("DUNE_API_KEY not found. Set it in .env or pass directly.")
        
        self.client = DataClient(
            base_url=self.BASE_URL,
            timeout=30,
            headers={
                "X-Dune-API-Key": self.api_key,
                "Content-Type": "application/json"
            }
        )
    
    def execute_query(self, query_id: int, params: Optional[Dict] = None, performance: str = "medium") -> Dict:
        """Execute a Dune query by ID."""
        endpoint = f"/query/{query_id}/execute"
        payload = {"performance": performance}
        if params:
            payload["query_parameters"] = params
        
        data = self.client.post(endpoint, json=payload)
        return data
    
    def get_execution_status(self, execution_id: str) -> Dict:
        """Get the status of a query execution."""
        endpoint = f"/execution/{execution_id}/status"
        data = self.client.get(endpoint)
        return data
    
    def get_execution_results(self, execution_id: str, limit: int = 1000, offset: int = 0) -> Dict:
        """Get the results of a completed query execution."""
        endpoint = f"/execution/{execution_id}/results"
        params = {"limit": limit, "offset": offset}
        data = self.client.get(endpoint, params=params)
        return data
    
    def wait_for_results(self, execution_id: str, max_wait: int = 300, poll_interval: int = 5) -> Optional[Dict]:
        """Wait for a query to complete and return results."""
        start_time = time.time()
        while time.time() - start_time < max_wait:
            status = self.get_execution_status(execution_id)
            state = status.get("state", "UNKNOWN")
            
            if state == "QUERY_STATE_COMPLETED":
                return self.get_execution_results(execution_id)
            elif state == "QUERY_STATE_FAILED":
                raise RuntimeError(f"Query failed: {status.get('error', 'Unknown error')}")
            elif state == "QUERY_STATE_CANCELLED":
                raise RuntimeError("Query was cancelled")
            
            time.sleep(poll_interval)
        
        raise TimeoutError(f"Query did not complete within {max_wait} seconds")
    
    def run_query(self, query_id: int, params: Optional[Dict] = None) -> Dict:
        """Execute a query and wait for results (convenience method)."""
        execution = self.execute_query(query_id, params=params)
        execution_id = execution.get("execution_id")
        return self.wait_for_results(execution_id)
    
    def get_query_info(self, query_id: int) -> Dict:
        """Get information about a specific query."""
        endpoint = f"/query/{query_id}"
        data = self.client.get(endpoint)
        return data
    
    def search_queries(self, query: str, limit: int = 20) -> List[Dict]:
        """Search for public queries on Dune."""
        endpoint = "/queries/search"
        params = {"query": query, "limit": limit}
        data = self.client.get(endpoint, params=params)
        return data.get("results", [])


if __name__ == "__main__":
    try:
        api = DuneAPI()
        print("DuneAPI initialized successfully (using DataClient)")
        print(f"Base URL: {api.BASE_URL}")
    except ValueError as e:
        print(f"Warning: {e}")
        print("Set DUNE_API_KEY in .env to use Dune Analytics API")
