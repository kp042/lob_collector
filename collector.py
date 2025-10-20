"""
LOB (Limit Order Book) collector from Binance.
Agggregated LOB by depth pcts data -> Kafka.
All USDT and TRADING pairs. SPOT market only.
VPS with 2 IP.
~8-10 minutes for each itteration (for all coins) approximetely 
according Binance request weight limits.
About Binance Weights:
https://www.binance.com/en/support/faq/detail/360004492232
https://developers.binance.com/docs/binance-spot-api-docs/rest-api/limits
"""
import requests
import time
import logging
import json
import uuid
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from logging.handlers import RotatingFileHandler
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from confluent_kafka import Producer
from config import config

# Private data
MAIN_IP = config.ip.main_ip
ADDITIONAL_IP = config.ip.second_ip
KAFKA_BROKER = config.kafka.kafka_broker
KAFKA_TOPIC = config.kafka.kafka_topic

# Binance configuration parameters
EXCHANGE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo"  # to fetch all symbols
DEPTH_URL = "https://api.binance.com/api/v3/depth"
MAX_DEPTH = 5000
MAX_REQUESTS = 5
REQUEST_INTERVAL = 2.5
TIMEOUT = 10

# Logs
LOG_FILE = "logs/collector.log"

# Kafka configuration
KAFKA_CONFIG = {
    'bootstrap.servers': KAFKA_BROKER,
    'client.id': 'lobcollector_allspot',
    'acks': 1,                                  # Leadership Confirmation (Balance Between Reliability and Speed)
    'retries': 2,                               # Minimum number of attempts
    'compression.type': 'none',                 # Uncompressed for minimal latency
    'batch.num.messages': 10,                   # Very small batch
    'linger.ms': 0,                             # Sending immediately without delay
    'queue.buffering.max.messages': 1000,       # A small queue in case of temporary problems
    'message.timeout.ms': 3000,                 # Send timeout 3 seconds
    'socket.timeout.ms': 3000,                  # Socket timeout
    'max.in.flight.requests.per.connection': 1  # Guarantee of message order
}


def setup_logging(debug_mode: bool):
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    
    # Log rotation (5 files of 10MB each)
    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=5*1024*1024,
        backupCount=2,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    logging.basicConfig(
        level=logging.DEBUG if debug_mode else logging.INFO,
        handlers=[file_handler, console_handler]
    )


# Callback for processing Kafka delivery status
def kafka_delivery_report(err, msg):
    if err is not None:
        logging.error(f"Message delivery failed: {err}")
    else:
        logging.debug(f"Message delivered to {msg.topic()} [{msg.partition()}]")


def get_exception_list():
    try:
        with open("exceptions.json", 'r') as f:
            return json.load(f).get("exceptions", [])
    except FileNotFoundError:
        logging.error("exceptions.json not found, using empty exclusion list")
        return []
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON in exceptions.json: {e}")
        return []
    except Exception as e:
        logging.error(f"Error reading exceptions.json: {e}")
        return []


class IPSessionManager:
    def __init__(self):
        self.sessions = [self.create_session(MAIN_IP), self.create_session(ADDITIONAL_IP)]
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.exceptions.RequestException))
    )
    def create_session(self, ip):
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        adapter.poolmanager.connection_pool_kw['source_address'] = (ip, 0)
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        return session


class OrderBookCollector:
    def __init__(self):
        self.session_manager = IPSessionManager()
        self.symbols = self.fetch_symbols()
        self.kafka_producer = Producer(KAFKA_CONFIG)
        logging.info(f"Loaded {len(self.symbols)} symbols from configuration")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    def fetch_symbols(self):
        try:
            EXCLUDE_SYMBOLS = get_exception_list()
            session = self.session_manager.sessions[0]
            response = session.get(EXCHANGE_INFO_URL, timeout=TIMEOUT)
            response.raise_for_status()
            data = response.json()
            symbols = [
                s['symbol'] for s in data['symbols']
                if s['quoteAsset'] == 'USDT' 
                and s['symbol'] not in EXCLUDE_SYMBOLS
                and s['status'] == 'TRADING'
            ]
            logging.debug(f"Fetched {len(symbols)} active trading symbols")
            return symbols
        except Exception as e:
            logging.error(f"Failed to fetch symbols: {e}")
            raise

    def analyze_orderbook(self, symbol, orderbook_data):
        if not orderbook_data:
            return {'symbol': symbol, 'status': 'error'}

        bids = orderbook_data.get('bids', [])
        asks = orderbook_data.get('asks', [])

        if not bids or not asks:
            return {'symbol': symbol, 'status': 'incomplete_data'}

        count_bid_levels = len(bids)
        count_ask_levels = len(asks)
        best_bid = float(bids[0][0]) if bids else 0.0
        best_ask = float(asks[0][0]) if asks else 0.0
        min_bid = float(bids[-1][0]) if bids else 0.0
        max_ask = float(asks[-1][0]) if asks else 0.0
        max_pct_from_best_bid = round((best_bid-min_bid) / best_bid * 100)
        max_pct_from_best_ask = round((max_ask-best_ask) / best_ask * 100)

        # Calculating the LOB depth
        def calculate_depth(orders, threshold, is_ask):
            total_sum = 0.0
            orders.sort(key=lambda x: float(x[0]), reverse=not is_ask)            

            for price_str, qty_str in orders:
                price, qty = float(price_str), float(qty_str)
                if is_ask:
                    if price > threshold:
                        break
                else:
                    if price < threshold:
                        break
                total_sum += price * qty
            return total_sum
       
        # Calculate depth
        bid_1 = calculate_depth(bids, best_bid * (1 - 0.01), False)
        bid_3 = calculate_depth(bids, best_bid * (1 - 0.03), False)
        bid_5 = calculate_depth(bids, best_bid * (1 - 0.05), False)
        bid_8 = calculate_depth(bids, best_bid * (1 - 0.08), False)
        bid_15 = calculate_depth(bids, best_bid * (1 - 0.15), False)
        bid_20 = calculate_depth(bids, best_bid * (1 - 0.2), False)
        bid_30 = calculate_depth(bids, best_bid * (1 - 0.3), False)
        bid_60 = calculate_depth(bids, best_bid * (1 - 0.6), False)
        ask_1 = calculate_depth(asks, best_ask * (1 + 0.01), True)
        ask_3 = calculate_depth(asks, best_ask * (1 + 0.03), True)
        ask_5 = calculate_depth(asks, best_ask * (1 + 0.05), True)
        ask_8 = calculate_depth(asks, best_ask * (1 + 0.08), True)
        ask_15 = calculate_depth(asks, best_ask * (1 + 0.15), True)
        ask_20 = calculate_depth(asks, best_ask * (1 + 0.2), True)
        ask_30 = calculate_depth(asks, best_ask * (1 + 0.3), True)
        ask_60 = calculate_depth(asks, best_ask * (1 + 0.6), True)
        total_bid_volume = sum(float(p) * float(q) for p, q in bids)
        total_ask_volume = sum(float(p) * float(q) for p, q in asks)

        return {
            'symbol': symbol,
            'best_bid': best_bid,
            'best_ask': best_ask,
            'min_bid': min_bid,
            'max_ask': max_ask,
            'depth_1pct_bid': round(bid_1),
            'depth_1pct_ask': round(ask_1),
            'depth_3pct_bid': round(bid_3),
            'depth_3pct_ask': round(ask_3),
            'depth_5pct_bid': round(bid_5),
            'depth_5pct_ask': round(ask_5),
            'depth_8pct_bid': round(bid_8),
            'depth_8pct_ask': round(ask_8),
            'depth_15pct_bid': round(bid_15),
            'depth_15pct_ask': round(ask_15),
            'depth_20pct_bid': round(bid_20),
            'depth_20pct_ask': round(ask_20),
            'depth_30pct_bid': round(bid_30),
            'depth_30pct_ask': round(ask_30),
            'depth_60pct_bid': round(bid_60),
            'depth_60pct_ask': round(ask_60),
            'total_bid_volume': round(total_bid_volume),
            'total_ask_volume': round(total_ask_volume),
            'count_bid_levels': count_bid_levels,
            'count_ask_levels': count_ask_levels,
            'max_pct_from_best_bid': max_pct_from_best_bid,
            'max_pct_from_best_ask': max_pct_from_best_ask,
            'event_time': int(time.time()),
            'status': 'ok'
        }

    def process_batch(self, batch, iteration_id):
        success_count = 0
        failed_symbols = []

        with ThreadPoolExecutor(max_workers=MAX_REQUESTS) as executor:
            futures = [
                executor.submit(self.process_symbol, symbol, idx, iteration_id)
                for idx, symbol in enumerate(batch)
            ]

            for future in futures:
                result = future.result()
                if result:
                    if result.get('status') == 'ok':
                        success_count += 1
                        self.send_to_kafka(result)
                    else:
                        failed_symbols.append(result['symbol'])

        # Logging batch statistics
        batch_stats = {
            'batch_size': len(batch),
            'success': success_count,
            'failed': len(batch) - success_count,
            'failed_symbols': failed_symbols
        }
        logging.debug(f"Batch processed: {json.dumps(batch_stats)}")

        return success_count, failed_symbols

    def process_symbol(self, symbol, idx, iteration_id):
        try:
            session = self.session_manager.sessions[idx % len(self.session_manager.sessions)]
            response = session.get(
                DEPTH_URL, 
                params={'symbol': symbol, 'limit': MAX_DEPTH}, 
                timeout=TIMEOUT
            )
            response.raise_for_status()
            result = self.analyze_orderbook(symbol, response.json())
            result['iteration_id'] = iteration_id
            return result
        except Exception as e:
            logging.error(f"Failed to process {symbol}: {e}")
            return {'symbol': symbol, 'status': 'error', 'error': str(e)}

    @staticmethod
    def check_kafka_connection():
        """Check Kafka broker availability without sending test messages"""
        try:
            producer = Producer(KAFKA_CONFIG)
            # We simply create a producer without sending a message and check the topic metadata
            metadata = producer.list_topics(timeout=5)
            if KAFKA_TOPIC in metadata.topics:
                logging.info("Kafka connection: OK, topic exists")
            else:
                logging.warning(f"Kafka topic {KAFKA_TOPIC} not found")
            producer.flush(1)
            return True
        except Exception as e:
            logging.error(f"Kafka connection failed: {e}")
            return False

    def send_to_kafka(self, data):
        try:
            json_data = json.dumps(data).encode('utf-8')
            self.kafka_producer.produce(
                topic=KAFKA_TOPIC,
                value=json_data,
                callback=kafka_delivery_report
            )
            self.kafka_producer.poll(0)
        except BufferError as e:
            logging.warning(f"Kafka producer queue full: {e}")
            # Let's wait and try again.
            self.kafka_producer.poll(1)
            self.kafka_producer.produce(
                topic=KAFKA_TOPIC,
                value=json_data,
                callback=kafka_delivery_report
            )
        except Exception as e:
            logging.error(f"Kafka send failed: {e}")

    def run(self):
        logging.info("Starting collector service with Kafka integration")
        self.check_kafka_connection()

        while True:
            iteration_id = str(uuid.uuid4())
            start_time = time.perf_counter()
            total_success = 0
            total_failed = 0
            all_failed_symbols = []
            self.symbols = self.fetch_symbols()
            time.sleep(REQUEST_INTERVAL)

            try:
                for i in range(0, len(self.symbols), MAX_REQUESTS):
                    batch = self.symbols[i:i+MAX_REQUESTS]
                    success_count, failed_symbols = self.process_batch(batch, iteration_id)
                    total_success += success_count
                    total_failed += len(failed_symbols)
                    all_failed_symbols.extend(failed_symbols)
                    time.sleep(REQUEST_INTERVAL)

            except KeyboardInterrupt:
                logging.info("Shutting down...")
                # Finalization before exit
                self.kafka_producer.flush(30)
                break
            except Exception as e:
                logging.error(f"Critical error: {e}")
                time.sleep(60)
            finally:
                # Producer's finalization
                self.kafka_producer.flush(10)

                # Logging iteration results
                duration = time.perf_counter() - start_time
                iteration_stats = {
                    'iteration_id': iteration_id,
                    'duration_sec': round(duration, 2),
                    'total_symbols': len(self.symbols),
                    'success': total_success,
                    'failed': total_failed,
                    'success_rate': round(total_success / len(self.symbols) * 100, 2),
                    'failed_symbols': all_failed_symbols
                }
                logging.info(f"Iteration completed: {json.dumps(iteration_stats)}")

                # Delay before next iteration
                time.sleep(1)


if __name__ == '__main__':
    setup_logging(debug_mode=False)
    collector = OrderBookCollector()
    collector.run()
