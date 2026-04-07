# Temper AI Dashboard

The Temper AI dashboard — a React single-page application for monitoring, debugging, and designing multi-agent workflows.

## Tech Stack

- **React 19** + TypeScript 5.9
- **Tailwind CSS 4.1** + Shadcn/ui (Radix primitives)
- **React Flow** — DAG visualization
- **Zustand + Immer** — state management
- **TanStack React Query** — server state
- **Vite** — build tool

## Development

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173 (proxied to backend on :8420)
```

## Build

```bash
npm run build    # outputs to dist/
```

The backend serves `dist/` as static files at `/app/*`.

## Structure

```
src/
  pages/           # Route-level components (WorkflowList, ExecutionView, StudioView, etc.)
  components/      # Feature-grouped components
    dag/           # DAG visualization (StageNode, AgentNode, edges)
    layout/        # App shell (Sidebar, Header, Tabs, Panels)
    studio/        # Workflow designer (Canvas, Palette, Properties, Editors)
    docs/          # Config reference docs
    shared/        # Reusable primitives (StatusBadge, EmptyState, ThemeToggle)
    ui/            # Shadcn/ui components
  hooks/           # Custom hooks (useConfigAPI, useDagElements, useDocsAPI)
  store/           # Zustand stores (executionStore, designStore)
  lib/             # Utilities (constants, utils, dagLayout, theme)
```
