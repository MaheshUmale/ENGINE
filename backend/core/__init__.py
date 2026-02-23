"""
Core module for ProTrade Enhanced Options Trading Platform.
Uses lazy loading to prevent circular dependencies.
"""
from typing import Any

def __getattr__(name: str) -> Any:
    import importlib
    if name == 'options_manager':
        mod = importlib.import_module('core.options_manager')
        return getattr(mod, 'options_manager')
    if name == 'data_engine':
        return importlib.import_module('core.data_engine')
    if name == 'symbol_mapper':
        mod = importlib.import_module('core.symbol_mapper')
        return getattr(mod, 'symbol_mapper')
    if name == 'greeks_calculator':
        mod = importlib.import_module('core.greeks_calculator')
        return getattr(mod, 'greeks_calculator')
    if name == 'iv_analyzer':
        mod = importlib.import_module('core.iv_analyzer')
        return getattr(mod, 'iv_analyzer')
    if name == 'oi_buildup_analyzer':
        mod = importlib.import_module('core.oi_buildup_analyzer')
        return getattr(mod, 'oi_buildup_analyzer')
    if name == 'strategy_builder':
        mod = importlib.import_module('core.strategy_builder')
        return getattr(mod, 'strategy_builder')
    if name == 'alert_system':
        mod = importlib.import_module('core.alert_system')
        return getattr(mod, 'alert_system')

    # Check if it's a module in core
    try:
        return importlib.import_module(f"core.{name}")
    except ImportError:
        raise AttributeError(f"module {__name__} has no attribute {name}")

__all__ = [
    'options_manager',
    'data_engine',
    'symbol_mapper',
    'greeks_calculator',
    'iv_analyzer',
    'oi_buildup_analyzer',
    'strategy_builder',
    'alert_system'
]
