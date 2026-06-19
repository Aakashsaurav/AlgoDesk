import sqlite3
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict
from pathlib import Path

@dataclass
class ScheduledJob:
    job_id: str
    name: str
    job_type: str
    cron_expr: str
    params: Dict = field(default_factory=dict)
    enabled: bool = True
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    last_status: str = "PENDING"

class JobStore:
    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = Path("data/sqlite/jobs.db")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    name TEXT,
                    job_type TEXT,
                    cron_expr TEXT,
                    params TEXT,
                    enabled INTEGER,
                    last_run TEXT,
                    next_run TEXT,
                    last_status TEXT
                )
            ''')
            
    def _parse_time(self, ts: Optional[str]) -> Optional[datetime]:
        if not ts:
            return None
        try:
            return datetime.fromisoformat(ts)
        except Exception:
            return None

    def save(self, job: ScheduledJob):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO jobs 
                (job_id, name, job_type, cron_expr, params, enabled, last_run, next_run, last_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                job.job_id,
                job.name,
                job.job_type,
                job.cron_expr,
                json.dumps(job.params),
                1 if job.enabled else 0,
                job.last_run.isoformat() if job.last_run else None,
                job.next_run.isoformat() if job.next_run else None,
                job.last_status
            ))

    def load_all(self) -> List[ScheduledJob]:
        jobs = []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute("SELECT * FROM jobs")
            for row in cursor:
                jobs.append(ScheduledJob(
                    job_id=row['job_id'],
                    name=row['name'],
                    job_type=row['job_type'],
                    cron_expr=row['cron_expr'],
                    params=json.loads(row['params']),
                    enabled=bool(row['enabled']),
                    last_run=self._parse_time(row['last_run']),
                    next_run=self._parse_time(row['next_run']),
                    last_status=row['last_status']
                ))
        return jobs

    def delete(self, job_id: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))

    def update_last_run(self, job_id: str, timestamp: datetime, status: str, result_summary: str = ""):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                UPDATE jobs SET last_run = ?, last_status = ? WHERE job_id = ?
            ''', (timestamp.isoformat(), status, job_id))
            
    def update_next_run(self, job_id: str, timestamp: Optional[datetime]):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                UPDATE jobs SET next_run = ? WHERE job_id = ?
            ''', (timestamp.isoformat() if timestamp else None, job_id))
