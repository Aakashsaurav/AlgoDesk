"""
indicators/custom.py
--------------------
Loader and manager for user-defined custom indicators.
Supports storing custom indicators in an SQLite database and loading them into the engine.
"""

import sqlite3
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, List, Optional

import pandas as pd
from indicators.engine import IndicatorEngine
from indicators.expression import ExpressionParser
from config import config

logger = logging.getLogger(__name__)


@dataclass
class CustomIndicatorSpec:
    """Specification for a user-defined custom indicator."""
    name: str
    category: str
    description: str
    type: str  # 'expression' or 'python'
    code: str
    inputs: List[str]
    outputs: List[str]
    parameters: Dict[str, Any]


class CustomIndicatorLoader:
    """
    Manages persistence of custom indicators to SQLite and loads them into
    the IndicatorEngine at runtime.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or config.DATA_DIR / "custom_indicators.db"
        self._init_db()

    def _init_db(self) -> None:
        """Initialize the SQLite database schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS custom_indicators (
                    name TEXT PRIMARY KEY,
                    category TEXT,
                    description TEXT,
                    type TEXT,
                    code TEXT,
                    inputs TEXT,
                    outputs TEXT,
                    parameters TEXT
                )
            ''')
            conn.commit()

    def save(self, spec: CustomIndicatorSpec) -> None:
        """Save or update a custom indicator in the database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT OR REPLACE INTO custom_indicators 
                (name, category, description, type, code, inputs, outputs, parameters)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                spec.name,
                spec.category,
                spec.description,
                spec.type,
                spec.code,
                json.dumps(spec.inputs),
                json.dumps(spec.outputs),
                json.dumps(spec.parameters)
            ))
            conn.commit()
        logger.info("Saved custom indicator '%s' to %s", spec.name, self.db_path)

    def delete(self, name: str) -> None:
        """Delete a custom indicator from the database."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('DELETE FROM custom_indicators WHERE name = ?', (name,))
            conn.commit()
        logger.info("Deleted custom indicator '%s'", name)

    def list_all(self) -> List[CustomIndicatorSpec]:
        """List all custom indicators stored in the database."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('SELECT * FROM custom_indicators')
            rows = cursor.fetchall()
        
        specs = []
        for row in rows:
            specs.append(CustomIndicatorSpec(
                name=row[0],
                category=row[1],
                description=row[2],
                type=row[3],
                code=row[4],
                inputs=json.loads(row[5]),
                outputs=json.loads(row[6]),
                parameters=json.loads(row[7])
            ))
        return specs

    def load_into_engine(self, engine: IndicatorEngine) -> None:
        """Load all custom indicators from the database into the given engine."""
        specs = self.list_all()
        for spec in specs:
            if spec.type == 'expression':
                self._register_expression(engine, spec)
            elif spec.type == 'python':
                self._register_python(engine, spec)
            else:
                logger.warning("Unknown custom indicator type '%s' for '%s'", spec.type, spec.name)
        logger.info("Loaded %d custom indicators into engine.", len(specs))

    def _register_expression(self, engine: IndicatorEngine, spec: CustomIndicatorSpec) -> None:
        """Wrap an AST expression as a callable indicator function."""
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Map positional args to inputs
            data = {}
            if len(args) == 1 and isinstance(args[0], dict):
                data.update(args[0])
            elif len(args) == 1 and isinstance(args[0], pd.DataFrame):
                data.update({col: args[0][col] for col in args[0].columns})
            else:
                for i, val in enumerate(args):
                    if i < len(spec.inputs):
                        data[spec.inputs[i]] = val
            
            # Use kwargs for any overrides (mostly data fields)
            data.update({k: v for k, v in kwargs.items() if k in spec.inputs})
            
            # Combine params from defaults + kwargs
            params = spec.parameters.copy()
            params.update({k: v for k, v in kwargs.items() if k not in spec.inputs})
            
            # Expressions might need params as 'data' variables if referenced
            data.update(params)

            parser = ExpressionParser(engine, data)
            return parser.evaluate(spec.code)
            
        wrapper.__name__ = spec.name
        wrapper.__doc__ = spec.description
        engine.register(spec.name, wrapper)

    def _register_python(self, engine: IndicatorEngine, spec: CustomIndicatorSpec) -> None:
        """
        Restricted Python execution environment for indicators.
        Only allows pandas, numpy, and basic math operations.
        """
        allowed_globals = {
            "pd": pd,
            "np": __import__("numpy"),
            "__builtins__": {
                "abs": abs, "min": min, "max": max, "sum": sum, 
                "round": round, "len": len, "range": range,
                "bool": bool, "int": int, "float": float, "str": str,
                "Exception": Exception, "ValueError": ValueError
            }
        }
        
        local_vars = {}
        try:
            # Code should define a function with the same name as spec.name
            exec(spec.code, allowed_globals, local_vars)
            func = local_vars.get(spec.name)
            
            if not callable(func):
                logger.error("Python indicator '%s' must define a function named '%s'", spec.name, spec.name)
                return
                
            engine.register(spec.name, func)
        except Exception as e:
            logger.error("Failed to load python indicator '%s': %s", spec.name, e)

__all__ = ["CustomIndicatorSpec", "CustomIndicatorLoader"]
