"""
screener/universe.py
--------------------
Manages the universe of symbols to be screened.
"""

import logging
from dataclasses import dataclass, field
import pandas as pd
from typing import Dict, List, Self

logger = logging.getLogger(__name__)

@dataclass
class Universe:
    name: str
    symbols: List[str]
    description: str = ""
    
    def __post_init__(self):
        if not self.symbols:
            logger.warning(f"Universe '{self.name}' initialized with empty symbols list.")
            # We don't raise an error here to allow empty universes, but it's warned.
            

    def validate(self, data_dict: Dict[str, pd.DataFrame]) -> List[str]:
        """Returns list of symbols that are in `symbols` but missing from `data_dict`."""
        return [sym for sym in self.symbols if sym not in data_dict]
        
    def filter(self, data_dict: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
        """Returns only symbols present in both universe and data_dict."""
        return {sym: df for sym, df in data_dict.items() if sym in self.symbols}
        
    @classmethod
    def custom(cls, symbols: List[str]) -> Self:
        return cls(name="Custom", symbols=symbols)
        
    @classmethod
    def from_list(cls, name: str, symbols: List[str]) -> Self:
        return cls(name=name, symbols=symbols)
