# Docker Quickstart — Lineage-Aware Memory Governance

## Demo mode (no Ollama, runs in ~5 seconds)

```bash
cd Lineage-Aware-Memory

# Build the agent image
docker compose -f docker/docker-compose.yml build agent

# Run experiment (downloads Northwind DB automatically on first run)
docker compose -f docker/docker-compose.yml run --rm agent
```

Results are written to `experiments/` on your host (volume-mounted).

---

## LLM mode (real Ollama agent generates SQL)

```bash
# Start Ollama server
docker compose -f docker/docker-compose.yml up ollama -d

# Wait for it to be healthy (~10s), then pull a model
docker compose -f docker/docker-compose.yml exec ollama ollama pull llama3.2:3b

# Run experiment with LLM
docker compose -f docker/docker-compose.yml run --rm agent --llm

# Use a different model
OLLAMA_MODEL=phi3:mini docker compose -f docker/docker-compose.yml run --rm agent --llm
```

Recommended models (sorted by size):
| Model | Size | SQL capability |
|-------|------|----------------|
| `qwen2.5:3b` | ~2 GB | Good |
| `llama3.2:3b` | ~2 GB | Good |
| `phi3:mini` | ~2.2 GB | Decent |
| `llama3.1:8b` | ~5 GB | Best |

---

## Running without Docker

```bash
# Install deps
pip install sqlglot requests

# Run demo (no Ollama)
python -m real_agent.experiment

# Run with LLM (requires Ollama running locally)
pip install langchain langchain-community langchain-ollama
ollama pull llama3.2:3b
python -m real_agent.experiment --llm --model llama3.2:3b
```

---

## Output files

After the experiment completes:

```
experiments/
├── exp6_real_agent_results.json   # raw results (all round-trips)
└── exp6_real_agent_report.md      # detailed Markdown proof document
```
