"""
indicators/expression.py
------------------------
Safe AST-based evaluator for indicator expressions.

Allows users to write formulaic rules like:
    "sma(close, 50) > sma(close, 200)"
    "rsi(close, 14) < 30 & macd(close)['histogram'] > 0"
    "close > close[-1]"  # shift syntax for previous bar
"""

import ast
import operator as op
import re
from typing import Any, Dict

import numpy as np
import pandas as pd
from indicators.engine import IndicatorEngine
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Set

@dataclass
class CompiledExpression:
    """Compiled representation of an indicator expression."""
    tree: ast.AST
    required_columns: Set[str] = field(default_factory=set)
    required_indicators: Set[str] = field(default_factory=set)

# Supported safe operators
_OPERATORS = {
    ast.Add: op.add,
    ast.Sub: op.sub,
    ast.Mult: op.mul,
    ast.Div: op.truediv,
    ast.Pow: op.pow,
    ast.USub: op.neg,
    ast.Eq: op.eq,
    ast.NotEq: op.ne,
    ast.Lt: op.lt,
    ast.LtE: op.le,
    ast.Gt: op.gt,
    ast.GtE: op.ge,
    ast.BitAnd: op.and_,
    ast.BitOr: op.or_,
    ast.Invert: op.invert,
}


class ExpressionParser:
    """
    Safely parses and evaluates string expressions involving price data
    and indicators using Python's AST.
    """

    def __init__(self, engine: IndicatorEngine, data: Dict[str, pd.Series]) -> None:
        """
        Args:
            engine: Configured IndicatorEngine to compute function calls.
            data: Dictionary of named series (e.g., {"close": df["close"], ...})
        """
        self.engine = engine
        self.data = data

    def evaluate(self, expr: str) -> pd.Series | float | bool:
        """
        Parse and evaluate the expression.

        Replaces 'and' / 'or' with bitwise '&' / '|' prior to parsing
        to support pandas element-wise logical operations.
        
        Raises:
            ValueError: If expression is empty or invalid syntax.
        """
        if not expr or not expr.strip():
            raise ValueError("Expression cannot be empty")

        # Replace logical operators with bitwise ones for pandas
        import re
        # Case-insensitive replacement for 'AND' and 'OR' to 'and' and 'or' so AST can parse them
        expr = re.sub(r'(?i)\band\b', 'and', expr)
        expr = re.sub(r'(?i)\bor\b', 'or', expr)

        compiled = self.parse(expr)
        return self._eval(compiled.tree)

    @classmethod
    @lru_cache(maxsize=128)
    def parse(cls, expr: str) -> CompiledExpression:
        """
        Parse an expression string into a CompiledExpression.
        
        Raises:
            ValueError: If expression is empty or invalid syntax.
        """
        if not expr or not expr.strip():
            raise ValueError("Expression cannot be empty")

        expr = re.sub(r'(?i)\band\b', 'and', expr)
        expr = re.sub(r'(?i)\bor\b', 'or', expr)

        try:
            tree = ast.parse(expr, mode="eval").body
        except SyntaxError as e:
            raise ValueError(f"Invalid expression syntax: {expr}") from e
            
        required_columns = set()
        required_indicators = set()
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                if node.id.lower() not in ("true", "false"):
                    required_columns.add(node.id)
            elif isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name):
                    required_indicators.add(node.func.id)
                    # Exclude the function name from required columns if it was added
                    required_columns.discard(node.func.id)
                    
        return CompiledExpression(
            tree=tree,
            required_columns=required_columns,
            required_indicators=required_indicators
        )

    @classmethod
    def validate(cls, expr: str) -> tuple[bool, str]:
        """
        Validate an expression string.
        Returns a tuple of (is_valid, error_message).
        """
        try:
            cls.parse(expr)
            return True, ""
        except Exception as e:
            return False, str(e)

    def evaluate_boolean(self, expr: str) -> pd.Series:
        """
        Evaluate the expression and ensure the result is a boolean pandas Series.
        Useful for screener rules.
        
        Raises:
            TypeError: If result cannot be converted to a boolean Series.
        """
        result = self.evaluate(expr)
        if isinstance(result, pd.Series):
            return result.astype(bool)
        elif isinstance(result, (bool, np.bool_)):
            # If the expression evaluated to a scalar bool, broadcast to a series based on data index
            if self.data:
                first_series = next(iter(self.data.values()))
                return pd.Series(result, index=first_series.index)
            return pd.Series([result])
        elif isinstance(result, (int, float)):
            if self.data:
                first_series = next(iter(self.data.values()))
                return pd.Series(bool(result), index=first_series.index)
            return pd.Series([bool(result)])
        else:
            raise TypeError(f"Expression result cannot be converted to boolean Series: {type(result)}")

    def _eval(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            return node.value

        elif isinstance(node, ast.Name):
            if node.id in self.data:
                return self.data[node.id]
            # Try to resolve as a boolean constant if lowercased
            if node.id.lower() == "true": return True
            if node.id.lower() == "false": return False
            raise NameError(f"Unknown variable or data series: '{node.id}'")

        elif isinstance(node, ast.BinOp):
            left = self._eval(node.left)
            right = self._eval(node.right)
            op_func = _OPERATORS.get(type(node.op))
            if not op_func:
                raise TypeError(f"Unsupported binary operator: {type(node.op).__name__}")
            return op_func(left, right)

        elif isinstance(node, ast.UnaryOp):
            operand = self._eval(node.operand)
            op_func = _OPERATORS.get(type(node.op))
            if not op_func:
                raise TypeError(f"Unsupported unary operator: {type(node.op).__name__}")
            return op_func(operand)

        elif isinstance(node, ast.BoolOp):
            # Evaluate all values and reduce them with bitwise operators for pandas Series
            op_func = op.and_ if isinstance(node.op, ast.And) else op.or_
            result = self._eval(node.values[0])
            for next_node in node.values[1:]:
                result = op_func(result, self._eval(next_node))
            return result

        elif isinstance(node, ast.Compare):
            left = self._eval(node.left)
            if len(node.ops) > 1:
                raise ValueError("Chained comparisons (e.g. 10 < x < 20) are not supported. Use '&' instead.")
            right = self._eval(node.comparators[0])
            op_func = _OPERATORS.get(type(node.ops[0]))
            if not op_func:
                raise TypeError(f"Unsupported comparison operator: {type(node.ops[0]).__name__}")
            return op_func(left, right)

        elif isinstance(node, ast.Call):
            args = [self._eval(arg) for arg in node.args]
            kwargs = {kw.arg: self._eval(kw.value) for kw in node.keywords if kw.arg}

            if isinstance(node.func, ast.Name):
                func_name = node.func.id
                # If it's a known data column/series but called like a func, that's an error
                if func_name in self.data:
                    raise ValueError(f"'{func_name}' is a data series, not a function.")
                return self.engine.compute(func_name, *args, **kwargs)
            elif isinstance(node.func, ast.Attribute):
                func_callable = self._eval(node.func)
                if callable(func_callable):
                    return func_callable(*args, **kwargs)
                raise TypeError("Attribute is not callable")
            else:
                raise ValueError("Only direct function calls and method attributes are supported")

        elif isinstance(node, ast.Subscript):
            value = self._eval(node.value)
            
            # Extract slice value based on AST version (Python 3.8 vs 3.9+)
            if isinstance(node.slice, ast.Constant):
                slice_val = node.slice.value
            elif isinstance(node.slice, ast.Index):  # Python 3.8 fallback
                if isinstance(node.slice.value, ast.Constant):
                    slice_val = node.slice.value.value
                elif isinstance(node.slice.value, ast.UnaryOp) and isinstance(node.slice.value.op, ast.USub):
                    # Negative index
                    slice_val = -node.slice.value.operand.value
                else:
                    slice_val = self._eval(node.slice.value)
            elif isinstance(node.slice, ast.UnaryOp) and isinstance(node.slice.op, ast.USub):
                 slice_val = -self._eval(node.slice.operand)
            else:
                slice_val = self._eval(node.slice)

            # Support shift syntax for pandas Series (e.g. close[-1] -> close.shift(1))
            if isinstance(value, pd.Series) and isinstance(slice_val, int):
                if slice_val < 0:
                    return value.shift(abs(slice_val))
                elif slice_val > 0:
                    return value.shift(-slice_val)
                return value

            # Dictionary access (e.g., macd['histogram'])
            if isinstance(value, (dict, pd.DataFrame)) and isinstance(slice_val, str):
                return value[slice_val]

            raise TypeError(f"Unsupported subscript type {type(slice_val).__name__} on {type(value).__name__}")

        elif isinstance(node, ast.Attribute):
            value = self._eval(node.value)
            if isinstance(value, pd.Series):
                if node.attr == "shift":
                    # We return a callable that applies shift, to be used in ast.Call
                    return value.shift
            raise TypeError(f"Unsupported attribute '{node.attr}' on {type(value).__name__}")

        else:
            raise TypeError(f"Unsupported syntax construct: {type(node).__name__}")

__all__ = ["ExpressionParser"]
