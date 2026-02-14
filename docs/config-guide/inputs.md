# Input Files

Input files provide data to workflows at runtime. They are simple YAML key-value files matching the workflow's `inputs.required` fields.

**Location:** `examples/*.yaml`

## Usage

```bash
maf run configs/workflows/simple_research.yaml --input examples/research_input.yaml
```

## Examples

### Research Input

```yaml
# examples/research_input.yaml
topic: "Artificial Intelligence in Healthcare"
focus_areas:
  - "Medical diagnosis"
  - "Drug discovery"
  - "Patient care automation"
depth: "medium"
```

### Decision Input

```yaml
# examples/demo_input.yaml
question: "Should we launch the product now or wait?"
options:
  - "Launch Now"
  - "Wait 1 Month"
  - "Beta Launch"
context: "Product is 90% ready, some bugs remain"
```

### Debate Input

```yaml
# examples/debate_demo_input.yaml
question: "What is the best approach to AI safety?"
options:
  - "Alignment research"
  - "Regulation"
  - "Open source"
context: "Growing public concern about AI capabilities"
```

### Technical Problem Input

```yaml
# examples/technical_problem_demo_input.yaml
problem_description: |
  Design and implement a distributed rate limiter
  for a high-traffic API service handling 1M+ req/s

technical_context: |
  Current architecture:
  - Microservices on Kubernetes
  - Multi-region deployment
  - Redis for caching

success_criteria: |
  Performance metrics:
  - P99 latency: < 5ms overhead
  - Throughput: 1M+ requests/second
  - Availability: 99.99%
```

### ERC721 Smart Contract Input

```yaml
# examples/erc721_input.yaml
contract_name: "SimpleNFT"
token_name: "SimpleNFT"
token_symbol: "SNFT"
llm_model: "llama3:8b"
```

## Structure Rules

- Keys must match the workflow's `inputs.required` list
- Optional keys from `inputs.optional` can be included or omitted
- Values can be strings, lists, dicts, numbers, or multi-line strings (using `|`)
- No schema validation on input files themselves — validation happens when the workflow processes them
- Jinja2 defaults in stage configs handle missing optional inputs:
  ```yaml
  depth: "{{ workflow.inputs.depth | default('medium') }}"
  ```
