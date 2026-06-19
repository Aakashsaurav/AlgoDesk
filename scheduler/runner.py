import logging
from datetime import datetime
from typing import Callable, Any, List
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.base import JobLookupError
from scheduler.job_store import JobStore, ScheduledJob
from config import IST

logger = logging.getLogger(__name__)

class AlgoDeskScheduler:
    def __init__(self, job_store: JobStore):
        self.job_store = job_store
        self._scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
        self._registry = {} # type: dict[str, Callable]

    def register_job_func(self, job_type: str, func: Callable):
        self._registry[job_type] = func

    def start(self):
        if not self._scheduler.running:
            self._scheduler.start()
            
            jobs = self.job_store.load_all()
            for job in jobs:
                if job.enabled and job.job_type in self._registry:
                    self._schedule_internal(job)
            logger.info("AlgoDeskScheduler started.")
            
    def stop(self):
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("AlgoDeskScheduler stopped.")
            
    def _schedule_internal(self, job: ScheduledJob):
        func = self._registry.get(job.job_type)
        if not func:
            logger.error(f"Cannot schedule job {job.job_id}: unknown type {job.job_type}")
            return
            
        trigger = CronTrigger.from_crontab(job.cron_expr)
        
        def wrapper(**kwargs):
            try:
                func(**kwargs)
                self.job_store.update_last_run(job.job_id, datetime.now(tz=IST), "SUCCESS")
            except Exception as e:
                logger.error(f"Job {job.job_id} failed: {e}")
                self.job_store.update_last_run(job.job_id, datetime.now(tz=IST), "FAILED", str(e))
                
        try:
            self._scheduler.add_job(
                wrapper, 
                trigger=trigger, 
                id=job.job_id, 
                replace_existing=True,
                kwargs=job.params
            )
        except Exception as e:
            logger.error(f"Failed to add job to APScheduler: {e}")

    def add_job(self, job_id: str, name: str, job_type: str, cron_expr: str, **params) -> str:
        job = ScheduledJob(
            job_id=job_id,
            name=name,
            job_type=job_type,
            cron_expr=cron_expr,
            params=params,
            enabled=True
        )
        self.job_store.save(job)
        if self._scheduler.running:
            self._schedule_internal(job)
        return job_id
        
    def remove_job(self, job_id: str) -> bool:
        self.job_store.delete(job_id)
        try:
            self._scheduler.remove_job(job_id)
            return True
        except JobLookupError:
            return False
            
    def list_jobs(self) -> List[ScheduledJob]:
        return self.job_store.load_all()
        
    def pause_job(self, job_id: str):
        try:
            self._scheduler.pause_job(job_id)
        except JobLookupError:
            pass
        jobs = self.job_store.load_all()
        for j in jobs:
            if j.job_id == job_id:
                j.enabled = False
                self.job_store.save(j)
            
    def resume_job(self, job_id: str):
        try:
            self._scheduler.resume_job(job_id)
        except JobLookupError:
            pass
        jobs = self.job_store.load_all()
        for j in jobs:
            if j.job_id == job_id:
                j.enabled = True
                self.job_store.save(j)
            
    def run_now(self, job_id: str):
        jobs = self.job_store.load_all()
        job = next((j for j in jobs if j.job_id == job_id), None)
        if not job:
            raise ValueError(f"Job {job_id} not found")
            
        func = self._registry.get(job.job_type)
        if not func:
            raise ValueError(f"Unknown job type {job.job_type}")
            
        try:
            func(**job.params)
            self.job_store.update_last_run(job_id, datetime.now(tz=IST), "SUCCESS")
        except Exception as e:
            self.job_store.update_last_run(job_id, datetime.now(tz=IST), "FAILED", str(e))
            raise
            
    @property
    def is_running(self) -> bool:
        return self._scheduler.running
