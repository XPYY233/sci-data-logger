# AGENTS.md

## Read this first

If you are an AI agent working in this repository, **do not start planning or editing extension-related code until you have read**:

1. [`docs/extensions/extension_contract.md`](docs/extensions/extension_contract.md)
2. [`docs/extensions/collaboration_guidelines.md`](docs/extensions/collaboration_guidelines.md)
3. [`docs/architecture.md`](docs/architecture.md)

## Repository rule of thumb

This project currently follows:

> **主干冻结、外挂优先、兼容优先**

Default expectations:

- Do **not** modify `src/sci_data_logger/` unless the user explicitly requests a core change.
- Prefer new work under `extensions/<domain>/`.
- Keep extensions independently testable and documented.
- Preserve loose coupling between extensions.
- Before finishing, check whether `README.md` or extension docs also need updates.

## Before you implement

Make sure you can answer:

1. Which extension owns this work?
2. Can it be completed without changing the frozen core?
3. What public entrypoint, config, tests, and docs should accompany it?
4. How will it remain compatible with other agents' work?

If the task touches `extensions/`, the authoritative detailed rules live in:

- [`docs/extensions/extension_contract.md`](docs/extensions/extension_contract.md)

