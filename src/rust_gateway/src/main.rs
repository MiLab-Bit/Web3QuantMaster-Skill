// Web3QuantMaster Gateway v6.0 - Rust 高性能实现
// 
// 性能目标:
// - P99 延迟：<10ms (缓存命中 <1ms)
// - 并发：10,000+ RPS
// - Token 节省：90% (二进制协议)
//
// 技术栈:
// - Rust + Tokio (异步运行时)
// - Actix-web (Web 框架)
// - Redis (缓存)
// - Protocol Buffers (二进制序列化)
// - Edge Computing (Cloudflare Workers)

use actix_web::{web, App, HttpServer, HttpResponse, middleware};
use redis::{Client, Commands, AsyncCommands};
use tokio::sync::RwLock;
use std::sync::Arc;
use std::time::{Duration, Instant};
use serde::{Deserialize, Serialize};
use prost::Message;

// ── Protocol Buffers 定义 ───────────────────────────────────────────────
// 
// syntax = "proto3";
// package wqm;
// 
// message PriceRequest {
//   string symbol = 1;
//   repeated string fields = 2;
// }
// 
// message PriceResponse {
//   string symbol = 1;
//   double price = 2;
//   double change_24h = 3;
//   int64 timestamp = 4;
// }
// 
// message BatchRequest {
//   repeated PriceRequest requests = 1;
// }
// 
// message BatchResponse {
//   repeated PriceResponse responses = 1;
// }

include!("proto/wqm.rs");

// ── 配置 ─────────────────────────────────────────────────────────────────

struct Config {
    redis_url: String,
    cache_ttl_sec: u64,
    max_concurrent: usize,
}

impl Config {
    fn from_env() -> Self {
        Self {
            redis_url: std::env::var("REDIS_URL")
                .unwrap_or_else(|_| "redis://localhost:6379".to_string()),
            cache_ttl_sec: 60,
            max_concurrent: 10000,
        }
    }
}

// ── 应用状态 ─────────────────────────────────────────────────────────────

struct AppState {
    redis: Client,
    config: Config,
    request_count: RwLock<u64>,
    cache_hits: RwLock<u64>,
}

impl AppState {
    fn new(config: Config) -> Result<Self, Box<dyn std::error::Error>> {
        let redis = Client::open(config.redis_url.as_str())?;
        Ok(Self {
            redis,
            config,
            request_count: RwLock::new(0),
            cache_hits: RwLock::new(0),
        })
    }
    
    async fn get_cache(&self, key: &str) -> Option<PriceResponse> {
        let mut conn = self.redis.get_async_connection().await.ok()?;
        let data: Option<Vec<u8>> = conn.get(key).await.ok()?;
        
        if let Some(bytes) = data {
            *self.cache_hits.write().await += 1;
            PriceResponse::decode(&bytes[..]).ok()
        } else {
            None
        }
    }
    
    async fn set_cache(&self, key: &str, response: &PriceResponse) {
        let mut conn = self.redis.get_async_connection().await.ok();
        if let Some(mut c) = conn {
            let bytes = response.encode_to_vec();
            let _: () = c.set_ex(key, bytes, self.config.cache_ttl_sec).await.ok();
        }
    }
}

// ── API 端点 ─────────────────────────────────────────────────────────────

async fn health_check() -> HttpResponse {
    HttpResponse::Ok().json(serde_json::json!({
        "status": "ok",
        "version": "6.0.0-rust",
        "timestamp": chrono::Utc::now().to_rfc3339(),
    }))
}

async fn get_price(
    path: web::Path<String>,
    query: web::Query<PriceQuery>,
    state: web::Data<Arc<AppState>>,
) -> HttpResponse {
    let start = Instant::now();
    let symbol = path.into_inner();
    
    // 缓存 key
    let cache_key = format!("wqm:price:{}", symbol);
    
    // 查缓存
    if let Some(cached) = state.get_cache(&cache_key).await {
        *state.request_count.write().await += 1;
        return HttpResponse::Ok()
            .insert_header(("X-Cache", "HIT"))
            .insert_header(("X-Latency-US", start.elapsed().as_micros().to_string()))
            .content_type("application/x-protobuf")
            .body(cached.encode_to_vec());
    }
    
    // 模拟 API 调用 (实际应调用外部 API)
    tokio::time::sleep(Duration::from_millis(1)).await;
    
    let response = PriceResponse {
        symbol: symbol.clone(),
        price: 50000.0,
        change_24h: 2.5,
        timestamp: chrono::Utc::now().timestamp(),
    };
    
    // 写缓存
    state.set_cache(&cache_key, &response).await;
    *state.request_count.write().await += 1;
    
    HttpResponse::Ok()
        .insert_header(("X-Cache", "MISS"))
        .insert_header(("X-Latency-US", start.elapsed().as_micros().to_string()))
        .content_type("application/x-protobuf")
        .body(response.encode_to_vec())
}

#[derive(Deserialize)]
struct PriceQuery {
    fields: Option<String>,
}

async fn batch_request(
    payload: web::Bytes,
    state: web::Data<Arc<AppState>>,
) -> HttpResponse {
    let start = Instant::now();
    
    // 解码 Protobuf
    let batch_req = match BatchRequest::decode(&payload[..]) {
        Ok(req) => req,
        Err(_) => return HttpResponse::BadRequest().finish(),
    };
    
    // 并发处理
    let mut responses = Vec::with_capacity(batch_req.requests.len());
    for req in batch_req.requests {
        let cache_key = format!("wqm:price:{}", req.symbol);
        
        if let Some(cached) = state.get_cache(&cache_key).await {
            responses.push(cached);
        } else {
            // 模拟 API 调用
            let response = PriceResponse {
                symbol: req.symbol,
                price: 50000.0,
                change_24h: 2.5,
                timestamp: chrono::Utc::now().timestamp(),
            };
            responses.push(response);
        }
    }
    
    let batch_resp = BatchResponse { responses };
    
    HttpResponse::Ok()
        .insert_header(("X-Latency-US", start.elapsed().as_micros().to_string()))
        .content_type("application/x-protobuf")
        .body(batch_resp.encode_to_vec())
}

async fn metrics(state: web::Data<Arc<AppState>>) -> HttpResponse {
    let request_count = *state.request_count.read().await;
    let cache_hits = *state.cache_hits.read().await;
    let hit_rate = if request_count > 0 {
        cache_hits as f64 / request_count as f64 * 100.0
    } else {
        0.0
    };
    
    HttpResponse::Ok().json(serde_json::json!({
        "request_count": request_count,
        "cache_hits": cache_hits,
        "cache_hit_rate": hit_rate,
        "version": "6.0.0-rust",
    }))
}

// ── 主函数 ───────────────────────────────────────────────────────────────

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    let config = Config::from_env();
    let state = Arc::new(AppState::new(config).expect("Failed to create state"));
    
    println!("[Rust Gateway] Starting v6.0.0-rust...");
    println!("[Rust Gateway] Redis: {}", state.config.redis_url);
    println!("[Rust Gateway] Max concurrent: {}", state.config.max_concurrent);
    
    HttpServer::new(move || {
        App::new()
            .app_data(web::Data::new(state.clone()))
            .wrap(middleware::Logger::default())
            .route("/health", web::get().to(health_check))
            .route("/api/v1/price/{symbol}", web::get().to(get_price))
            .route("/api/v1/batch", web::post().to(batch_request))
            .route("/metrics", web::get().to(metrics))
    })
    .bind("0.0.0.0:8766")?
    .workers(4)  // CPU 核心数
    .run()
    .await
}
