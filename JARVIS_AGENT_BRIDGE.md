# Jarvis / MS Football Agent Bridge

This branch adds a local, authenticated bridge so Jarvis can understand and
operate the real MS Football application without requiring one hard-coded
function for every natural-language request.

## What the bridge exposes

Read/discovery tools:

- `list_capabilities`: project apps/models and bridge capabilities.
- `describe_schema`: live Django model/field/relation/choice discovery.
- `query_records`: generic read-only Django ORM queries.
- `run_readonly_sql`: one read-only SELECT/CTE query for complex analysis.
- `search_code`: local source search with credential assignments redacted.
- `list_routes`: live Django URL/view discovery.

Controlled write tools:

- `prepare_mutation`: builds a preview for create/update/delete and returns a
  short-lived `change_id`; it never changes the database.
- `commit_mutation`: applies the prepared change. Jarvis gates this tool
  behind an explicit user confirmation.

The bridge intentionally does not expose authentication passwords, session
data, API keys or source-code credential assignments.

## Start locally

Use the same strong random token in the MS Football process and Jarvis. Keep it
in local environment variables only.

PowerShell:

```powershell
$env:JARVIS_MS_FOOTBALL_BRIDGE_TOKEN="<strong-random-token>"
python manage.py run_jarvis_bridge
```

Default address:

```text
http://127.0.0.1:8765
```

It binds to loopback only by default. Do not expose the bridge directly to the
public internet. If remote access is added later, place it behind an
authenticated private tunnel/MCP gateway.

## Example agent flow

User:

```text
Combien reste-t-il à payer pour le joueur X ?
```

Agent:

```text
describe_schema
-> discovers Player / Video / Invoice / Payment relations
query_records or run_readonly_sql
-> reads real data
-> answers from the database
```

User:

```text
Passe cette vidéo au statut livré.
```

Agent:

```text
search_code / list_routes
-> understands existing delivery workflow and side effects
prepare_mutation (fallback only if no business action is available)
-> preview
Jarvis asks the user for confirmation
commit_mutation
-> real write
```

For workflows with side effects such as email, WhatsApp, automation pipelines,
payment logic or delivery logic, the agent should inspect the existing code and
routes first. A raw database write is not automatically equivalent to executing
the application's business workflow.

## Security note

Production secrets must be supplied through environment variables. This branch
removes committed fallback credentials from settings, but credentials that were
ever committed remain in Git history and must be rotated separately.
