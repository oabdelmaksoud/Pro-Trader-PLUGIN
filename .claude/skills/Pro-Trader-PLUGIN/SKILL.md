# Pro-Trader-PLUGIN Development Patterns

> Auto-generated skill from repository analysis

## Overview

This skill teaches the development patterns for Pro-Trader-PLUGIN, a Python-based trading system that combines automated market analysis, plugin-based architecture, and real-time monitoring. The codebase follows a modular design with data flows, trading agents, monitoring scripts, and a web dashboard for visualization.

## Coding Conventions

### File Naming
- Use `snake_case` for all Python files
- Plugin files: `{name}_plugin.py` in `pro_trader/plugins/{category}/`
- Data source files: `{source}_data.py` in `tradingagents/dataflows/`
- Script files: `{purpose}.py` or `{name}_monitor.py` in `scripts/`
- State files: `{feature}_state.json` or `{feature}_cache.json` in `logs/`

### Import Style
```python
# Standard library imports first
import json
import time
from datetime import datetime

# Third-party imports
import requests
import pandas as pd

# Local imports
from pro_trader.core.registry import register_plugin
from tradingagents.dataflows import base_data
```

### Commit Conventions
- Use conventional commit prefixes: `feat:`, `fix:`, `docs:`, `chore:`
- Keep commit messages around 53 characters
- Example: `feat: add sentiment analysis plugin for news data`

## Workflows

### Plugin Development Cycle
**Trigger:** When adding new trading functionality (data source, strategy, monitor, etc.)
**Command:** `/new-plugin`

1. Create plugin implementation in `pro_trader/plugins/{category}/{name}_plugin.py`
   ```python
   from pro_trader.core.registry import register_plugin
   
   @register_plugin('data_source')
   class NewsPlugin:
       def fetch_data(self):
           # Implementation
           pass
   ```

2. Update `pro_trader/core/registry.py` to register the plugin
3. Add plugin to `pyproject.toml` entry_points or dependencies
4. Create corresponding test file in `tests/test_{name}_plugin.py`
5. Test the plugin integration with existing pipeline

### Data Source Integration
**Trigger:** When adding a new data source that affects trading decisions
**Command:** `/new-data-source`

1. Create data fetching module in `tradingagents/dataflows/{source}_data.py`
   ```python
   def fetch_{source}_data(symbol):
       # Fetch data logic
       data = get_external_data(symbol)
       
       # Score the data impact
       score = calculate_market_impact(data)
       
       return {
           'data': data,
           'score': score,
           'timestamp': datetime.now()
       }
   ```

2. Wire into `scripts/get_market_data.py` with scoring logic
3. Update `scripts/full_pipeline_scan.py` to include in agent context
4. Add to intelligence context loading functions
5. Test data flow through the complete pipeline

### Monitoring Script Creation
**Trigger:** When adding automated monitoring for specific market events
**Command:** `/new-monitor`

1. Create monitoring script in `scripts/{name}_monitor.py`
   ```python
   import json
   from datetime import datetime
   
   def load_state():
       try:
           with open('logs/{name}_state.json', 'r') as f:
               return json.load(f)
       except FileNotFoundError:
           return {}
   
   def save_state(state):
       with open('logs/{name}_state.json', 'w') as f:
           json.dump(state, f)
   
   def monitor_{name}():
       state = load_state()
       # Monitoring logic
       # Alert posting logic
       save_state(state)
   ```

2. Add state tracking in `logs/{name}_state.json`
3. Wire into cron scheduling system
4. Add Discord alert posting functionality
5. Test monitoring thresholds and alert delivery

### Trade Execution Enhancement
**Trigger:** When adding new trading rules, gates, or execution logic
**Command:** `/enhance-execution`

1. Update `scripts/trade_gate.py` with new gate logic
   ```python
   def enhanced_trade_gate(symbol, signal_data):
       # Existing gate checks
       if not basic_checks(symbol, signal_data):
           return False
       
       # New enhancement logic
       if not new_risk_check(symbol):
           return False
       
       return True
   ```

2. Modify `scripts/close_position.py` for exit handling
3. Update `config/strategy.json` with new parameters
4. Add state tracking in `logs/` files
5. Backtest new execution logic before deployment

### Dashboard Feature Addition
**Trigger:** When adding new visualization or functionality to the dashboard
**Command:** `/dashboard-feature`

1. Update `dashboard/index.html` with new UI components
   ```html
   <div id="new-feature-panel">
       <h3>New Feature</h3>
       <div id="feature-data"></div>
   </div>
   ```

2. Add corresponding API endpoints in `dashboard/server.py`
   ```python
   @app.route('/api/new-feature')
   def get_new_feature_data():
       data = fetch_feature_data()
       return jsonify(data)
   ```

3. Implement SSE streaming if real-time updates needed
4. Add data fetching from trading system logs/APIs
5. Test UI responsiveness and data accuracy

### Documentation Overhaul
**Trigger:** When significant system changes require comprehensive documentation updates
**Command:** `/doc-update`

1. Rewrite `README.md` with current architecture
2. Add or update `SKILL.md`/`AGENTS.md` for OpenClaw compatibility
3. Include system diagrams and workflow descriptions
4. Update installation and usage instructions
5. Review and update code comments for clarity

### Log State Management
**Trigger:** When adding new features that need persistent state or caching
**Command:** `/new-state-tracking`

1. Create new JSON log file in `logs/{feature}_state.json` or `logs/{feature}_cache.json`
   ```python
   def init_state():
       return {
           'last_update': None,
           'cache': {},
           'metrics': {
               'total_updates': 0,
               'last_reset': datetime.now().isoformat()
           }
       }
   ```

2. Implement state read/write logic in relevant scripts
3. Add cleanup and maintenance logic for log rotation
4. Wire into monitoring or execution scripts
5. Add error handling for corrupted state files

## Testing Patterns

- Test files follow pattern: `*.test.*`
- Focus on integration testing for plugin compatibility
- Mock external data sources in tests
- Test state persistence and recovery scenarios
- Validate alert and monitoring thresholds

## Commands

| Command | Purpose |
|---------|---------|
| `/new-plugin` | Add a new plugin to the pro-trader plugin system |
| `/new-data-source` | Wire a new data source into the trading pipeline |
| `/new-monitor` | Create automated monitoring for market events |
| `/enhance-execution` | Add new trading rules and execution logic |
| `/dashboard-feature` | Add new dashboard visualization or functionality |
| `/doc-update` | Comprehensive documentation updates |
| `/new-state-tracking` | Create persistent state management for features |