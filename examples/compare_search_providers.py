#!/usr/bin/env python3
"""Compare search providers (Tavily vs SearXNG) for market research workflows.

This script prints instructions for running the market research workflow
with each search provider and comparing results.
"""


def main() -> None:
    print("=" * 70)
    print("Search Provider Comparison: Tavily vs SearXNG")
    print("=" * 70)

    print("""
PREREQUISITES
-------------
- vLLM running on http://localhost:8000 with qwen3-next
- For Tavily: TAVILY_API_KEY environment variable set
- For SearXNG: Docker container running (see docker/searxng/)

STEP 1: Run with Tavily (default)
----------------------------------
The default market_researcher agent config uses TavilySearch.

    maf run configs/workflows/market_research.yaml \\
        --input examples/market_research_input.yaml \\
        --show-details

STEP 2: Run with SearXNG
-------------------------
Edit configs/agents/market_researcher.yaml and change the tools section:

    tools:
      - SearXNGSearch
      - WebScraper

Make sure SearXNG is running:

    cd docker/searxng && docker compose up -d

Then run the same workflow:

    maf run configs/workflows/market_research.yaml \\
        --input examples/market_research_input.yaml \\
        --show-details

STEP 3: Compare results
------------------------
Compare the two runs on:
  - Result quality and relevance
  - Number of sources found
  - Response latency
  - Source diversity

KEY DIFFERENCES
---------------
  Tavily:
    + Higher quality search results (AI-optimized)
    + Built-in content extraction
    - Requires API key
    - Usage limits on free tier

  SearXNG:
    + Self-hosted, no API key needed
    + No usage limits
    + Privacy-preserving (no tracking)
    - Requires Docker setup
    - Results depend on upstream engine availability
""")


if __name__ == "__main__":
    main()
