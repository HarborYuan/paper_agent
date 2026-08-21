from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from src.config import settings
from src.logger import logger
from src.worker import run_worker

JOB_ID = "daily_auto_update_job"


class SchedulerService:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()

    async def start(self):
        """Start the scheduler and apply the current settings (no-op if auto-update is disabled)."""
        await self.reload()

    async def reload(self):
        """
        (Re)apply ENABLE_AUTO_UPDATE / AUTO_UPDATE_TIME from the live settings object.
        Safe to call at any time — used by the Settings page so schedule changes need no restart.
        """
        try:
            if not settings.ENABLE_AUTO_UPDATE:
                if self.scheduler.running and self.scheduler.get_job(JOB_ID):
                    self.scheduler.remove_job(JOB_ID)
                    await logger.log("Scheduler: daily auto-update disabled.")
                return

            hour, minute = map(int, str(settings.AUTO_UPDATE_TIME).split(":"))
            trigger = CronTrigger(hour=hour, minute=minute, timezone="UTC")
            self.scheduler.add_job(run_worker, trigger=trigger, id=JOB_ID, replace_existing=True)
            if not self.scheduler.running:
                self.scheduler.start()
            await logger.log(f"Scheduler: daily auto-update at {hour:02d}:{minute:02d} UTC.")
        except ValueError:
            await logger.log(f"Invalid AUTO_UPDATE_TIME format: {settings.AUTO_UPDATE_TIME}. Scheduler not updated.")
        except Exception as e:
            await logger.log(f"Failed to (re)start scheduler: {e}")

    def next_run_time(self):
        if not self.scheduler.running:
            return None
        job = self.scheduler.get_job(JOB_ID)
        return job.next_run_time if job else None

    def shutdown(self):
        if self.scheduler.running:
            self.scheduler.shutdown()
