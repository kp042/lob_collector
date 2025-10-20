# Binance Limit Order Book Collector

A high-performance, production-ready data collector for Binance Limit Order Books (LOB). This system efficiently aggregates order book data for all active USDT trading pairs on Binance Spot market, processing depth data and streaming it to Kafka for real-time analysis.

## 🚀 Project Overview

This collector is designed to handle Binance's strict API rate limits by utilizing multiple IP addresses and intelligent request weighting. It processes approximately 450+ trading pairs every 8-10 minutes while staying within Binance's 6,000 request weight per minute limit.

### Key Achievements
- **Multi-IP Architecture**: Utilizes 2 VPS IPs to maximize data collection throughput
- **Intelligent Rate Limiting**: Implements Binance's request weight system (250 weight per symbol)
- **Real-time Streaming**: Kafka integration for seamless data pipeline
- **Production Ready**: Error handling, retry mechanisms, and comprehensive logging

## 📊 System Architecture

```
Binance REST API → Multi-IP Collector → Data Aggregation → Kafka → ClickHouse
       ↑                  ↑                  ↑             ↑          ↑
   5000 levels      Weight-aware        Depth by %     Streaming   Analytics
   depth data      request scheduling   thresholds                 Storage
```

## 🛠 Technical Features

### Binance API Integration
- **Maximum Depth**: 5,000 order book levels per symbol
- **Request Weight**: 250 units per symbol (maximum depth)
- **Rate Limits**: 24 requests/minute per IP (48 total with 2 IPs)
- **Symbol Filtering**: Active USDT pairs in TRADING status only

### Data Processing
- **Depth Aggregation**: Calculates order book depth at 1%, 3%, 5%, 8%, 15%, 20%, 30%, 60% thresholds
- **Volume Metrics**: Total bid/ask volumes and level counts
- **Price Analysis**: Best bid/ask, min/max prices, percentage spreads
- **Iteration Tracking**: UUID-based iteration identification for data consistency

### Performance Optimizations
- **Concurrent Processing**: ThreadPoolExecutor with configurable workers
- **Connection Pooling**: Persistent HTTP sessions with retry mechanisms
- **Memory Efficiency**: Streaming data processing without large in-memory buffers
- **Network Optimization**: Source IP binding for multi-IP support

## 📁 Project Structure

```
lob_collector/
├── collector.py              # Main collection engine
├── config.py                 # Configuration management
├── exceptions.json           # Symbol exclusion list
├── Dockerfile               # Container definition
├── docker-compose.yml       # Service orchestration
├── requirements.txt         # Python dependencies
├── .env.example             # Environment template
└── logs/                    # Log directory (created at runtime)
```

## ⚙️ Installation & Setup

### Prerequisites
- Docker & Docker Compose
- VPS with 2 dedicated IP addresses
- Kafka cluster (can be remote)
- Minimum 2GB RAM, 2 CPU cores

### Quick Start

1. **Clone and Configure**
```bash
git clone <repository-url>
cd lob_collector
cp .env.example .env
```

2. **Environment Configuration**
Edit `.env` with your actual values:
```env
# VPS IP Addresses
MAIN_IP=192.168.1.100
ADDITIONAL_IP=192.168.1.101

# Kafka Configuration
KAFKA_BROKER=your.kafka.server:9092
KAFKA_TOPIC=binanceloballspot
```

3. **Build and Deploy**
```bash
docker compose up -d --build
```

4. **Verify Operation**
```bash
docker logs -f binance-lob-collector
```

### Manual Installation (Without Docker)

1. **Python Environment**
```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
```

2. **Environment Setup**
```bash
export MAIN_IP="your_main_ip"
export ADDITIONAL_IP="your_secondary_ip"
export KAFKA_BROKER="kafka_server:9092"
export KAFKA_TOPIC="binanceloballspot"
```

3. **Run Collector**
```bash
python collector.py
```

## 🔧 Configuration Details

### Binance API Settings
```python
# Defined in collector.py
EXCHANGE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo"
DEPTH_URL = "https://api.binance.com/api/v3/depth"
MAX_DEPTH = 5000           # Maximum order book levels
MAX_REQUESTS = 5           # Concurrent requests per batch
REQUEST_INTERVAL = 2.5     # Seconds between batches
TIMEOUT = 10               # Request timeout in seconds
```

### Kafka Producer Configuration
```python
KAFKA_CONFIG = {
    'bootstrap.servers': KAFKA_BROKER,
    'client.id': 'lobcollector_allspot',
    'acks': 1,                          # Leader acknowledgment
    'retries': 2,                       # Minimum retry attempts
    'compression.type': 'none',         # No compression for low latency
    'batch.num.messages': 10,           # Small batches
    'linger.ms': 0,                     # No batching delay
    'queue.buffering.max.messages': 1000,
    'message.timeout.ms': 3000,         # 3 second send timeout
    'max.in.flight.requests.per.connection': 1  # Message ordering
}
```

### Symbol Management
- **Automatic Discovery**: Fetches all active USDT pairs from Binance
- **Exclusion List**: Managed via `exceptions.json`
- **Status Filtering**: Only TRADING status symbols included

## 📈 Data Schema

### Kafka Message Format
```json
{
  "symbol": "BTCUSDT",
  "best_bid": 50000.0,
  "best_ask": 50050.0,
  "min_bid": 49500.0,
  "max_ask": 50500.0,
  "depth_1pct_bid": 1500000,
  "depth_1pct_ask": 1200000,
  "depth_3pct_bid": 3500000,
  "depth_3pct_ask": 3200000,
  "depth_5pct_bid": 5500000,
  "depth_5pct_ask": 5200000,
  "depth_8pct_bid": 8500000,
  "depth_8pct_ask": 8200000,
  "depth_15pct_bid": 15500000,
  "depth_15pct_ask": 15200000,
  "depth_20pct_bid": 20500000,
  "depth_20pct_ask": 20200000,
  "depth_30pct_bid": 30500000,
  "depth_30pct_ask": 30200000,
  "depth_60pct_bid": 60500000,
  "depth_60pct_ask": 60200000,
  "total_bid_volume": 100000000,
  "total_ask_volume": 95000000,
  "count_bid_levels": 2450,
  "count_ask_levels": 2380,
  "max_pct_from_best_bid": 1,
  "max_pct_from_best_ask": 1,
  "event_time": 1633045025,
  "iteration_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "status": "ok"
}
```

### ClickHouse Table Schema
```sql
CREATE TABLE cryptodata.blob_rest_all_aggregated
(
    `iteration_id` UUID CODEC(ZSTD(1)),
    `symbol` LowCardinality(String) CODEC(ZSTD(1)),
    `best_bid` Decimal(16, 8) CODEC(ZSTD(1)),
    `best_ask` Decimal(16, 8) CODEC(ZSTD(1)),
    `min_bid` Decimal(16, 8) CODEC(ZSTD(1)),
    `max_ask` Decimal(16, 8) CODEC(ZSTD(1)),
    `depth_1pct_bid` UInt64 CODEC(ZSTD(1)),
    `depth_1pct_ask` UInt64 CODEC(ZSTD(1)),
    `depth_3pct_bid` UInt64 CODEC(ZSTD(1)),
    `depth_3pct_ask` UInt64 CODEC(ZSTD(1)),
    `depth_5pct_bid` UInt64 CODEC(ZSTD(1)),
    `depth_5pct_ask` UInt64 CODEC(ZSTD(1)),
    `depth_8pct_bid` UInt64 CODEC(ZSTD(1)),
    `depth_8pct_ask` UInt64 CODEC(ZSTD(1)),
    `depth_15pct_bid` UInt64 CODEC(ZSTD(1)),
    `depth_15pct_ask` UInt64 CODEC(ZSTD(1)),
    `depth_20pct_bid` UInt64 CODEC(ZSTD(1)),
    `depth_20pct_ask` UInt64 CODEC(ZSTD(1)),
    `depth_30pct_bid` UInt64 CODEC(ZSTD(1)),
    `depth_30pct_ask` UInt64 CODEC(ZSTD(1)),
    `depth_60pct_bid` UInt64 CODEC(ZSTD(1)),
    `depth_60pct_ask` UInt64 CODEC(ZSTD(1)),
    `total_bid_volume` UInt64 CODEC(ZSTD(1)),
    `total_ask_volume` UInt64 CODEC(ZSTD(1)),
    `count_bid_levels` UInt16 CODEC(ZSTD(1)),
    `count_ask_levels` UInt16 CODEC(ZSTD(1)),
    `max_pct_from_best_bid` UInt8 CODEC(ZSTD(1)),
    `max_pct_from_best_ask` UInt8 CODEC(ZSTD(1)),    
    `event_time` UInt64 CODEC(ZSTD(1))
)
ENGINE = MergeTree
ORDER BY (symbol, event_time)
SETTINGS index_granularity = 8192;
```

## 🔍 Monitoring & Logging

### Log Structure
The collector provides detailed logging with rotation (5 files × 10MB each):

```
2024-01-15 12:00:00 - INFO - Starting collector service with Kafka integration
2024-01-15 12:00:01 - INFO - Loaded 450 symbols from configuration
2024-01-15 12:00:01 - DEBUG - Fetched 450 active trading symbols
2024-01-15 12:08:15 - INFO - Iteration completed: {"iteration_id": "uuid", "duration_sec": 485.2, "total_symbols": 450, "success": 445, "failed": 5, "success_rate": 98.89, "failed_symbols": ["SYMBOL1", "SYMBOL2"]}
```

### Performance Metrics
- **Iteration Duration**: 480-600 seconds (8-10 minutes)
- **Success Rate**: Typically 98%+
- **Kafka Throughput**: ~10 messages/second during peak
- **Memory Usage**: Stable at 150-200MB

### Health Checks
```bash
# Container status
docker ps

# Real-time logs
docker logs -f binance-lob-collector

# Resource usage
docker stats binance-lob-collector

# Log files
tail -f logs/collector.log
```

## 🚨 Troubleshooting

### Common Issues

1. **Kafka Connection Failures**
```bash
# Test Kafka connectivity
telnet kafka_server 9092

# Check Kafka topic exists
kafka-topics.sh --list --bootstrap-server kafka_server:9092
```

2. **Binance Rate Limiting**
- Symptoms: 429 HTTP errors in logs
- Solution: Verify IP configuration and increase REQUEST_INTERVAL

3. **Permission Denied Errors**
```bash
# Fix log directory permissions
chmod 755 logs/
docker compose down && docker compose up -d --build
```

4. **Container Network Issues**
```bash
# Verify host network mode
docker inspect binance-lob-collector | grep NetworkMode

# Check IP configuration on VPS
ip addr show
```

### Performance Tuning

**For Higher Throughput:**
- Increase `MAX_REQUESTS` (if Binance limits allow)
- Add more IP addresses
- Optimize Kafka batch settings

**For Better Reliability:**
- Increase retry attempts and timeouts
- Implement circuit breaker pattern
- Add dead letter queue for failed messages

## 🔄 Operations

### Daily Operations
```bash
# Monitor operation
docker logs --tail 100 binance-lob-collector

# Check resource usage
docker stats binance-lob-collector

# Verify data flow
# (Check ClickHouse for recent data)
```

### Maintenance Tasks
```bash
# Update application
git pull
docker compose down
docker compose up -d --build

# Log rotation (automatic, but manual cleanup if needed)
find logs/ -name "*.log" -mtime +7 -delete

# Container cleanup
docker system prune -f
```

### Backup Procedures
- Kafka topics with appropriate retention policies
- ClickHouse data backups
- Configuration and exclusion list versioning

## 📊 Binance API Reference

### Rate Limits
- **Hard Limit**: 6,000 request weight per minute
- **IP-based**: Limits tracked per IP address
- **Weight System**: 
  - 1-100 levels: 1 weight
  - 101-500: 5 weight
  - 501-1000: 10 weight
  - 1001-5000: 50 weight

### Endpoints Used
- `GET /api/v3/exchangeInfo` - Symbol information (low weight)
- `GET /api/v3/depth` - Order book data (250 weight at limit=5000)

## 🤝 Contributing

### Development Setup
1. Fork the repository
2. Create feature branch (`git checkout -b feature/improvement`)
3. Test changes thoroughly
4. Submit pull request

### Testing
- Unit tests for data processing functions
- Integration tests with mock Binance API
- Performance testing with full symbol list

## 📄 License

MIT License - see LICENSE file for details.

## 🙋‍♂️ Support

For issues and questions:
1. Check troubleshooting section above
2. Review Binance API documentation
3. Create GitHub issue with detailed logs

---

**Note**: This collector is designed for professional use and complies with Binance API terms of service. Always monitor your API usage and adjust parameters according to current Binance limits.
