from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from src.config import settings
from src.logger import logger
from src.worker import run_worker

class SchedulerService:
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        
    def start(self):
        if not settings.ENABLE_AUTO_UPDATE:
            return

        try:
            # Parse time string "HH:MM"
            hour, minute = map(int, settings.AUTO_UPDATE_TIME.split(":"))
            
            trigger = CronTrigger(
                hour=hour, 
                minute=minute, 
                timezone="UTC" # Container timezone is likely UTC or we want UTC
            )
            
            self.scheduler.add_job(
                run_worker,
                trigger=trigger,
                id="daily_auto_update_job",
                replace_existing=True
            )
            
            self.scheduler.start()
            print(f"Scheduler started. Auto-update scheduled daily at {settings.AUTO_UPDATE_TIME} UTC.")
            
        except ValueError:
            print(f"Invalid AUTO_UPDATE_TIME format: {settings.AUTO_UPDATE_TIME}. Scheduler not started.")
        except Exception as e:
            print(f"Failed to start scheduler: {e}")

    def shutdown(self):
        if self.scheduler.running:
            self.scheduler.shutdown()
