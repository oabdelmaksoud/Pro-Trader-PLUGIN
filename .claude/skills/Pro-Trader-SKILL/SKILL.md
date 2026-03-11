# Pro-Trader-SKILL Development Patterns

> Auto-generated skill from repository analysis

## Overview

This skill teaches development patterns for the Pro-Trader system - a sophisticated trading automation platform built in Python. The codebase follows a plugin-based architecture with intelligence modules, market data pipelines, and real-time monitoring capabilities. It integrates with OpenClaw for messaging, Discord for notifications, and includes a web dashboard for visualization.

The system is organized around a core registry pattern with pluggable components for different trading strategies, data sources, and notification systems. Intelligence gathering modules feed into scoring algorithms that influence automated trading decisions.

## Coding Conventions

- **File naming:** Use `snake_case` for all Python files
- **Import style:** Mixed approach - use both relative and absolute imports as appropriate
- **Export style:** Mixed - utilize both `__all__` declarations and direct imports
- **Directory structure:** 
  - `pro_trader/` - Core system with plugins and services
  - `scripts/` - Standalone automation scripts
  - `tradingagents/` - Agent-based trading logic
  - `logs/` - Persistent state and cache files
  - `dashboard/` - Web interface components

**Example file structure:**
```python
# scripts/market_monitor.py
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from pro_trader.core.registry import get_plugin
```

## Workflows

### Add New Plugin
**Trigger:** When adding a new plugin capability to the trading system
**Command:** `/add-plugin`

1. Create plugin file in appropriate `pro_trader/plugins/` subdirectory following the plugin interface
2. Update `pro_trader/core/registry.py` to register the new plugin with proper metadata
3. Update `pyproject.toml` with entry points or new dependencies if required
4. Create corresponding test file in `tests/` directory with comprehensive coverage

**Example plugin structure:**
```python
# pro_trader/plugins/analyzers/sentiment_analyzer.py
class SentimentAnalyzer:
    def __init__(self):
        self.name = "sentiment_analyzer"
    
    def analyze(self, data):
        # Implementation here
        pass
```

### Add Intelligence Module
**Trigger:** When adding a new data source or intelligence capability to the trading pipeline
**Command:** `/add-intelligence`

1. Create new module in `scripts/` or `tradingagents/dataflows/` with data fetching logic
2. Wire into `get_market_data.py` for score bonuses and penalty calculations
3. Wire into `full_pipeline_scan.py` for agent consumption and decision making
4. Create corresponding cache/state file in `logs/` for persistence and performance

**Example integration:**
```python
# In get_market_data.py
from scripts.new_intelligence_module import get_signal_strength

def calculate_score_bonus(symbol):
    signal = get_signal_strength(symbol)
    return signal * 0.15  # 15% bonus multiplier
```

### Fix Hardcoded Paths
**Trigger:** When fixing portability issues or hardcoded system paths
**Command:** `/fix-paths`

1. Add `REPO_ROOT = Path(__file__).resolve().parent.parent` at top of files
2. Replace hardcoded absolute paths with relative paths using `REPO_ROOT`
3. Update `sys.path.insert()` calls to use dynamic path construction
4. Update file loading operations to use relative paths from repo root

**Before/After example:**
```python
# Before
sys.path.insert(0, "/home/user/pro-trader")
with open("/home/user/pro-trader/config.json") as f:

# After
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
with open(REPO_ROOT / "config.json") as f:
```

### Update OpenClaw Compatibility
**Trigger:** When upgrading to a new OpenClaw version
**Command:** `/update-openclaw`

1. Update version references in `Dockerfile` with new OpenClaw version tag
2. Update `pro_trader/services/openclaw.py` for new API changes and endpoints
3. Update Discord notifier plugins for messaging format compatibility
4. Update documentation with new version compatibility notes and breaking changes

### Wire Data Into Pipeline
**Trigger:** When connecting disconnected data sources to the main trading flow
**Command:** `/wire-data`

1. Modify `get_market_data.py` to include new data source in scoring calculations
2. Add appropriate score bonuses/penalties based on data signals and thresholds
3. Wire data into agent prompts in `full_pipeline_scan.py` for context awareness
4. Create helper functions for data loading, validation, and context building

**Example scoring integration:**
```python
def apply_data_bonus(base_score, symbol):
    # Get signal from new data source
    signal_strength = new_data_source.get_signal(symbol)
    if signal_strength > 0.7:
        return base_score * 1.2  # 20% bonus
    elif signal_strength < 0.3:
        return base_score * 0.8  # 20% penalty
    return base_score
```

### Add Monitor Script
**Trigger:** When adding a new market monitoring capability
**Command:** `/add-monitor`

1. Create monitoring script in `scripts/` directory with appropriate naming
2. Implement data fetching logic with error handling and retry mechanisms
3. Add Discord posting functionality via openclaw integration
4. Create persistent state/cache file in `logs/` for tracking and deduplication
5. Add cron job configuration comments for scheduling

**Monitor template:**
```python
# scripts/monitor_whale_moves.py
import json
from pathlib import Path

CACHE_FILE = Path(__file__).parent.parent / "logs" / "whale_cache.json"

def check_whale_activity():
    # Fetch and analyze data
    # Check against cache to avoid duplicates
    # Post alerts via Discord if significant
    pass
```

### Enhance Dashboard
**Trigger:** When adding new dashboard functionality or data visualization
**Command:** `/enhance-dashboard`

1. Add new API endpoints in `dashboard/server.py` with proper routing
2. Update `dashboard/index.html` with new UI components and styling
3. Add real-time data streaming capabilities if needed using WebSockets
4. Update chart or data visualization components with new data sources

### Comprehensive README Update
**Trigger:** When major system changes require documentation updates
**Command:** `/update-readme`

1. Add or update Mermaid/ASCII diagrams for system architecture
2. Document new architecture patterns and design decisions
3. Update API documentation and usage examples with current syntax
4. Add new sections for major features with installation and configuration steps

## Testing Patterns

Testing follows a `*.test.*` file pattern. Tests should be created in the `tests/` directory with comprehensive coverage of:
- Plugin registration and functionality
- Data pipeline integration
- Error handling and edge cases
- API endpoint responses
- Mock external service calls

## Commands

| Command | Purpose |
|---------|---------|
| `/add-plugin` | Create a new plugin with proper registration |
| `/add-intelligence` | Add intelligence module to trading pipeline |
| `/fix-paths` | Convert hardcoded paths to portable relative paths |
| `/update-openclaw` | Update system for new OpenClaw compatibility |
| `/wire-data` | Integrate data sources into scoring pipeline |
| `/add-monitor` | Create new market monitoring script with alerts |
| `/enhance-dashboard` | Add new dashboard features and endpoints |
| `/update-readme` | Comprehensive documentation updates with diagrams |