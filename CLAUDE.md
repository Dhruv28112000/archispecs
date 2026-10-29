# CLAUDE.md — ArchiSpec

## What we are building
ArchiSpec is an autonomous agent that turns a Business Requirement Document (PDF) into:
1. An executive summary + critical missing-gaps alert
2. An editable architecture diagram (`.drawio`)
3. INVEST user stories with Gherkin acceptance criteria and Fibonacci story points (Jira-importable CSV)

Hackathon build: **4 hours, 5 people**. Optimise for a working end-to-end demo over completeness.
Demo must show 6 steps: User Goal → Plan → Skill → Memory → MCP/Tool → Output.

## Tech stack (do not add dependencies without asking)
- Python 3.11+
- LLM: Google Gemini via native SDK `google-genai` (primary), Ollama via `ollama` (fallback)
- Schemas: Pydantic v2
- PDF: PyMuPDF (`import pymupdf`; the `fitz` alias is deprecated). Extract text without ligatures:
  `page.get_text(flags=pymupdf.TEXTFLAGS_TEXT & ~pymupdf.TEXT_PRESERVE_LIGATURES)`
- MCP: official `mcp` Python SDK **v1 (`mcp<2`)** — `FastMCP` server, stdio client (v2 renamed FastMCP → MCPServer)
- UI: Streamlit
- Validation: `gherkin-official`
- Config: `python-dotenv`
- Memory / vector DB: ChromaDB (`chromadb`), local `PersistentClient`, default local embedding function

## Repo structure
```
app.py                  # Streamlit UI
agent.py                # orchestrator: ingest → plan → memory → skills → validate → tools → bundle
llm.py                  # generate_json(prompt, schema) with cache, retry/backoff, Ollama fallback
schemas.py              # Pydantic contracts (single source of truth)
validators.py           # deterministic checks
prompts/planner.md
prompts/gaps_stories.md
prompts/architect.md
mcp_server/server.py    # FastMCP: query_enterprise_memory, generate_drawio_diagram, export_sprint_backlog,
                        #   save_feedback, save_run (tools return dict[str, Any] -> read result.structuredContent)
mcp_server/drawio.py    # Architecture JSON → draw.io XML (deterministic grid layout)
memory/seed_data.json   # human-editable seed content (source of truth for seeding)
memory/store.py         # Chroma wrapper: get_constraints(), search(), add_feedback(), add_run()
memory/seed_memory.py   # (re)builds the Chroma DB from seed_data.json
memory/chroma/          # Chroma persistent storage (git-ignored, rebuilt by seed script)
samples/                # synthetic BRD PDF(s)
outputs/                # generated files (git-ignored)
.cache/                 # LLM response cache (git-ignored)
```

## Data contracts (schemas.py) — keep FLAT (Gemini supports a JSON Schema subset)
Enum-like fields (Gap.category, Gap.severity, Component.tier) are `Literal[...]`.
- `PlanStep`: id:int, title:str, purpose:str, executor:str  (skill or tool name)
- `Plan`: steps: list[PlanStep]
- `Gap`: id:str ("GAP-01"), title, category ("NFR"|"Security"|"EdgeCase"|"Compliance"), severity ("High"|"Medium"|"Low"), reason, suggested_requirement, source_section:str ("not stated" if absent)
- `GapList`: gaps: list[Gap]
- `UserStory`: id ("US-01"), title, as_a, i_want, so_that, gherkin:str (full Feature/Scenario text), story_points:int, linked_gaps: list[str], compliance_tags: list[str]
- `StoryList`: stories: list[UserStory]
- `Component`: id, name, tech, tier ("Client"|"Edge"|"Service"|"Data"|"Messaging"|"External"), requirements: list[str]
- `Connection`: source, target, label
- `Architecture`: components: list[Component], connections: list[Connection]
- `Memory`: approved_stack: list[str], compliance_rules: list[str], estimation_scale: list[int], feedback: list[str]
  (assembled from Chroma by `memory/store.py`; agents and validators only see this Pydantic object)

## Memory design (ChromaDB)
Note: Pydantic models in `schemas.py` remain the data contracts. Chroma stores memory *records*,
each with a fixed metadata schema, and provides semantic search.

**Collection `enterprise_memory`** — one document per memory item
| metadata field | values |
|---|---|
| `type` | `stack` \| `compliance` \| `estimation` \| `pattern` \| `feedback` |
| `domain` | e.g. `payments`, `privacy`, `general` |
| `key` | short id, e.g. `pci-tokenise`, `stack-redis` |
| `source` | `seed` \| `user_feedback` |
| `created_at` | ISO timestamp |
| `name` | stack records only: display name used for `Memory.approved_stack` (e.g. `PostgreSQL`) |
Document text = the rule/pattern in plain language (this is what gets embedded).

**Collection `past_runs`** — one document per approved story or gap from previous runs
metadata: `run_id`, `kind` (`story`|`gap`), `domain`, `created_at`; document = title + description.

**Two access modes (important):**
1. **Deterministic lookup** for hard constraints — `collection.get(where={"type": "stack"})` etc.
   Used to build the `Memory` object for validators (approved stack, Fibonacci scale). Never rely on similarity search for these.
2. **Semantic search (RAG)** for guidance — `collection.query(query_texts=[...], n_results=5, where={"type": {"$in": ["compliance","pattern","feedback"]}})`
   using BRD goals/gap titles as queries. Results are injected into skill prompts with their `key` so outputs can cite them.

**Rules**
- Use Chroma's default local embedding function (no data sent to external embedding APIs).
- Stable IDs (`key`) so re-seeding upserts instead of duplicating.
- `save_feedback` adds a `type=feedback` record; the next run retrieves it via semantic search.
- After a successful run, store approved gaps/stories in `past_runs` (enables "similar past stories" reuse).

**store.py API:** `get_constraints() -> Memory`, `search(queries, n=5)` (top n per query, merged, deduped,
sorted by cosine distance; dicts with key/type/domain/text/distance), `search_past(queries, n=3)`,
`add_feedback(text) -> key`, `add_run(run_id, gaps, stories) -> count`, `upsert_records(records)`, `reset()`.
The estimation scale is parsed from the JSON list inside the `estimation` record text.

## Agent flow (agent.py)
1. `ingest(pdf_path) -> str` — extract text with PyMuPDF
2. `make_plan(brd_text, memory) -> Plan` — 4 stages; UI shows it and waits for Approve.
   Stages/executors: ① `query_enterprise_memory` ② `gaps_and_stories` ③ `architect` ④ `validate_and_export`
3. `query_enterprise_memory` via MCP — returns hard constraints (deterministic) + top semantic matches
   for the BRD's goals (RAG) + similar past stories; show the call and retrieved `key`s in the step log
4. `gaps_and_stories(brd_text, memory) -> GapList, StoryList` — stories generated in batches of 3–5
5. `architect(brd_text, memory, gaps) -> Architecture` — approved stack ONLY
6. `validate(...)` — on failure send errors back to the LLM once, then flag remaining issues
7. MCP `generate_drawio_diagram` and `export_sprint_backlog`
8. Write `outputs/summary.md`; save user feedback to memory

The agent emits step events (`step`, `status`, `detail`) so the UI can show a live log.
Tool calls are **driven by code**, not by the LLM choosing tools.

**agent.py API (for the UI):** `plan_run(pdf, on_event) -> Plan`, `execute_run(pdf, plan, on_event) -> dict`
(keys: run_id, title, plan, memory, gaps, stories, architecture, flags, paths{summary,drawio,backlog}),
`save_feedback(text) -> {key}`. Events: `on_event(step, status, detail)`; status ∈ start|done|info|warning|error;
MCP calls use step `mcp:<tool>`; LLM provider/retry/fallback lines arrive as step `llm`.
Stories: 3 batches × 4 (US-01..US-12) + one coverage batch if a High gap is still unlinked.
A full run costs ~7–9 LLM calls; every successful call is cached, so a failed run resumes from cache.
Gemini free tier allows only ~20 requests/day per model — pre-warm the cache, never clear it before the demo.
**Cache gotcha:** prompts include memory (feedback + similar past items), so `save_run`/`save_feedback`
change the next run's prompts → cache misses → fresh LLM calls. After pre-warming, do not save runs/feedback
before the demo (or reset with `seed_memory.py --reset` and re-run once).

## Prompt conventions (prompts/*.md)
- Each prompt file is the `system` message. The `user` message is built from labelled blocks:
  `BRD:` text, a `MEMORY CONTEXT` block (`APPROVED STACK:`, `ESTIMATION SCALE:`, `RULES:` lines as
  `- [key] (type) text`), and where needed `GAPS:` (GapList JSON) and `STORY IDS:`.
- gaps_stories.md serves two calls: user message starts with `TASK: gaps` (→ GapList) or `TASK: stories` (→ StoryList).
- Outputs cite memory keys: gaps via `(applied: key)` in suggested_requirement, stories via `compliance_tags`,
  components via `applied: key` in `requirements`.
- `python tests/run_prompts.py` runs all prompts on the sample BRD (reference for message building).

## LLM rules (llm.py)
- Single entry point: `generate_json(system: str, user: str, schema: type[BaseModel]) -> BaseModel`
- Gemini: `response_mime_type="application/json"`, `response_schema=schema`, temperature 0.2
- Model name from env `LLM_MODEL`; key from env `GEMINI_API_KEY`
- Provider chain from env `LLM_PROVIDER`: `gemini` (default; Gemini → Ollama fallback) or `ollama` (Ollama only,
  no Gemini key needed). Ollama: `OLLAMA_HOST`, `OLLAMA_MODEL`, optional `OLLAMA_API_KEY` (sent as
  `Authorization: Bearer` — only for remote/cloud hosts), `OLLAMA_NUM_CTX` (default 16384; Ollama's default
  context truncates our prompts silently)
- Cache: hash(system+user+schema name) → `.cache/<hash>.json`; return cached if present
- Retry on 429/5xx with exponential backoff (max 3); on any remaining Gemini error (incl. 4xx such as a bad model name)
  fall back to Ollama (`OLLAMA_MODEL`, `OLLAMA_HOST`, `format=schema.model_json_schema()`, `think=False`)
- Raises `llm.LLMError` if all providers fail; logs the answering provider (`cache`|`gemini`|`ollama`) on logger `archispecs.llm`
- Temperature from env `LLM_TEMPERATURE` (default 0.2)
- Always validate with Pydantic; one repair retry with the validation error appended

## Validators (validators.py)
- story_points ∈ memory.estimation_scale
- gherkin parses with `gherkin-official` and contains Given/When/Then
- every Component.tech ∈ memory.approved_stack (external systems allowed only in tier "External")
- every High-severity gap is referenced by ≥1 story
- returns `list[str]` of human-readable errors, each prefixed with the story/gap/component id
- API: `validate(gaps, stories, arch, memory)` (all checks), `validate_stories(stories, gaps, memory)`
  (for the story repair loop), plus `check_story_points`, `check_gherkin`, `check_architecture_stack`, `check_gap_coverage`
- Note: gherkin-official accepts a Feature with no Scenarios — the validator flags that explicitly

## draw.io rules (mcp_server/drawio.py)
- Output valid uncompressed draw.io XML: `<mxfile><diagram><mxGraphModel><root>` with cells id="0" and id="1" (parent="0")
- Deterministic layout: one row per tier (fixed order), components spaced on a grid; edges with labels
- Colour by tier; label = name + tech
- Never ask the LLM for coordinates

## Backlog export
- CSV columns: Summary, Issue Type, Description, Story Points, Labels
- Description = user story sentence + Gherkin + linked gaps
- Write to `outputs/backlog.csv`; return path and row count
- Labels = `archispec draft` + compliance tags (spaces → `-`); filenames are sanitised to a basename inside `OUTPUT_DIR`

## Security & data rules (mandatory)
- Use ONLY synthetic data. Never add real client documents, names, or Valtech internal material.
- Never hard-code or print API keys. Read from `.env`; `.env`, `outputs/`, `.cache/`, `memory/chroma/` are in `.gitignore`.
- All outputs are labelled "Draft — requires BA/Architect review".

## Coding conventions
- Small, typed functions; docstrings on public functions
- No silent failures: log and surface errors in the UI step log
- Prefer simple code over abstractions — this is a 4-hour build
- Keep prompts in `prompts/*.md`, not inline strings

## Commands
```
pip install -r requirements.txt
cp .env.example .env               # then fill in values (never commit .env)
python smoke_test.py                 # one call to the configured LLM_PROVIDER
python memory/seed_memory.py         # upsert seed records (add --reset to wipe feedback + past runs too)
python samples/make_brd.py           # regenerate samples/checkout_brd.pdf
python mcp_server/server.py          # run MCP server standalone (stdio)
streamlit run app.py                 # run the app
python -m pytest -q                  # quick tests (if time)
```

## Definition of done
- One click from PDF to all outputs (only Approve in between)
- Plan visible before execution; memory MCP call visible in log
- Stories pass validators; architecture uses approved stack only
- `.drawio` opens in draw.io and is editable; backlog CSV written
- Ollama fallback tested once