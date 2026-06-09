# Use cases:
# - Discover all strategy classes for the dashboard and API.
# - Instantiate strategies from validated parameter dictionaries.
# - Expose parameter schemas for strategy builders and optimization tools.
"""
strategies/registry.py
-----------------------
Strategy discovery and loading utilities.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, get_args, get_origin

from strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent
_REGISTRY_CACHE: Optional[Dict[str, dict]] = None


def get_strategy_registry(force_refresh: bool = False) -> Dict[str, dict]:
    """Return the cached strategy registry."""
    global _REGISTRY_CACHE
    if _REGISTRY_CACHE is None or force_refresh:
        _REGISTRY_CACHE = _build_registry()
    return dict(_REGISTRY_CACHE)


def get_strategy_schema(class_name: str) -> dict:
    """Return one strategy schema by class name."""
    registry = get_strategy_registry()
    if class_name not in registry:
        raise KeyError(
            f"Strategy '{class_name}' not found. Available: {sorted(registry.keys())}"
        )
    return dict(registry[class_name])


def list_strategies(force_refresh: bool = False) -> List[dict]:
    """Return registry values sorted by display name."""
    registry = get_strategy_registry(force_refresh=force_refresh)
    return sorted(registry.values(), key=lambda item: item["display_name"])


def load_strategy(class_name: str, params: Optional[Dict[str, Any]] = None) -> BaseStrategy:
    """Instantiate a strategy from registry metadata."""
    schema = get_strategy_schema(class_name)
    module = importlib.import_module(schema["module_path"])
    cls = getattr(module, class_name)
    coerced = _coerce_params(params or {}, schema["params"])

    try:
        strategy = cls(**coerced)
    except TypeError as exc:
        raise TypeError(
            f"Invalid parameters for {class_name}: {exc}. "
            f"Expected: {[param['name'] for param in schema['params']]}"
        ) from exc

    if not isinstance(strategy, BaseStrategy):
        raise TypeError(f"{class_name} did not produce a BaseStrategy instance.")
    return strategy


def _build_registry() -> Dict[str, dict]:
    """Scan the strategies package and build a registry of concrete strategies."""
    registry: Dict[str, dict] = {}
    duplicates: Dict[str, List[str]] = {}

    for py_file in sorted(_HERE.rglob("*.py")):
        if "__pycache__" in py_file.parts:
            continue
        if py_file.name in {"__init__.py", "registry.py", "base.py", "base_strategy.py", "base_strategy_github.py"}:
            continue

        module_path = _file_to_module_path(py_file)
        if module_path is None:
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
            if class_name in registry:
                duplicates.setdefault(class_name, []).extend(
                    [registry[class_name]["module_path"], module_path]
                )
                continue
            registry[class_name] = schema

    if duplicates:
        logger.warning("Duplicate strategy names ignored: %s", duplicates)

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
        logger.debug("Cannot import %s: %s", module_path, exc)
        return None


def _extract_schema(cls: Type[BaseStrategy], module_path: str) -> Optional[dict]:
    try:
        params = _extract_param_schema(cls)
        description = getattr(cls, "DESCRIPTION", "") or inspect.cleandoc(cls.__doc__ or "")
        display_name = cls.__name__

        try:
            defaults = {
                param["name"]: param["default"]
                for param in params
                if param["default"] is not None
            }
            instance = cls(**defaults)
            display_name = instance.name
            if not description:
                description = instance.description
        except Exception:
            pass

        return {
            "class_name": cls.__name__,
            "display_name": display_name,
            "module_path": module_path,
            "description": description,
            "category": getattr(cls, "CATEGORY", "Custom"),
            "params": params,
        }
    except Exception as exc:
        logger.debug("Cannot extract schema from %s: %s", cls.__name__, exc)
        return None


def _extract_param_schema(cls: Type[BaseStrategy]) -> List[dict]:
    explicit_schema = getattr(cls, "PARAM_SCHEMA", None)
    if explicit_schema:
        return [dict(item) for item in explicit_schema]

    signature = inspect.signature(cls.__init__)
    params: List[dict] = []
    for name, param in signature.parameters.items():
        if name in {"self", "args", "kwargs"}:
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


def _coerce_params(params: Dict[str, Any], schema: List[dict]) -> Dict[str, Any]:
    schema_map = {item["name"]: item for item in schema}
    coerced: Dict[str, Any] = {}

    for key, value in params.items():
        if key not in schema_map:
            coerced[key] = value
            continue

        ptype = schema_map[key]["type"]
        try:
            if ptype == "int":
                coerced[key] = int(value)
            elif ptype == "float":
                coerced[key] = float(value)
            elif ptype == "bool":
                if isinstance(value, str):
                    coerced[key] = value.strip().lower() in {"1", "true", "yes", "on"}
                else:
                    coerced[key] = bool(value)
            elif ptype in {"str", "select"}:
                coerced[key] = str(value)
            else:
                coerced[key] = value
        except (TypeError, ValueError):
            coerced[key] = value

    return coerced


__all__ = [
    "get_strategy_registry",
    "get_strategy_schema",
    "list_strategies",
    "load_strategy",
]
