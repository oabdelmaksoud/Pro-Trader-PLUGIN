"""
CooperCorp PRJ-002 — Alpaca Broker Integration
TODO: Implement REST + WebSocket execution layer

See: ~/.openclaw/skills/trading-agents/references/broker-integration.md
"""

class AlpacaBroker:
    """
    Alpaca Markets broker adapter.
    Replace the simulated exchange in agents/managers/portfolio_manager.py
    """
    def __init__(self, api_key: str, secret_key: str, base_url: str = "https://paper-api.alpaca.markets"):
        # TODO: import alpaca_trade_api and initialize
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = base_url
        raise NotImplementedError("Alpaca broker not yet implemented — assign to Forge (PRJ-002)")

    def submit_order(self, symbol: str, qty: float, side: str, order_type: str = "market"):
        raise NotImplementedError

    def get_positions(self):
        raise NotImplementedError

    def get_portfolio_value(self) -> float:
        raise NotImplementedError
