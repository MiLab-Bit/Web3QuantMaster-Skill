// Web3QuantMaster Edge Worker v6.0
// 部署到 Cloudflare Workers (全球 275+ 节点)
//
// 性能优势:
// - 边缘缓存：用户最近节点 (<10ms)
// - DDoS 防护：Cloudflare 自动
// - 零冷启动：V8 Isolates
// - 免费额度：100K 请求/天

import type { ExecutionContext } from "@cloudflare/workers-types";

// ── 缓存配置 ─────────────────────────────────────────────────────────────

const CACHE_TTL = {
  price: 30,      // 价格 30 秒
  defi: 300,      // DeFi 5 分钟
  narrative: 600, // 叙事 10 分钟
};

const CACHE_PREFIX = "wqm:";

// ── 请求处理 ─────────────────────────────────────────────────────────────

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    const url = new URL(request.url);
    const path = url.pathname;
    
    // 健康检查
    if (path === "/health") {
      return json({ status: "ok", version: "6.0.0-edge" });
    }
    
    // 价格查询
    if (path.startsWith("/api/v1/price/")) {
      const symbol = path.split("/").pop() || "BTC";
      return handlePrice(request, env, symbol);
    }
    
    // 批量请求
    if (path === "/api/v1/batch" && request.method === "POST") {
      return handleBatch(request, env);
    }
    
    // 404
    return json({ error: "Not found" }, { status: 404 });
  },
};

// ── 端点处理 ─────────────────────────────────────────────────────────────

async function handlePrice(request: Request, env: Env, symbol: string): Promise<Response> {
  const start = Date.now();
  const cacheKey = `${CACHE_PREFIX}price:${symbol}`;
  
  // 查缓存 (Cloudflare Cache API)
  const cache = caches.default;
  let response = await cache.match(cacheKey);
  
  if (response) {
    const latency = Date.now() - start;
    return new Response(response.body, {
      headers: {
        "Content-Type": "application/json",
        "X-Cache": "HIT",
        "X-Latency-MS": latency.toString(),
        "Cache-Control": `max-age=${CACHE_TTL.price}`,
      },
    });
  }
  
  // 未命中 - 调用外部 API
  const data = await fetchPriceFromAPI(symbol);
  
  response = json({
    data,
    from_cache: false,
    timestamp: new Date().toISOString(),
  }, {
    headers: {
      "X-Cache": "MISS",
      "X-Latency-MS": (Date.now() - start).toString(),
      "Cache-Control": `max-age=${CACHE_TTL.price}`,
    },
  });
  
  // 写缓存
  ctx.waitUntil(cache.put(cacheKey, response.clone()));
  
  return response;
}

async function handleBatch(request: Request, env: Env): Promise<Response> {
  const start = Date.now();
  const requests = await request.json<BatchRequest[]>();
  
  // 并发处理
  const results = await Promise.all(
    requests.map(async (req) => {
      const cacheKey = `${CACHE_PREFIX}${req.endpoint}:${JSON.stringify(req.params)}`;
      
      // 查缓存
      const cached = await caches.default.match(cacheKey);
      if (cached) {
        return { data: await cached.json(), from_cache: true };
      }
      
      // 调用 API
      const data = await fetchEndpoint(req.endpoint, req.params);
      return { data, from_cache: false };
    })
  );
  
  const latency = Date.now() - start;
  
  return json({
    results,
    latency_ms: latency,
    count: results.length,
  });
}

// ── 辅助函数 ─────────────────────────────────────────────────────────────

async function fetchPriceFromAPI(symbol: string): Promise<PriceData> {
  // 模拟 API 调用 (实际应调用 CoinGecko/Binance 等)
  await sleep(10); // 10ms 模拟延迟
  
  return {
    symbol,
    price: 50000 + Math.random() * 1000,
    change_24h: (Math.random() - 0.5) * 10,
    volume_24h: 1e9 + Math.random() * 1e8,
  };
}

async function fetchEndpoint(endpoint: string, params: any): Promise<any> {
  // 路由到不同外部 API
  switch (endpoint) {
    case "price":
      return fetchPriceFromAPI(params.symbol);
    case "defi_tvl":
      return fetchDeFiTVL();
    default:
      throw new Error(`Unknown endpoint: ${endpoint}`);
  }
}

async function fetchDeFiTVL(): Promise<DeFiTVL> {
  await sleep(20);
  return {
    total: 50e9,
    protocols: [
      { name: "Lido", tvl: 23e9 },
      { name: "AAVE", tvl: 11e9 },
      { name: "Maker", tvl: 5e9 },
    ],
  };
}

function json(data: any, init?: ResponseInit): Response {
  return new Response(JSON.stringify(data), {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
}

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

// ── 类型定义 ─────────────────────────────────────────────────────────────

interface PriceData {
  symbol: string;
  price: number;
  change_24h: number;
  volume_24h: number;
}

interface DeFiTVL {
  total: number;
  protocols: Array<{ name: string; tvl: number }>;
}

interface BatchRequest {
  endpoint: string;
  params: Record<string, any>;
}
