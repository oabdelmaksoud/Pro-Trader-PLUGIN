"""
Pro-Trader Plugin Framework
===========================
Three-layer architecture: Core Library → Plugin System → Service Layer

Usage:
    from pro_trader import ProTrader

    trader = ProTrader()
    trader.load_plugins()
    signal = trader.analyze("/METH26")
"""

__version__ = "1.0.0"

from pro_trader.core.trader import ProTrader

__all__ = ["ProTrader", "__version__"]
