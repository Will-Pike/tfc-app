import os
import redis
from rq import Worker, Queue, SimpleWorker
from rq.timeouts import TimerDeathPenalty
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

listen = [os.getenv('RQ_QUEUE', 'default')]

redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
conn = redis.from_url(redis_url)

if __name__ == '__main__':
    logger.info("Starting RQ worker...")
    worker_cls = SimpleWorker if os.name == 'nt' else Worker
    worker = worker_cls(listen, connection=conn)
    if os.name == 'nt':
        worker.death_penalty_class = TimerDeathPenalty
    worker.work(logging_level='INFO')