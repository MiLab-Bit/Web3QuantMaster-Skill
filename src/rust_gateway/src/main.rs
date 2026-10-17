// Web3QuantMaster Gateway v6.0 - Rust 高性能实现
// 
// 编译：cargo build --release
// 运行：./target/release/wqm-gateway
// 压测：ab -n 10000 -c 100 http://localhost:8766/health

use actix_web::{web, App, HttpServer, HttpResponse, middleware, dev::ConnectionInfo};
use redis::{Client, AsyncCommands, aio::Connection as RedisConnection};
use tokio::sync::RwLock;
use std::sync::Arc;
use std::time::{Duration, Instant};
use serde::{Deserialize, Serialize};
use prost::Message;
use bytes::Bytes;
use thiserror::Error;
use tracing::{info, warn, error};

// 包含生成的 Protobuf 代码
pub mod proto {
    include!(concat!(env!("OUT_DIR"), "/wqm.rs"));
}

use proto::*;

// ── 错误处理 ─────────────────────────────────────────────────────────────

#[derive(Error, Debug)]
pub enum AppError {
    #[error("Redis error: {0}")]
    Redis(#[from] redis::RedisError),
    
    #[error("Protobuf decode error: {0}")]
    Protobuf(#[from] prost::DecodeError),
    
    #[error("Internal error: {0}")]
    Internal(String),
}

impl actix_web::ResponseError for AppError {
    fn status_code(&self) -> actix_web::http::StatusCode {
        match self {
            AppError::Redis(_) => actix_web::http::StatusCode::INTERNAL_SERVER_ERROR,
            AppError::Protobuf(_) => actix_web::http::StatusCode::BAD_REQUEST,
            AppError::Internal(_) => actix_web::http::StatusCode::INTERNAL_SERVER_ERROR,
        }
    }
}

type Result<T> = std::result::Result<T, AppError>;

// ── 配置 ─────────────────────────────────────────────────────────────────

#[derive(Clone)]
struct Config {
    redis_url: String,
    cache_ttl_sec: u64,
    max_concurrent: usize,
    bind_addr: String,
    workers: usize,
}

impl Config {
    fn from_env() -> Self {
        Self {
            redis_url: std::env::var("REDIS_URL")
                .unwrap_or_else(|_| "redis://localhost:6379".to_string()),
            cache_ttl_sec: std::env::var("CACHE_TTL")
                .unwrap_or_else(|_| "60".to_string())
                .parse()
                .unwrap_or(60),
            max_concurrent: std::env::var("MAX_CONCURRENT")
                .unwrap_or_else(|_| "10000".to_string())
                .parse()
                .unwrap_or(10000),
            bind_addr: std::env::var("BIND_ADDR")
                .unwrap_or_else(|_| "0.0.0.0:8766".to_string()),
            workers: std::env::var("WORKERS")
                .unwrap_or_else(|_| "4".to_string())
                .parse()
                .unwrap_or(4),
        }
    }
}

// ── 应用状态 ─────────────────────────────────────────────────────────────

struct AppState {
    redis: Client,
    config: Config,
    request_count: RwLock<u64>,
    cache_hits: RwLock<u64>,
    cache_misses: RwLock<u64>,
}

impl AppState {
    fn new(config: Config) -> Result<Self> {
        let redis = Client::open(config.redis_url.as_str())?;
        Ok(Self {
            redis,
            config,
            request_count: RwLock::new(0),
            cache_hits: RwLock::new(0),
            cache_misses: RwLock::new(0),
        })
    }
    
    async fn get_cache(&self, key: &str) -> Option<PriceResponse> {
        let mut conn = match self.redis.get_async_connection().await.ok() {
            Some(c) => c,
            None => return None,
        };
        
        let data: Option<Vec<u8>> = conn.get(key).await.ok()?;
        
        if let Some(bytes) = data {
            *self.cache_hits.write().await += 1;
            PriceResponse::decode(&bytes[..]).ok()
        } else {
            *self.cache_misses.write().await += 1;
            None
        }
    }
    
    async fn set_cache(&self, key: &str, response: &PriceResponse) {
        let mut conn = match self.redis.get_async_connection().await.ok() {
            Some(c) => c,
            None => return,
        };
        
        let bytes = response.encode_to_vec();
        let _: () = conn.set_ex(key, bytes, self.config.cache_ttl_sec).await.ok();
    }
    
    async fn increment_request(&self) {
        *self.request_count.write().await += 1;
    }
}

// ── 响应结构 ─────────────────────────────────────────────────────────────

#[derive(Serialize, Deserialize)]
struct HealthResponse {
    status: String,
    version: String,
    timestamp: String,
}

#[derive(Serialize, Deserialize)]
struct MetricsResponse {
    request_count: u64,
    cache_hits: u64,
    cache_misses: u64,
    cache_hit_rate: f64,
    version: String,
}

#[derive(Deserialize)]
struct PriceQuery {
    fields: Option<String>,
}

// ── API 端点 ─────────────────────────────────────────────────────────────

async fn health_check() -> HttpResponse {
    HttpResponse::Ok().json(HealthResponse {
        status: "ok".to_string(),
        version: "6.0.0-rust".to_string(),
        timestamp: chrono::Utc::now().to_rfc3339(),
    })
}

async fn get_price(
    path: web::Path<String>,
    query: web::Query<PriceQuery>,
    state: web::Data<Arc<AppState>>,
) -> Result<HttpResponse> {
    let start = Instant::now();
    let symbol = path.into_inner();
    
    // 缓存 key
    let cache_key = format!("wqm:price:{}", symbol);
    
    // 查缓存
    if let Some(cached) = state.get_cache(&cache_key).await {
        state.increment_request().await;
        let latency_us = start.elapsed().as_micros();
        
        return Ok(HttpResponse::Ok()
            .insert_header(("X-Cache", "HIT"))
            .insert_header(("X-Latency-Us", latency_us.to_string()))
            .content_type("application/x-protobuf")
            .body(cached.encode_to_vec()));
    }
    
    // 未命中 - 模拟 API 调用 (实际应调用外部 API)
    tokio::time::sleep(Duration::from_millis(1)).await;
    
    let response = PriceResponse {
        symbol: symbol.clone(),
        price: 50000.0 + (std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_millis() % 1000) as f64,
        change_24h: 2.5,
        timestamp: chrono::Utc::now().timestamp(),
    };
    
    // 写缓存
    state.set_cache(&cache_key, &response).await;
    state.increment_request().await;
    
    let latency_us = start.elapsed().as_micros();
    
    Ok(HttpResponse::Ok()
        .insert_header(("X-Cache", "MISS"))
        .insert_header(("X-Latency-Us", latency_us.to_string()))
        .content_type("application/x-protobuf")
        .body(response.encode_to_vec()))
}

async fn batch_request(
    payload: Bytes,
    state: web::Data<Arc<AppState>>,
) -> Result<HttpResponse> {
    let start = Instant::now();
    
    // 解码 Protobuf
    let batch_req = BatchRequest::decode(&payload[..])?;
    
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
    let latency_us = start.elapsed().as_micros();
    
    Ok(HttpResponse::Ok()
        .insert_header(("X-Latency-Us", latency_us.to_string()))
        .content_type("application/x-protobuf")
        .body(batch_resp.encode_to_vec()))
}

async fn metrics(state: web::Data<Arc<AppState>>) -> HttpResponse {
    let request_count = *state.request_count.read().await;
    let cache_hits = *state.cache_hits.read().await;
    let cache_misses = *state.cache_misses.read().await;
    let hit_rate = if request_count > 0 {
        cache_hits as f64 / (cache_hits + cache_misses) as f64 * 100.0
    } else {
        0.0
    };
    
    HttpResponse::Ok().json(MetricsResponse {
        request_count,
        cache_hits,
        cache_misses,
        hit_rate,
        version: "6.0.0-rust".to_string(),
    })
}

// ── 主函数 ───────────────────────────────────────────────────────────────

#[actix_web::main]
async fn main() -> std::io::Result<()> {
    // 初始化日志
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::from_default_env()
                .add_directive("actix_web=info".parse().unwrap())
                .add_directive("wqm_gateway=debug".parse().unwrap()),
        )
        .init();
    
    let config = Config::from_env();
    let state = Arc::new(AppState::new(config.clone()).expect("Failed to create state"));
    
    info!("🦀 Rust Gateway v6.0.0 starting...");
    info!("   Redis: {}", config.redis_url);
    info!("   Bind: {}", config.bind_addr);
    info!("   Workers: {}", config.workers);
    info!("   Max concurrent: {}", config.max_concurrent);
    info!("   Cache TTL: {}s", config.cache_ttl_sec);
    
    HttpServer::new(move || {
        App::new()
            .app_data(web::Data::new(state.clone()))
            .app_data(web::PayloadConfig::new(10 * 1024 * 1024)) // 10MB max payload
            .wrap(middleware::Logger::default())
            .route("/health", web::get().to(health_check))
            .route("/api/v1/price/{symbol}", web::get().to(get_price))
            .route("/api/v1/batch", web::post().to(batch_request))
            .route("/metrics", web::get().to(metrics))
    })
    .bind(&config.bind_addr)?
    .workers(config.workers)
    .run()
    .await
}
