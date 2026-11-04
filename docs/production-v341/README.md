# Production recovery baseline — v341 / Extension24

This branch is a **source recovery snapshot**, not a deployment instruction.

- Production current release: v341; code released in v340.
- Slug: `666c5b21-df45-4e3b-97a8-10c73a0b0df1`.
- Original slug archive SHA256: `ef295e778af90d52efb91427c9b7cdef057c79305572800c382eddf071bb32d7`.
- Slug commit label `56cbd3261cf749872106fbda0e2b86b0f3a22405` is a delivery content label, **not a Git commit**.
- All 331 application/source files recovered from the exact retained archive; all reader/action runtime hashes verified against the deployed manifest.
- `SOURCE-MANIFEST.json` contains original hashes, the 24 contracts and every exclusion.

## One approved security difference

`gestion_joueurs/telegram_bot.py`: the hardcoded Telegram credential was replaced with `os.environ["TELEGRAM_BOT_TOKEN"]`. No other original application bytes were changed. **This variable has NOT been configured on Heroku.** Before any future worker activation/deployment, handle the credential separately with explicit authorization. The currently stopped worker was not started. The historical exposed credential has NOT been rotated or removed from old Git history.

## What is intentionally not in Git

Environment files (including inherited `.env` files), SQLite database, scheduler state, voice recording, bytecode, Python/buildpack/vendor runtime and generated staticfiles. The original full archive remains private locally. Existing legacy modules are preserved without activation or endorsement. No GitHub-only legacy files have been silently mixed into the production tree; the parent commit retains their history.

## Preserve the running service during future development

Develop from this branch, not from the older master tree. Keep `actions/`, `data_access/`, their migrations, the `actions.mount` middleware and settings/URL mounting. Preserve approval HMAC, actor/scopes/permissions, PRE/POST verification, plan digests, idempotency, quota and fail-closed behavior. Existing plans, audits, actor permissions and credentials live in the production database/configuration, not in Git. Hermes client plugins are installed separately and were not modified.

Heroku remains linked to `master`, with automatic deployment disabled at snapshot time. This branch was not linked, merged or deployed. Before a later deployment, review diff, dependencies and migration plan; retain Config Vars and database, run isolated qualification, and obtain deployment authorization. A source snapshot is not a proof that a fresh build reproduces every binary dependency of the current slug. The inherited requirements remain unchanged.

## Provenance distinction

The qualification manifest's `applicationInventory` lists 209 files. Its documentation file `data_access/ACCESS.md` is absent from the actual deployed slug; the other 208 entries match. It was not fabricated or added to this runtime-source snapshot. All 35 entries in the separate `runtimeSources` manifest match. The private audit initially covered 330 source files; the final snapshot additionally restores the credential-free `.env.automation.example` template (331 source files), without changing application code.

## Verification scope

Exact original archive hash; full recovered source hash/mode inventory; reader/action runtime hash equality; all 24 contract names present; AST parsing without importing application code; actual publication-byte credential scan; Git tree/blob readback; official Heroku release/slug/formation/configuration hash and GitHub linkage comparison before/after. No live business request or database access is needed or performed for this backup.
