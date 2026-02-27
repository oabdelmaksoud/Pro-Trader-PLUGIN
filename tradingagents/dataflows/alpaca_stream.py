"""
CooperCorp PRJ-002 — Alpaca Live Market Data Stream
TODO: WebSocket feed to replace yfinance for live trading

See: ~/.openclaw/skills/trading-agents/references/broker-integration.md
"""

class AlpacaStream:
    """
    Real-time bar/trade/quote streaming via Alpaca WebSocket.
    Replaces yfinance (batch/delayed) for live trading mode.
    """
    def __init__(self, api_key: str, secret_key: str):
        self.api_key = api_key
        self.secret_key = secret_key
        raise NotImplementedError("Alpaca stream not yet implemented — assign to Forge (PRJ-002)")

    async def on_bar(self, bar):
        raise NotImplementedError

    def subscribe(self, symbols: list):
        raise NotImplementedError

    def run(self):
        raise NotImplementedError
