"""
screener/output.py
------------------
Output formatting and history management for screener results.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Union

import pandas as pd

from screener.base import ScanSummary


class OutputFormatter:
    """Formats scan results to CSV or JSON."""
    
    def format_csv(self, summary: ScanSummary, filepath: Union[str, Path]) -> None:
        """Saves summary.results as CSV using .to_row()."""
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        rows = [r.to_row() for r in summary.results]
        if not rows:
            pd.DataFrame().to_csv(filepath, index=False)
            return

        df = pd.DataFrame(rows)
        df.to_csv(filepath, index=False)

    def format_json(self, summary: ScanSummary, filepath: Union[str, Path]) -> None:
        """Saves summary.to_dict() as JSON."""
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(summary.to_dict(), f, indent=4)


class ScreenerHistory:
    """Manages history of screener runs."""
    
    def __init__(self, history_dir: Union[str, Path]):
        self.history_dir = Path(history_dir)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.formatter = OutputFormatter()
        
    def save_scan(self, summary: ScanSummary) -> None:
        """Saves both CSV and JSON to the history directory with timestamped filenames."""
        # Note: In production you might want to use the scan_date or a consistent timestamp.
        # But per the requirement: `scan_{name}_{timestamp}.json`
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = summary.scan_name.replace(" ", "_")
        
        base_name = f"scan_{name}_{timestamp}"
        csv_path = self.history_dir / f"{base_name}.csv"
        json_path = self.history_dir / f"{base_name}.json"
        
        self.formatter.format_csv(summary, csv_path)
        self.formatter.format_json(summary, json_path)
