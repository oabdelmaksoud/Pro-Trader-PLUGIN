FROM python:3.12-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl && rm -rf /var/lib/apt/lists/*

# Install Node 22+ for openclaw (optional)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y nodejs && rm -rf /var/lib/apt/lists/*

# Install openclaw CLI (optional — graceful degradation if unavailable)
RUN npm install -g openclaw@latest 2>/dev/null || echo "openclaw install skipped"

# Copy and install Python package
COPY pyproject.toml .
COPY pro_trader/ pro_trader/
COPY tradingagents/ tradingagents/
COPY cli/ cli/
COPY config/ config/
COPY scripts/ scripts/

RUN pip install --no-cache-dir ".[all]"

# Create logs directory
RUN mkdir -p logs

# Environment
ENV PYTHONUNBUFFERED=1
ENV PROTRADER_LLM_PROVIDER=anthropic

EXPOSE 8002

CMD ["pro-trader", "monitor", "check"]
