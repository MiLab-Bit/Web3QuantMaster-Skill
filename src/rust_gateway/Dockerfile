# Build stage
FROM rust:1.75-slim as builder

WORKDIR /app
RUN apt-get update && apt-get install -y protobuf-compiler && rm -rf /var/lib/apt/lists/*

COPY . .
RUN cargo build --release

# Runtime stage
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y ca-certificates && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/target/release/wqm-gateway /usr/local/bin/

EXPOSE 8766
CMD ["wqm-gateway"]
