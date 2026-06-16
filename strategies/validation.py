import logging
from typing import Any, Dict, List

from strategies.contracts import ParamSpec

logger = logging.getLogger(__name__)

def normalize_param_schema(raw_schema: List[Dict[str, Any]]) -> List[ParamSpec]:
    """Convert raw dictionary schema to ParamSpec objects."""
    schema = []
    for item in raw_schema:
        if isinstance(item, ParamSpec):
            schema.append(item)
        else:
            # Add defaults for optional fields if missing
            spec_dict = dict(item)
            if spec_dict.get("type") == "series":
                spec_dict["required"] = True
                spec_dict["runtime_only"] = True
            schema.append(ParamSpec(**spec_dict))
    return schema

def validate_param_schema(schema: List[ParamSpec]) -> None:
    """Validate that the schema itself is logically sound."""
    for spec in schema:
        if spec.type in ("int", "float"):
            if spec.min is not None and spec.max is not None and spec.min > spec.max:
                raise ValueError(f"Param '{spec.name}' has min > max.")
            if spec.optimize:
                if spec.min is None or spec.max is None or spec.step is None:
                    raise ValueError(f"Optimizer-eligible param '{spec.name}' must define min, max, and step.")
        elif spec.type == "select":
            if not spec.options:
                raise ValueError(f"Select param '{spec.name}' requires 'options'.")
        # Ensure default satisfies schema
        if spec.default is not None:
            try:
                coerce_param_value(spec.default, spec)
            except ValueError as e:
                raise ValueError(f"Default value for '{spec.name}' violates schema: {e}")

def coerce_param_value(value: Any, spec: ParamSpec) -> Any:
    """Coerce a single value according to its ParamSpec."""
    if value is None:
        if spec.required:
            raise ValueError(f"Parameter '{spec.name}' is required but received None.")
        return None

    if spec.type == "int":
        try:
            val = int(value)
        except (ValueError, TypeError):
            raise ValueError(f"Parameter '{spec.name}' must be an integer, got {value}.")
        if spec.min is not None and val < spec.min:
            raise ValueError(f"Parameter '{spec.name}'={val} is below minimum {spec.min}.")
        if spec.max is not None and val > spec.max:
            raise ValueError(f"Parameter '{spec.name}'={val} is above maximum {spec.max}.")
        return val

    if spec.type == "float":
        try:
            val = float(value)
        except (ValueError, TypeError):
            raise ValueError(f"Parameter '{spec.name}' must be a float, got {value}.")
        if spec.min is not None and val < spec.min:
            raise ValueError(f"Parameter '{spec.name}'={val} is below minimum {spec.min}.")
        if spec.max is not None and val > spec.max:
            raise ValueError(f"Parameter '{spec.name}'={val} is above maximum {spec.max}.")
        return val

    if spec.type == "bool":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lower_val = value.lower()
            if lower_val in ("true", "1", "yes"):
                return True
            if lower_val in ("false", "0", "no"):
                return False
        if isinstance(value, int):
            return bool(value)
        raise ValueError(f"Parameter '{spec.name}' must be a boolean.")

    if spec.type == "select":
        if spec.options is not None and value not in spec.options:
            raise ValueError(f"Parameter '{spec.name}'={value} is not a valid option: {spec.options}.")
        return value

    if spec.type == "str":
        return str(value)

    if spec.type == "series":
        return value

    return value

def coerce_params(params: Dict[str, Any], schema: List[ParamSpec], allow_extra_params: bool = False) -> Dict[str, Any]:
    """Coerce all parameters, applying defaults where missing."""
    coerced = {}
    spec_map = {spec.name: spec for spec in schema}

    for key, value in params.items():
        if key not in spec_map:
            if not allow_extra_params:
                raise ValueError(f"Unknown parameter '{key}' provided.")
            coerced[key] = value
        else:
            coerced[key] = coerce_param_value(value, spec_map[key])

    for spec in schema:
        if spec.name not in coerced:
            if spec.required and spec.default is None:
                raise ValueError(f"Required parameter '{spec.name}' is missing.")
            coerced[spec.name] = coerce_param_value(spec.default, spec)

    return coerced

def validate_params_against_schema(params: Dict[str, Any], schema: List[ParamSpec], allow_extra_params: bool = False) -> None:
    """Validate params without modifying them."""
    coerce_params(params, schema, allow_extra_params)
