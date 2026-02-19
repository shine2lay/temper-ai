# Product Spec: The Vibe Coding Squad

## Context

We want a real-world demo product that showcases the Temper AI in production. Rather than a throwaway demo, this is a product that **is** the use case: a platform where anyone can submit a suggestion for a product, and a squad of AI agents triages it against the product's vision doc, and if approved, generates the actual code changes and pushes them through CI/CD.

The product dog-foods itself - once live, users submit suggestions about The Vibe Coding Squad itself, and the pipeline processes them.

## Product Overview

**Name:** The Vibe Coding Squad

**Tagline:** Submit a suggestion. The squad vibes it into code.

**What it does:** A public-facing web app where anyone can suggest changes to a product ("move button to the left", "add a page that does X"). A multi-agent pipeline reads the project's vision/guideline doc, triages the suggestion, and if it aligns with the vision and is feasible, generates actual code changes committed to the repo. Users see the full agent discussion and pipeline progress for every suggestion.

**Target users:** Anyone - public, anonymous. No accounts, no stored user data. Content censored if needed.

**Scope:** Single project per instance (one vision doc, one repo, one suggestion board).

## Core Concept

```
User submits suggestion
    ↓
Pipeline reads vision/guideline doc
    ↓
Multi-agent triage:
  - Does this align with product vision?
  - Is it technically feasible?
  - What's the priority/impact?
    ↓
Decision: Approve or Reject (with reasoning referencing the vision doc)
    ↓
If approved:
  - Design spec
  - Generate code changes
  - Commit to branch → Push → CI/CD runs
    ↓
Suggestion board shows full agent discussion + status for every step
```

The **vision/guideline doc** is the source of truth. It defines what the product is, its principles, current goals, and what's out of scope. Every triage decision references it.

## Pages

### 1. Explainer Page
- What is The Vibe Coding Squad
- How it works (visual pipeline diagram)
- The vision doc for this product (public, transparent)
- Link to submit a suggestion
- Link to view the suggestions board

### 2. Submit Suggestion
- Could be a section on the explainer page or a separate page
- Simple text input: "What should we build/change?"
- Optional: category tag (UI, feature, bug, improvement)
- No account required
- Submit triggers the pipeline

### 3. Suggestions Board
- List of all suggestions, newest first
- Each suggestion shows:
  - The suggestion text
  - Status badge: `submitted → triaging → approved/rejected → designing → coding → shipped`
  - Timestamps for each status change
  - Priority label (if approved): P0-P3
- Click into a suggestion to see detail view

### 4. Suggestion Detail (expanded view on board)
- Full suggestion text
- Current status with progress indicator
- **Pipeline Activity Feed** - the key differentiator:
  - Each agent's output shown chronologically with agent name, timestamp, and full reasoning
  - Vision Alignment Agent: "Aligns with X goal because..."
  - Feasibility Agent: "Estimated effort: small. Approach: ..."
  - Priority Agent: "P2 - moderate impact, low effort..."
  - Spec Agent: requirements, acceptance criteria
  - Code Agent: diff/summary of changes made
  - CI/CD status: build passing/failing
- If rejected: clear explanation referencing the vision doc

## Pipeline Design

### Vision Doc
The vision doc is a markdown file in the repo that agents read before every triage. Example structure:

```markdown
# Product Vision: The Vibe Coding Squad

## Core Purpose
A public suggestion board where AI agents triage and build features from user suggestions.

## Principles
- Transparency: every agent decision is visible to the user
- Simplicity: the UI should be dead simple
- Speed: suggestions should be triaged within minutes
- Safety: no user data stored, content moderated

## Current Goals
- Explainer page
- Suggestion submission
- Suggestions board with pipeline visibility
- Triage pipeline (vision alignment, feasibility, priority)
- Code generation for approved suggestions

## Out of Scope
- User accounts / authentication
- Multiple project support
- Payment / monetization
- Mobile app
```

### Pipeline Stages

**Stage 1: Classify & Moderate**
- Single agent
- Classify suggestion: UI change, new feature, bug fix, improvement, other
- Check for spam, offensive content, or nonsensical input
- If spam/offensive → reject immediately with reason
- Output: classification + cleaned suggestion text

**Stage 2: Vision Alignment** (conditional - skip if Stage 1 rejected)
- Single agent reads the vision doc
- Evaluates: Does this align with core purpose? Does it match current goals? Is it explicitly out of scope?
- Output: aligned/not-aligned + reasoning referencing specific sections of the vision doc

**Stage 3: Feasibility & Priority** (conditional - skip if not aligned)
- Parallel agents:
  - **Feasibility agent**: technical complexity, estimated effort (small/medium/large), dependencies, risks
  - **Priority agent**: user impact, alignment strength, effort-to-value ratio, priority label (P0-P3)
- Synthesis: go/no-go recommendation with priority

**Stage 4: Design Spec** (conditional - only if approved)
- Single agent
- Produces: requirements, acceptance criteria, technical approach, files to modify
- Output: structured spec

**Stage 5: Code Generation** (conditional - only if spec approved)
- Agent(s) generate actual code changes based on the spec
- Changes committed to a feature branch
- Push to GitHub → CI/CD runs
- Output: branch name, commit SHA, PR link (if auto-created)

**Stage 6: Status Update**
- Update suggestion status in DB
- Store all agent outputs for the activity feed

### Pipeline in MAF Terms

```yaml
workflow:
  name: suggestion_triage
  description: "Triage and build user suggestions"

  stages:
    - name: classify
      stage_ref: configs/stages/classify_moderate.yaml

    - name: vision_alignment
      stage_ref: configs/stages/vision_alignment.yaml
      conditional: true
      condition: "{{ stage_outputs.classify.stage_status == 'success' }}"

    - name: feasibility_priority
      stage_ref: configs/stages/feasibility_priority.yaml
      conditional: true
      condition: "{{ stage_outputs.vision_alignment.aligned == true }}"

    - name: design_spec
      stage_ref: configs/stages/design_spec.yaml
      conditional: true
      condition: "{{ stage_outputs.feasibility_priority.approved == true }}"

    - name: code_generation
      stage_ref: configs/stages/code_generation.yaml
      conditional: true
      condition: "{{ stage_outputs.design_spec.stage_status == 'success' }}"

  inputs:
    required:
      - suggestion_text
    optional:
      - category
```

## Data Model

### Suggestion
```
id: UUID
text: string
category: string (optional)
status: enum (submitted, triaging, approved, rejected, designing, coding, shipped, failed)
priority: string (P0-P3, null if not yet triaged)
created_at: timestamp
updated_at: timestamp
```

### PipelineEvent
```
id: UUID
suggestion_id: FK → Suggestion
agent_name: string
stage_name: string
event_type: enum (started, output, completed, failed)
content: text (agent's output / reasoning)
created_at: timestamp
```

No user table - anonymous submissions.

## Tech Stack

- **Backend:** FastAPI (Python) - embeds MAF directly
- **Database:** SQLite for v1 (SQLModel/Alembic - already in the framework)
- **Frontend:** TBD (agents decide during build, but likely simple HTML/JS or HTMX)
- **Pipeline:** MAF workflows triggered by API endpoint
- **LLM:** qwen3-next via vLLM (localhost:8000)
- **CI/CD:** GitHub Actions
- **Deployment:** Docker (docker/ already exists in framework)

## Architecture

```
┌─────────────────────────────────────┐
│           Frontend                   │
│  Explainer | Submit | Board         │
│         (static + fetch API)         │
└──────────────┬──────────────────────┘
               │ HTTP
┌──────────────▼──────────────────────┐
│         FastAPI Backend              │
│                                      │
│  POST /api/suggestions   (submit)    │
│  GET  /api/suggestions   (list)      │
│  GET  /api/suggestions/:id (detail)  │
│  GET  /api/suggestions/:id/events    │
│  GET  /api/vision        (vision doc)│
│  WebSocket /ws/suggestions/:id       │
│         (live pipeline updates)      │
│                                      │
│  ┌────────────────────────────────┐  │
│  │   MAF Runtime (embedded)       │  │
│  │   Triggered on POST /suggest   │  │
│  │   Runs pipeline as async task  │  │
│  │   Writes PipelineEvents to DB  │  │
│  │   as each agent produces output│  │
│  └────────────────────────────────┘  │
│                                      │
│  ┌────────────────────────────────┐  │
│  │   SQLite (suggestions + events)│  │
│  └────────────────────────────────┘  │
└──────────────────────────────────────┘
               │
               │ git push (on approved + coded suggestions)
               ▼
┌──────────────────────────────────────┐
│  GitHub Repo → CI/CD (GitHub Actions)│
└──────────────────────────────────────┘
```

## API Design

### POST /api/suggestions
Submit a new suggestion.
```json
Request:  { "text": "Add dark mode toggle", "category": "feature" }
Response: { "id": "uuid", "status": "submitted" }
```
Triggers pipeline asynchronously.

### GET /api/suggestions
List all suggestions with status.
```json
Response: {
  "suggestions": [
    { "id": "uuid", "text": "Add dark mode...", "status": "approved", "priority": "P2", "created_at": "..." },
    ...
  ]
}
```

### GET /api/suggestions/:id
Full suggestion detail.

### GET /api/suggestions/:id/events
Pipeline activity feed for a suggestion.
```json
Response: {
  "events": [
    { "agent_name": "Vision Alignment Agent", "stage_name": "vision_alignment", "content": "Aligns with...", "created_at": "..." },
    ...
  ]
}
```

### WebSocket /ws/suggestions/:id
Live pipeline updates streamed as events happen.

### GET /api/vision
Returns the current vision doc (public transparency).

## Deployment

- **v1:** Docker container running FastAPI + embedded MAF
- **Repo:** New standalone repo (imports MAF as dependency or submodule)
- **CI/CD:** GitHub Actions - lint, test, build Docker image
- **Infra:** Single container, SQLite file volume

## Build Order

### Phase 1: Foundation
1. Create new repo with project structure
2. Write the vision doc for The Vibe Coding Squad
3. Set up FastAPI backend with SQLite (SQLModel)
4. Create data models (Suggestion, PipelineEvent)
5. Implement basic API endpoints (CRUD)
6. Docker + CI/CD setup

### Phase 2: Frontend
7. Explainer page
8. Submit suggestion form
9. Suggestions board (list view)
10. Suggestion detail with pipeline activity feed

### Phase 3: Pipeline
11. Create MAF agents (classifier, vision alignment, feasibility, priority, spec designer)
12. Create MAF stages and workflow config
13. Wire up: POST /suggestions → async MAF pipeline → write events to DB
14. WebSocket for live updates

### Phase 4: Code Generation
15. Code generation agent that reads spec + codebase
16. Git integration: create branch, commit, push
17. CI/CD status tracking

### Phase 5: Polish & Dog-food
18. Submit suggestions about The Vibe Coding Squad itself
19. Watch the pipeline triage and build its own improvements
20. Iterate based on real usage

## Open Questions (for future discussion)

1. **Code generation scope:** How does the code gen agent understand the existing codebase? Does it read all files? A summary? An architecture doc?
2. **Human review:** Should there be a human approval step before code is merged, or fully autonomous?
3. **Rate limiting:** How to prevent spam/abuse on a public anonymous form?
4. **Content moderation:** What level of censoring? Just profanity filter or deeper?
5. **Duplicate detection:** Should the pipeline detect duplicate/similar suggestions?
6. **Suggestion voting:** Should other users be able to upvote suggestions? (adds complexity but good signal)

## Verification

1. Submit a suggestion via the form → appears on the board as "submitted"
2. Pipeline runs → events appear in real-time on the detail page
3. Agent reasoning references the vision doc
4. Approved suggestion → code changes committed to branch → CI/CD runs
5. Rejected suggestion → clear explanation visible on the board
