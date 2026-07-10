# ─────────────────────────────────────────────────────────────────────────────
# Lineage-Aware Memory Governance — Agent Container
# ─────────────────────────────────────────────────────────────────────────────
# Installs Python deps for real_agent/ experiment.
# The project directory is mounted at /workspace via docker-compose volume.
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim

LABEL maintainer="Lineage-Aware Memory Project"
LABEL description="Real-agent sqlglot lineage extraction experiment"

WORKDIR /workspace

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY docker/requirements_agent.txt /tmp/requirements_agent.txt
RUN pip install --no-cache-dir -r /tmp/requirements_agent.txt

# Default command: run experiment in demo mode
# Override in docker-compose or CLI with --llm for full LLM mode
CMD ["python", "-m", "real_agent.experiment"]
