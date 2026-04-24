import logging
import time

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from paperbreakfast.config import AppConfig
from paperbreakfast.pipeline import Pipeline

logger = logging.getLogger(__name__)


class Scheduler:

    def __init__(self, config: AppConfig):
        self._config = config
        self._pipeline = Pipeline(config)
        self._scheduler = BackgroundScheduler(timezone="UTC")

    def start(self):
        self._scheduler.add_job(
            self._pipeline.run_full,
            trigger=CronTrigger(hour=self._config.email.send_hour, minute=0, timezone="UTC"),
            id="daily_run",
            name="Fetch + evaluate + digest",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

        self._scheduler.start()
        logger.info(
            f"Scheduler running — daily at {self._config.email.send_hour:02d}:00 UTC"
        )

        try:
            while True:
                time.sleep(60)
        except (KeyboardInterrupt, SystemExit):
            logger.info("Shutting down scheduler...")
            self._scheduler.shutdown(wait=False)
