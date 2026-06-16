from __future__ import annotations

import importlib
import inspect
import json
import logging
import sys
import threading
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, get_args, get_origin
import pandas as pd

from strategies.categories import StrategyCategory
from strategies.base import BaseStrategy
from strategies.validation import coerce_params, normalize_param_schema, validate_param_schema
from strategies.contracts import ParamSpec

logger = logging.getLogger(__name__)

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
_REGISTRY_CACHE: Optional[Dict[str, dict]] = None
_REGISTRY_LOCK = threading.RLock()
_DIAGNOSTICS: Dict[str, Any] = {
    "discovered_count": 0,
    "skipped_files": [],
    "import_errors": {},
    "invalid_schemas": {},
}

class StrategyRegistryError(Exception):
    """Raised when there is a schema or load error in the strategy registry."""

def get_registry_diagnostics() -> Dict[str, Any]:
    """Return diagnostic information from the last registry build."""
    with _REGISTRY_LOCK:
        return dict(_DIAGNOSTICS)

def get_strategy_registry(force_refresh: bool = False) -> Dict[str, dict]:
    """Return the cached strategy registry."""
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is None or force_refresh:
        with _REGISTRY_LOCK:
            if _REGISTRY_CACHE is None or force_refresh:
                _REGISTRY_CACHE = _build_registry()
    return dict(_REGISTRY_CACHE)

def get_strategy_schema(class_name: str) -> dict:
    """Return one strategy schema by class name."""
    registry = get_strategy_registry()
    if class_name not in registry:
        raise KeyError(f"Strategy '{class_name}' not found. Available: {sorted(registry.keys())}")
    return dict(registry[class_name])

def list_strategies(compact: bool = False, force_refresh: bool = False) -> List[dict]:
    """Return registry values sorted by display name."""
    registry = get_strategy_registry(force_refresh=force_refresh)
    lst = sorted(registry.values(), key=lambda item: item["display_name"])
    if compact:
        return [
            {
                "class_name": s["class_name"],
                "display_name": s["display_name"],
                "category": s["category"],
            } for s in lst
        ]
    return lst

def list_by_category(category: str) -> List[dict]:
    """Return strategies belonging to a specific category."""
    registry = get_strategy_registry()
    return [s for s in registry.values() if s["category"] == category]

def get_strategy_class(class_name: str) -> Type[BaseStrategy]:
    """Load and return the strategy class directly."""
    schema = get_strategy_schema(class_name)
    module = importlib.import_module(schema["module_path"])
    return getattr(module, class_name)

def load_strategy(class_name: str, params: Optional[Dict[str, Any]] = None) -> BaseStrategy:
    """Instantiate a strategy from registry metadata."""
    schema = get_strategy_schema(class_name)
    cls = get_strategy_class(class_name)
    
    try:
        param_specs = [ParamSpec(**p) for p in schema["params"]]
        coerced = coerce_params(params or {}, param_specs, allow_extra_params=True)
    except Exception as exc:
        raise StrategyRegistryError(f"Parameter coercion failed for {class_name}: {exc}") from exc

    try:
        strategy = cls(**coerced)
    except Exception as exc:
        raise StrategyRegistryError(f"Instantiation failed for {class_name}: {exc}") from exc

    if not isinstance(strategy, BaseStrategy):
        raise TypeError(f"{class_name} did not produce a BaseStrategy instance.")
    return strategy

def validate_strategy_input(strategy: BaseStrategy, df: pd.DataFrame) -> None:
    """Validate that the input DataFrame contains all required columns for the strategy."""
    req_cols = strategy.required_input_columns()
    missing = [c for c in req_cols if c not in df.columns]
    if missing:
        raise ValueError(
            f"Strategy '{strategy.__class__.__name__}' missing required columns: {missing}. "
            f"Available: {list(df.columns)}"
        )

def _build_registry() -> Dict[str, dict]:
    registry: Dict[str, dict] = {}
    
    global _DIAGNOSTICS
    _DIAGNOSTICS = {
        "discovered_count": 0,
        "skipped_files": [],
        "import_errors": {},
        "invalid_schemas": {},
    }

    for py_file in sorted(_HERE.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        if py_file.name in {"__init__.py", "registry.py", "base.py", "contracts.py", "validation.py", "categories.py"}:
            _DIAGNOSTICS["skipped_files"].append(str(py_file))
            continue

        module_path = _file_to_module_path(py_file)
        if module_path is None:
            _DIAGNOSTICS["skipped_files"].append(str(py_file))
            continue

        module = _safe_import(module_path)
        if module is None:
            continue

        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj is BaseStrategy or not issubclass(obj, BaseStrategy):
                continue
            if obj.__module__ != module_path:
                continue
            if inspect.isabstract(obj):
                continue

            schema = _extract_schema(obj, module_path)
            if not schema:
                continue

            class_name = schema["class_name"]
            registry[class_name] = schema

    _DIAGNOSTICS["discovered_count"] = len(registry)
    logger.info("Strategy registry discovered %s strategies", len(registry))
    return registry

def _file_to_module_path(py_file: Path) -> Optional[str]:
    try:
        return ".".join(py_file.relative_to(_PROJECT_ROOT).with_suffix("").parts)
    except ValueError:
        return None

def _safe_import(module_path: str):
    root = str(_PROJECT_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        return importlib.import_module(module_path)
    except Exception as exc:
        _DIAGNOSTICS["import_errors"][module_path] = str(exc)
        logger.debug("Cannot import %s: %s", module_path, exc)
        return None

def _extract_schema(cls: Type[BaseStrategy], module_path: str) -> Optional[dict]:
    try:
        class_name = cls.__name__
        display_name = class_name
        description = getattr(cls, "DESCRIPTION", "") or inspect.cleandoc(cls.__doc__ or "")
        
        cat_val = getattr(cls, "CATEGORY", StrategyCategory.CUSTOM.value)
        try:
            category = StrategyCategory(cat_val).value
        except ValueError:
            logger.warning(f"Unknown category '{cat_val}' in {class_name}, defaulting to CUSTOM.")
            category = StrategyCategory.CUSTOM.value

        mode = getattr(cls, "MODE", "VECTORIZED")
        if not isinstance(mode, str):
            mode = mode.value
            
        scope = getattr(cls, "SYMBOL_SCOPE", "SINGLE_SYMBOL")
        if not isinstance(scope, str):
            scope = scope.value

        req_cols = ["open", "high", "low", "close", "volume"]
        extra = getattr(cls, "REQUIRED_EXTRA_COLUMNS", ())
        if extra:
            req_cols.extend(list(extra))

        params = _extract_param_schema(cls)

        return {
            "class_name": class_name,
            "display_name": display_name,
            "module_path": module_path,
            "description": description,
            "category": category,
            "mode": mode,
            "scope": scope,
            "required_columns": req_cols,
            "params": params,
        }
    except Exception as exc:
        _DIAGNOSTICS["invalid_schemas"][cls.__name__] = str(exc)
        logger.debug("Cannot extract schema from %s: %s", cls.__name__, exc)
        return None

def _extract_param_schema(cls: Type[BaseStrategy]) -> List[dict]:
    explicit_schema = getattr(cls, "PARAM_SCHEMA", None)
    if explicit_schema:
        # validate using validation.py
        normalized = normalize_param_schema(explicit_schema)
        validate_param_schema(normalized)
        # convert back to dict for serialization
        return [asdict(p) for p in normalized]

    # Legacy inference
    signature = inspect.signature(cls.__init__)
    params: List[dict] = []
    for name, param in signature.parameters.items():
        if name in {"self", "args", "kwargs", "name", "description", "params"}:
            continue

        default = None if param.default is inspect.Parameter.empty else param.default
        annotation = None if param.annotation is inspect.Parameter.empty else param.annotation
        type_str = _annotation_to_type(annotation, default)
        min_val, max_val, step = _infer_bounds(name, default, type_str)

        schema = {
            "name": name,
            "type": type_str,
            "default": default,
            "min": min_val,
            "max": max_val,
            "step": step,
            "label": name,
            "description": "",
            "unit": "",
            "options": None,
            "optimize": True,
            "required": False,
            "runtime_only": False,
        }
        params.append(schema)
    return params

def _annotation_to_type(annotation: Any, default: Any) -> str:
    origin = get_origin(annotation)
    if origin is not None:
        args = [arg for arg in get_args(annotation) if arg is not type(None)]
        if len(args) == 1:
            annotation = args[0]

    if annotation is bool or isinstance(default, bool):
        return "bool"
    if annotation is int or (isinstance(default, int) and not isinstance(default, bool)):
        return "int"
    if annotation is float or isinstance(default, float):
        return "float"
    if annotation is str or isinstance(default, str):
        return "str"
    return "any"

def _infer_bounds(name: str, default: Any, type_str: str):
    if type_str not in {"int", "float"}:
        return None, None, None

    lowered = name.lower()
    if any(token in lowered for token in ("period", "window", "lookback", "bars")):
        return 1, 500, 1
    if any(token in lowered for token in ("level", "threshold", "oversold", "overbought")):
        return 0, 100, 1
    if any(token in lowered for token in ("mult", "multiplier", "std", "sigma")):
        return 0.1, 10.0, 0.1
    if isinstance(default, int):
        return 1, 500, 1
    if isinstance(default, float):
        return 0.0, 100.0, 0.1
    return None, None, None

def format_strategy_table(strategies: List[dict]) -> str:
    """Format a list of strategy dictionaries into an ASCII table."""
    if not strategies:
        return "No strategies found."
    
    headers = ["Class Name", "Display Name", "Category", "Mode", "Scope", "Params", "Required Columns"]
    rows = []
    for s in strategies:
        rows.append([
            s.get("class_name", ""),
            s.get("display_name", ""),
            s.get("category", ""),
            s.get("mode", ""),
            s.get("scope", ""),
            str(len(s.get("params", []))),
            ", ".join(s.get("required_columns", [])),
        ])
        
    col_widths = [max(len(str(item)) for item in col) for col in zip(headers, *rows)]
    
    def format_row(row):
        return " | ".join(str(item).ljust(width) for item, width in zip(row, col_widths))
        
    separator = "-+-".join("-" * width for width in col_widths)
    
    lines = [
        format_row(headers),
        separator
    ]
    for row in rows:
        lines.append(format_row(row))
        
    return "\n".join(lines)


def strategy_registry_to_json() -> str:
    """Return the entire registry as a JSON string."""
    registry = get_strategy_registry()
    return json.dumps(registry, indent=2)


def generate_strategy_docs(output_path: Path) -> Path:
    """Generate a markdown file containing documentation for all discovered strategies."""
    registry = get_strategy_registry()
    strategies = sorted(registry.values(), key=lambda s: s["category"] + s["display_name"])
    
    lines = ["# Strategy Reference\n"]
    
    current_cat = None
    for s in strategies:
        cat = s.get("category", "Unknown")
        if cat != current_cat:
            lines.append(f"## Category: {cat}\n")
            current_cat = cat
            
        lines.append(f"### {s.get('display_name', s.get('class_name'))}")
        lines.append(f"**Class:** `{s.get('class_name')}`  ")
        lines.append(f"**Mode:** `{s.get('mode')}`  ")
        lines.append(f"**Scope:** `{s.get('scope')}`  \n")
        
        desc = s.get("description", "")
        if desc:
            lines.append(f"{desc}\n")
            
        req_cols = s.get("required_columns", [])
        if req_cols:
            lines.append("**Required Input Columns:**")
            lines.append(f"`{', '.join(req_cols)}`\n")
            
        params = s.get("params", [])
        if params:
            lines.append("**Parameters:**\n")
            lines.append("| Name | Type | Default | Min | Max | Step | Description |")
            lines.append("|---|---|---|---|---|---|---|")
            for p in params:
                desc_text = p.get("description", "")
                if p.get("unit"):
                    desc_text += f" ({p.get('unit')})"
                row = [
                    f"`{p.get('name')}`",
                    f"`{p.get('type')}`",
                    str(p.get("default", "")),
                    str(p.get("min", "")),
                    str(p.get("max", "")),
                    str(p.get("step", "")),
                    desc_text
                ]
                lines.append("| " + " | ".join(row) + " |")
            lines.append("\n")
            
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


__all__ = [
    "StrategyRegistryError",
    "get_strategy_registry",
    "get_strategy_schema",
    "get_registry_diagnostics",
    "list_strategies",
    "list_by_category",
    "load_strategy",
    "get_strategy_class",
    "validate_strategy_input",
    "format_strategy_table",
    "strategy_registry_to_json",
    "generate_strategy_docs",
]
