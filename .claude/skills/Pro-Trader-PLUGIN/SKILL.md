# Pro-Trader-PLUGIN Development Patterns

> Auto-generated skill from repository analysis

## Overview

This skill covers development patterns for a comprehensive trading system built in Python. The codebase implements a plugin-based architecture for market data analysis, trading intelligence gathering, and automated trading execution. The system includes data flow pipelines, market monitors, trading agents, and a web-based dashboard for real-time monitoring.

## Coding Conventions

### File Naming
- Use **snake_case** for all Python files
- Plugin files follow pattern: `{category}_{name}.py`
- Monitor scripts: `{source}_monitor.py`
- Tracker scripts: `{source}_tracker.py`

### Import Organization
```python
# Standard library imports first
import sys
from pathlib import Path
import json

# Third party imports
import pandas as pd
import numpy as np

# Local imports with dynamic path resolution
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from pro_trader.core.registry import PluginRegistry
from tradingagents.dataflows.market_data import MarketDataProcessor
```

### Path Management
Always use dynamic path resolution to avoid hardcoded paths:
```python
REPO = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO / "config" / "strategy.json"
LOGS_PATH = REPO / "logs"
```

## Workflows

### Plugin Integration
**Trigger:** When someone wants to add a new data source, analyst, monitor, or other plugin functionality
**Command:** `/new-plugin`

1. Create plugin implementation in `pro_trader/plugins/{category}/`
   ```python
   # pro_trader/plugins/analyzers/sentiment_analyzer.py
   from pro_trader.core.base import BasePlugin
   
   class SentimentAnalyzer(BasePlugin):
       def __init__(self, config):
           super().__init__(config)
           self.name = "sentiment_analyzer"
       
       def process(self, data):
           # Plugin logic here
           return processed_data
   ```

2. Update `pro_trader/core/registry.py` for plugin discovery
   ```python
   def discover_plugins(self, category):
       plugin_dir = self.base_path / "plugins" / category
       for file_path in plugin_dir.glob("*.py"):
           # Registration logic
   ```

3. Add plugin to `pyproject.toml` entry points
   ```toml
   [project.entry-points."pro_trader.analyzers"]
   sentiment = "pro_trader.plugins.analyzers.sentiment_analyzer:SentimentAnalyzer"
   ```

4. Update `__init__.py` files for imports
   ```python
   from .sentiment_analyzer import SentimentAnalyzer
   __all__ = ["SentimentAnalyzer"]
   ```

### Fix Imports and Paths
**Trigger:** When someone needs to fix path dependencies or import errors across the system
**Command:** `/fix-paths`

1. Add REPO variable using `Path(__file__).resolve().parent.parent`
   ```python
   from pathlib import Path
   REPO = Path(__file__).resolve().parent.parent
   ```

2. Update `sys.path.insert` with dynamic paths
   ```python
   import sys
   sys.path.insert(0, str(REPO))
   sys.path.insert(0, str(REPO / "tradingagents"))
   ```

3. Fix relative imports to use absolute imports from REPO root

4. Update script paths to use REPO root
   ```python
   config_file = REPO / "config" / "strategy.json"
   log_file = REPO / "logs" / "trading_state.json"
   ```

### Monitor Intelligence Integration
**Trigger:** When someone wants to add a new data source that feeds into trading decisions
**Command:** `/add-intelligence`

1. Create new monitor/tracker script in `scripts/`
   ```python
   # scripts/crypto_fear_greed_monitor.py
   def get_fear_greed_index():
       # Fetch data from API
       return score, timestamp
   
   def update_intelligence_context():
       score, ts = get_fear_greed_index()
       # Save to logs/fear_greed_state.json
   ```

2. Add data source integration in `get_market_data.py`
   ```python
   def apply_intelligence_bonuses(symbol, base_score):
       bonuses = load_intelligence_context()
       if bonuses.get('fear_greed_bullish'):
           base_score += 0.15  # Boost score
       return base_score
   ```

3. Wire score bonuses into the pipeline by updating scoring logic

4. Update intelligence context loading to include new data source

5. Add cron job for periodic execution
   ```bash
   */15 * * * * cd /path/to/repo && python scripts/crypto_fear_greed_monitor.py
   ```

### Trading System Enhancement
**Trigger:** When someone wants to enhance the core trading system with new features
**Command:** `/enhance-trading`

1. Create new module in `tradingagents/` subdirectory
   ```python
   # tradingagents/risk_management/kelly_criterion.py
   class KellyCriterion:
       def calculate_position_size(self, win_rate, avg_win, avg_loss):
           # Kelly formula implementation
           return position_size
   ```

2. Integrate with existing pipeline scripts
   ```python
   # In scripts/full_pipeline_scan.py
   from tradingagents.risk_management.kelly_criterion import KellyCriterion
   ```

3. Update `trade_gate.py` with new logic
   ```python
   def should_enter_trade(symbol, signals):
       # Add new risk management checks
       kelly = KellyCriterion()
       position_size = kelly.calculate_position_size(...)
       return position_size > 0.01  # Minimum threshold
   ```

4. Wire into `get_market_data.py` for scoring adjustments

5. Add configuration to `config/strategy.json` if needed
   ```json
   {
     "risk_management": {
       "kelly_enabled": true,
       "max_position_size": 0.1
     }
   }
   ```

### Documentation Overhaul
**Trigger:** When someone wants to comprehensively update project documentation
**Command:** `/update-docs`

1. Rewrite `README.md` with current architecture
   ```markdown
   # Pro-Trader-PLUGIN
   
   ## Architecture
   ```mermaid
   graph TD
       A[Market Data] --> B[Intelligence Pipeline]
       B --> C[Trading Signals]
   ```

2. Add system diagrams using Mermaid or ASCII art

3. Document all features and integrations with code examples

4. Update installation and usage instructions
   ```bash
   pip install -e .
   python scripts/full_pipeline_scan.py
   ```

5. Add configuration examples for common use cases

### Log State Management
**Trigger:** When someone needs to update or fix state management across log files
**Command:** `/fix-state`

1. Update relevant JSON state files in `logs/`
   ```python
   def reset_trading_state():
       state = {
           "last_scan": None,
           "active_positions": {},
           "drawdown_level": 0.0
       }
       with open(REPO / "logs" / "trading_state.json", "w") as f:
           json.dump(state, f, indent=2)
   ```

2. Reset state for new configurations by clearing relevant files

3. Add missing log files with proper initial structure

4. Clean up orphaned state files that are no longer used

### Dashboard Feature Addition
**Trigger:** When someone wants to add new dashboard functionality or improve the UI
**Command:** `/enhance-dashboard`

1. Update `dashboard/index.html` with new UI components
   ```html
   <div class="metric-card" id="risk-metrics">
       <h3>Risk Management</h3>
       <div class="metric-value" id="kelly-size">--</div>
   </div>
   ```

2. Add corresponding API endpoints in `dashboard/server.py`
   ```python
   @app.route('/api/risk-metrics')
   def get_risk_metrics():
       # Load kelly parameters and calculate current risk
       return jsonify(risk_data)
   ```

3. Implement real-time data streaming using WebSockets if needed

4. Add PWA features or update service worker for offline capability

## Testing Patterns

Tests follow the pattern `*.test.*` and are located throughout the codebase. Common testing approaches:

```python
# test_plugin_integration.py
def test_plugin_discovery():
    registry = PluginRegistry()
    plugins = registry.discover_plugins("analyzers")
    assert len(plugins) > 0

def test_market_data_processing():
    processor = MarketDataProcessor()
    result = processor.process(mock_data)
    assert result["score"] > 0
```

## Commands

| Command | Purpose |
|---------|---------|
| `/new-plugin` | Add a new plugin to the pro_trader plugin system |
| `/fix-paths` | Fix hardcoded paths and import issues for portability |
| `/add-intelligence` | Add new market intelligence source to trading pipeline |
| `/enhance-trading` | Add new trading system capabilities like risk management |
| `/update-docs` | Comprehensively update project documentation |
| `/fix-state` | Manage persistent state files and log data |
| `/enhance-dashboard` | Add new features to the trading dashboard interface |