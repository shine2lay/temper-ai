# Product Vision: The Vibe Coding Squad

## Core Purpose
A public suggestion board where AI agents triage and build features from user suggestions.
Users submit a suggestion, a multi-agent pipeline reads this vision doc, triages the suggestion,
and if approved, generates actual code changes.

## Principles
- Transparency: every agent decision is visible to the user
- Simplicity: the UI should be dead simple
- Speed: suggestions should be triaged within minutes
- Safety: no user data stored, content moderated
- Vision-driven: every decision references this document

## Tech Stack
- Backend: FastAPI (Python), SQLite via SQLModel
- Frontend: Simple HTML/CSS/JS (no heavy frameworks)
- Pipeline: MAF workflows triggered by API endpoint
- LLM: qwen3-next via vLLM
- Deployment: Docker

## Current Goals
- Explainer page (what VCS is, how it works, link to submit)
- Suggestion submission (simple text input, no account required)
- Suggestions board (list with status badges, timestamps, priority)
- Suggestion detail with pipeline activity feed (agent reasoning visible)
- Triage pipeline (classify, vision alignment, feasibility, priority)
- Code generation for approved suggestions

## Architecture
- Single FastAPI app embedding MAF runtime
- SQLite database with Suggestion and PipelineEvent tables
- Static frontend served by FastAPI
- WebSocket for live pipeline updates
- All code in a single workspace directory

## Out of Scope
- User accounts / authentication
- Multiple project support
- Payment / monetization
- Mobile app
- Complex frontend frameworks (React, Vue, etc.)
