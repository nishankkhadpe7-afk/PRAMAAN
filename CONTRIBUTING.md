# Contributing to PRAMAAN

Thanks for helping. PRAMAAN supports auditors in a regulated field, so changes are judged first on whether they keep its claims true: every number traceable to a source record, nothing invented, and the final decision left to a human.

## Ground rules

1. **No mock implementations to make tests pass.** A test that passes only because the code fakes the behaviour is a bug.
2. **Do not remove features or weaken safeguards** (role checks, human-only decisions, append-only history, amount screening for AI text) without an explicit discussion first.
3. **Keep existing data safe.** Schema changes must be additive and reversible; never rewrite or delete stored records or vault files.
4. **Never commit secrets or real client data.** Use the synthetic fixtures. `.env`, `.demo/` and AI coding-tool folders are git-ignored; the Secret scan workflow checks every push.
5. **Say what you measured.** Claims in docs or the UI need a test or an evaluation behind them, and limitations stay written down.

## Setup

Follow the [Quick start](README.md#quick-start), or run `START_PRAMAAN.bat` (Windows) / `./run-local.sh` (macOS, Linux) once to create the environment. The code imports itself as `Pramaan.backend`, so put the `launcher/` folder on `PYTHONPATH` first:

```powershell
$env:PYTHONPATH = "$PWD\launcher"        # PowerShell
export PYTHONPATH="$PWD/launcher"        # bash / zsh
```

## Checks to run before a pull request

```powershell
.\.venv-p4\Scripts\python.exe -m pytest backend/tests -q    # backend
cd web
npm run typecheck
npm test                                                   # UI unit tests (vitest)
npm run build
npm run test:e2e                                           # browser journeys + 360 px overflow check
```

If you change the investigation agent, also run `python -m Pramaan.backend.evaluate_agent` (offline baseline). If you have an LLM key, run `--planner llm --repeats 5` as well, and report the numbers in the pull request.

## Code conventions

- **Backend:** FastAPI routes must have a `name` that maps to an action in `backend/security.py`. A new route without a permission entry is refused by design, and `tests/test_route_resolution.py` checks the mapping.
- **Frontend:** React + TypeScript. Reuse the shared components (`components.tsx`, `ui.tsx`), the spacing and type tokens in `styles.css`, and the plain-language glossary in `glossary.tsx` (use `<Term k="…">` for audit vocabulary instead of writing new explanations). New screens need keyboard access and no axe violations.
- **AI text:** anything a model writes is shown labelled as AI and screened; never display a model-supplied amount.
- **Line endings:** the repository is edited on Windows and Linux; keep each file's existing line endings.

## Commits and pull requests

- Use short, imperative commit subjects with a type prefix, as in the existing history: `fix(agent): …`, `ui: …`, `docs: …`, `test: …`, `security: …`, `chore: …`.
- One topic per pull request. Describe what changed, why, and how you verified it (commands and results).
- Update `CHANGELOG.md` under **Unreleased** for anything a user or reviewer would notice.

## Reporting security problems

Please do not open a public issue; see [SECURITY.md](SECURITY.md).

## License

By contributing you agree that your contribution is licensed under the [AGPL-3.0-only](LICENSE) license of this project.
