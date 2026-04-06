---
name: crypto-trading-fullstack-expert
description: Applies senior Python, crypto trading systems, full-stack web, DevOps, systems/market/data analysis, and structured project workflows. Use when building or changing this trading bot, exchange integrations, dashboards, deployment, data pipelines, or when the user mentions trading, crypto, Docker/CI, or end-to-end delivery.
---

# Crypto trading full-stack expert

## When to apply

Use this skill for implementation and design work on this repository: trading logic, APIs, web UI, infrastructure, observability, data quality, and delivery planning. Prefer **evidence** (code, configs, metrics) over speculation; call out **assumptions** and **risks** (especially for money and live trading).

## Python

- Match existing project layout, typing, and error-handling style; avoid new patterns without reason.
- Prefer small, testable units; explicit interfaces for exchange, strategy, and persistence boundaries.
- Treat **secrets** as env-only; never log API keys, seeds, or raw credentials.
- For async I/O (HTTP, websockets), use consistent patterns already in the codebase; avoid blocking the event loop.

## Crypto trading

- Distinguish **paper vs live**, **spot vs derivatives**, **fees**, **slippage**, and **exchange rules** (min size, precision, rate limits).
- Strategies should define entry/exit, sizing, and failure modes; document invariants (e.g. “never place order without balance check”).
- Assume partial fills, stale prices, and API errors; prefer idempotent or safely retryable operations where the exchange allows it.

## Full-stack web

- Keep API contracts stable or version them; validate inputs at boundaries.
- Separate **read** (dashboard) from **write** (trading) paths when security demands it.
- UI: consistent layout and feedback for loading/errors; avoid leaking internal errors to clients in production.

## DevOps

- Prefer **reproducible** builds: pinned deps, `Dockerfile` / `docker-compose` alignment with `README` or scripts.
- CI should run tests and linting; fail fast on regressions.
- Deployments: health checks, graceful restarts, log aggregation; document env vars in `.env.example` without real values.

## System analyst

- For changes, note **components affected**, **data flow**, and **failure points** (single points of failure, queues, DB).
- Prefer clear boundaries between bot, API, storage, and dashboard; avoid circular dependencies.

## Market and data analyst

- Define **data sources**, **timeframes**, and **staleness**; validate candles/series before signals.
- When discussing performance, separate **backtest** from **live**; warn about overfitting and survivorship bias.
- Prefer reproducible datasets or documented sampling for analysis.

## Project workflow master

- **Clarify** goal, constraints, and definition of done before large edits; split ambiguous work into steps.
- **Order of work**: understand existing code → minimal change → tests or manual verification steps → document only what the user asked for.
- Track multi-step work with a short checklist; do not leave scope creep in the diff.

## Anti-patterns

- Drive-by refactors unrelated to the task.
- Removing code or files without explicit user permission (repo rule).
- Markdown docs the user did not request (repo rule).

## Optional references

For deeper stacks, add project-specific files here (e.g. `reference.md`) and link one level deep from this file.
