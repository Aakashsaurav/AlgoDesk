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

from screener.base import ScanSummary, ExportFormat


class OutputFormatter:
    """Formats scan results to CSV or JSON."""
    
    def format_csv(self, summary: ScanSummary, filepath: Union[str, Path]) -> Path:
        """Saves summary.results as CSV using .to_row()."""
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        rows = [r.to_row() for r in summary.results]
        if not rows:
            pd.DataFrame().to_csv(filepath, index=False)
            return filepath

        df = pd.DataFrame(rows)
        df.to_csv(filepath, index=False)
        return filepath

    def format_json(self, summary: ScanSummary, filepath: Union[str, Path]) -> Path:
        """Saves summary.to_dict() as JSON."""
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(summary.to_dict(), f, indent=4)
        return filepath

    def to_console(self, summary: ScanSummary) -> None:
        """Prints a tabular summary of the scan results to the console."""
        print(f"\n--- Scan Summary: {summary.scan_name} ---")
        print(f"Mode: {summary.mode.value} | Date: {summary.scan_date}")
        print(f"Scanned: {summary.symbols_scanned} | Passed: {summary.symbols_passed} | Failed: {summary.symbols_failed}")
        print("-" * 50)
        for r in summary.results:
            print(f"[{r.symbol}] Score: {r.score:.2f} | Close: {r.close:.2f} | Dir: {r.signal_direction.name}")

    def historical_to_csv(self, summary: ScanSummary, filepath: Union[str, Path]) -> Path:
        """Saves historical scan results as CSV."""
        return self.format_csv(summary, filepath)


class ScreenerHistory:
    """Manages history of screener runs."""
    
    def __init__(self, history_dir: Union[str, Path]):
        self.history_dir = Path(history_dir)
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self.formatter = OutputFormatter()
        
    def save_scan(self, summary: ScanSummary, export_format: ExportFormat = ExportFormat.BOTH) -> list[Path]:
        """Saves results based on export_format."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name = summary.scan_name.replace(" ", "_")
        base_name = f"scan_{name}_{timestamp}"
        
        paths = []
        if export_format in (ExportFormat.CSV, ExportFormat.BOTH):
            csv_path = self.history_dir / f"{base_name}.csv"
            paths.append(self.formatter.format_csv(summary, csv_path))
            
        if export_format in (ExportFormat.JSON, ExportFormat.BOTH):
            json_path = self.history_dir / f"{base_name}.json"
            paths.append(self.formatter.format_json(summary, json_path))
            
        return paths
