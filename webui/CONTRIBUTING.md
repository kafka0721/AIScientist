# Contributing to imaging_scientist WebUI

We appreciate your interest and the time you spend helping improve the imaging_scientist WebUI. Please read the following guidelines before contributing.

## How you can contribute

- **Report bugs and request features:** open an issue describing the problem, steps to reproduce, and your environment (Node version, backend version).
- **Propose design changes:** use issues to outline the problem, alternatives, and trade-offs before implementing.
- **Contribute code or docs:** submit PRs that address an open issue, with a clear rationale.

## The zero-touch-backend principle

> [!IMPORTANT]
> The WebUI is a **runtime client only**. It must work against an unmodified imaging_scientist backend — it talks to a running deployment over the LangGraph SDK and thin same-origin `/api/` routes, and never requires changes to the imaging_scientist repo. Keep all new features within this constraint (the one sanctioned exception, the `webui` launch mode, already lives in imaging_scientist).

## Prerequisites

- **Node.js 20+**.
- A running **imaging_scientist backend** (the LangGraph deployment). From your imaging_scientist install:
  ```bash
  WitAISci deploy        # serves the LangGraph API at http://127.0.0.1:6174
  ```
  Keep it running in its own terminal.

## Development setup

1. **Fork and clone** the repository:

   ```bash
   git clone https://github.com/<your-username>/imaging_scientist-WebUI.git
   cd imaging_scientist-WebUI
   ```

2. **Install dependencies** (package manager is **npm**):

   ```bash
   npm install
   ```

3. **Start the dev server:**
   ```bash
   npm run dev
   ```
   Open <http://localhost:4716>. In the configuration dialog, enter your **Deployment URL** (default `http://127.0.0.1:6174`) and click **Save**.

> You need two things running: the imaging_scientist backend (`WitAISci deploy`, port `6174`) and this UI (`npm run dev`, port `4716`).

## Scripts

| Command                | Description                             |
| ---------------------- | --------------------------------------- |
| `npm run dev`          | Start the dev server on port 4716       |
| `npm run build`        | Production build + assemble `dist/`     |
| `npm start`            | Serve the production build on port 4716 |
| `npm run start:dist`   | Run the assembled standalone `dist/`    |
| `npm run lint`         | Lint with ESLint                        |
| `npm run lint:fix`     | Lint and auto-fix                       |
| `npm run format`       | Format with Prettier                    |
| `npm run format:check` | Check formatting (used in CI)           |

## Production build

```bash
npm run build        # next build + assemble standalone into dist/
npm start            # serves the production build on http://localhost:4716
```

## Project structure

```txt
imaging_scientist-WebUI/
  bin/                       # npx launcher (witaiscientist-webui.mjs → dist/server.js)
  scripts/                   # assemble-standalone.mjs (packs dist/, strips *.map)
  src/
    app/
      api/                   # thin same-origin server routes (browser → local disk)
        witaisci-config/       #   detect backend port from imaging_scientist config
        skills/              #   list / install / uninstall + remote EvoSkills catalog
        memory/              #   global memory CRUD + observation graph + executions
        workspace/           #   browse / read / edit / upload / download-zip files
      components/            # feature UI: chat, inspector, memory, schedule, skills, dialogs
      hooks/                 # useChat, useThreads, useAsyncAgents, useScheduledTasks,
                             #   useAvailableModels, useMemoryActivity, useAutoNotify
      page.tsx               # three-column shell (thread · chat · inspector); nuqs routing
    components/ui/            # shared shadcn/ui primitives
    lib/                     # client helpers (asyncAgents, cronUtils, modelCommand,
                             #   observationGraph, fileLink, summarization, …)
      server/                # server-only fs helpers (workspace / memory / skills) w/ path guards
    providers/               # ClientProvider (SDK) · ChatProvider · ThemeProvider
```

## Architecture & connection contract

Three independent layers:

1. **Frontend** (Next.js standalone, port `4716`) — browser connects directly to the LangGraph backend; pure client-side chat + streaming.
2. **Next `/api/` routes** (server tool layer, same-origin) — the reason distribution is `output: "standalone"` rather than a static export.
3. **Backend** (imaging_scientist's `langgraph dev`, default port `6174`) — the anchor process: runs async agents, holds state, serves the SDK.

The backend exposes graphs `imaging_scientist` (main, UI-locked), `writing-agent`, `data-analysis-agent`, the `scheduler` graph (LangGraph crons behind **Scheduled Tasks**), and the `evomemory` workers. The UI filters thread lists by `metadata.graph_id == "imaging_scientist"` so worker/sub-agent threads stay hidden.

## Code style

- **TypeScript** — keep `npm run lint` (ESLint) clean and run `tsc --noEmit` before pushing.
- **Formatting** — `prettier --check .` must pass (run `npm run format` to fix).
- **Tailwind gotcha:** this project's `tailwind.config.mjs` overrides named tokens like `bg-primary`/`text-primary` to undefined LangSmith vars, so those classes render transparent. Use arbitrary values such as `bg-[var(--brand-solid)]` instead, and never apply a `/NN` opacity modifier to a `var()`-based color (it silently drops the declaration).
- Follow the existing patterns and conventions in the area you're modifying; keep changes minimal and focused.

## Submitting a pull request

1. Create a branch from `main` with a descriptive name (e.g. `fix/stream-tail`, `feat/command-palette`).
2. Make your changes, keeping commits focused. Use semantic prefixes: `fix:`, `feat:`, `docs:`, `chore:`, `refactor:`.
3. Ensure `npm run lint`, `tsc --noEmit`, and `npm run format:check` pass locally — these also run in CI.
4. Open a PR against `main` describing what changed and why. Include screenshots or screen recordings for any UI change.
5. A maintainer will review your PR. Please be responsive to feedback.

## Need help?

Open an [issue](https://github.com/WitAIScientist/WitAIScientist-WebUI/issues) if you have a question or run into a problem.
