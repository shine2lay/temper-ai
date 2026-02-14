# SearXNG for MAF

Local SearXNG instance providing privacy-preserving web search for the Meta-Autonomous Framework.

## Quick Start

```bash
cd docker/searxng
docker compose up -d
```

SearXNG will be available at `http://localhost:8888`.

## Verify

```bash
# Check the service is running
curl "http://localhost:8888/search?q=test&format=json" | python3 -m json.tool | head -20
```

## Configuration

- **Port**: 8888 (mapped from container port 8080)
- **Engines**: DuckDuckGo, Brave, Wikipedia
- **API format**: JSON enabled (required for `SearXNGSearch` tool)

Edit `settings.yaml` to add or remove search engines. Changes require a container restart:

```bash
docker compose restart
```

## Stop

```bash
docker compose down
```

## Usage with MAF

The `SearXNGSearch` tool connects to `http://localhost:8888` by default. To use it in a workflow:

1. Start SearXNG (see Quick Start above)
2. Set `tools: [SearXNGSearch]` in your agent config
3. Run the workflow:

```bash
maf run configs/workflows/market_research.yaml --input examples/market_research_input.yaml --show-details
```
