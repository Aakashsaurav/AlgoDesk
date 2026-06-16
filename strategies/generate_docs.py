import sys
from pathlib import Path
from typing import Dict, Any

# Ensure we can import from the root project directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from strategies.registry import get_strategy_registry

def generate_docs() -> str:
    """Generate Markdown documentation for all registered strategies."""
    strategies = get_strategy_registry()
    
    lines = [
        "# Algodesk Strategy Developer Guide & Built-in Strategies",
        "",
        "This document contains both the Strategy Developer Guide for creating new strategies and the auto-generated documentation for all built-in strategies.",
        "",
        "## 1. Strategy Developer Guide",
        "",
        "### 1.1 Required Input",
        "All strategies must accept a pandas DataFrame containing standard OHLCV columns: `open`, `high`, `low`, `close`, `volume`. Datetime index should be present.",
        "",
        "### 1.2 Standard Output Columns",
        "Strategies must return a DataFrame with the following standardized output columns:",
        "- `signal` (int): 1 for Long, -1 for Short, 0 for Neutral",
        "- `signal_tag` (str): Descriptive tag (e.g. 'ST_BUY_ENTRY')",
        "- `stop_loss` (float): Current static stop loss price",
        "- `take_profit` (float): Current static take profit price",
        "- `order_spec` (OrderSpec): An explicit order instruction dataclass",
        "- `confidence` (float): 0.0 to 1.0 confidence score",
        "- `reason` (str): Optional string explaining the signal",
        "",
        "### 1.3 Vectorized vs Event-Driven Patterns",
        "- **Vectorized Pattern**: Compute all indicators and signals globally using pandas/numpy. Fast and heavily preferred. Implement via `generate_signals(self, df: pd.DataFrame)`.",
        "- **Event-Driven Pattern**: Utilize `on_entry_stop(self, bar_idx, row, direction)` and `on_bar_close(self, bar_idx, row)` for fine-grained tick-by-tick simulation control in the Backtester.",
        "- **Portfolio Strategy Hook**: Use `on_portfolio(self, current_bar, open_positions)` to orchestrate risk across multiple symbols simultaneously.",
        "",
        "### 1.4 Parameter Schema",
        "Define all parameters in a class-level `PARAM_SCHEMA` list to enable automatic UI validation and Optimization grid generation. Fields:",
        "- `name`, `type`, `default`, `min`, `max`, `step`, `label`, `description`, `optimize`.",
        "",
        "### 1.5 No-Lookahead Expectation",
        "Strategies must NEVER use future rows to generate signals for the current row. `IndicatorEngine` explicitly blocks shifting signals backwards.",
        "",
        "---",
        "",
        "## 2. Available Built-in Strategies",
        ""
    ]
    
    # Group by category
    by_category: Dict[str, list] = {}
    for class_name, info in strategies.items():
        cat = info.get("category", "Uncategorized")
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append((class_name, info))
        
    for cat in sorted(by_category.keys()):
        lines.append(f"### {cat}")
        lines.append("")
        
        for class_name, info in sorted(by_category[cat], key=lambda x: x[0]):
            lines.append(f"#### {info.get('name', class_name)}")
            lines.append("")
            lines.append(f"**Class Name:** `{class_name}`")
            lines.append("")
            lines.append(f"{info.get('description', '')}")
            lines.append("")
            
            schema = info.get("schema", [])
            if schema:
                lines.append("**Parameters:**")
                lines.append("")
                lines.append("| Parameter | Type | Default | Min/Max/Options | Description | Opt? |")
                lines.append("|-----------|------|---------|-----------------|-------------|------|")
                
                for param in schema:
                    name = param.get("name", "")
                    ptype = param.get("type", "str")
                    default = str(param.get("default", ""))
                    
                    bounds = []
                    if ptype in ("int", "float"):
                        if "min" in param and "max" in param:
                            bounds.append(f"[{param['min']}, {param['max']}]")
                    elif ptype == "select":
                        bounds.append(", ".join(param.get("options", [])))
                        
                    bounds_str = " ".join(bounds)
                    desc = param.get("description", "")
                    opt = "Yes" if param.get("optimize", False) else "No"
                    
                    lines.append(f"| `{name}` | `{ptype}` | `{default}` | {bounds_str} | {desc} | {opt} |")
                
                lines.append("")
                
            req_cols = info.get("required_extra_columns", [])
            if req_cols:
                lines.append("**Required Extra Columns:**")
                for c in req_cols:
                    lines.append(f"- `{c}`")
                lines.append("")
                
    return "\n".join(lines)

if __name__ == "__main__":
    docs = generate_docs()
    target_path = Path(__file__).resolve().parent / "README.md"
    target_path.write_text(docs)
    print(f"Generated strategy documentation at {target_path}")
