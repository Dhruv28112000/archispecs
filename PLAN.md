# PLAN.md — ArchiSpec build plan for Claude Code

Put this file and `CLAUDE.md` in the repo root, then start Claude Code in that folder.
Work phase by phase. After each phase, run the check before moving on.

---

## Kickoff prompt (paste into Claude Code first)
> Read CLAUDE.md and PLAN.md. Do not write code yet. Summarise the architecture in 5 lines,
> list any questions or risks, then propose the exact file list for Phase 1.

---

## Phase 0 — Setup (0:00–0:20) · Owner: everyone
- [ ] `python -m venv .venv` and activate
- [ ] `.env` with `GEMINI_API_KEY`, `LLM_MODEL` (stable Flash model from AI Studio), `OLLAMA_MODEL=qwen3:8b`
- [ ] `ollama pull qwen3:8b` (fallback)
- [ ] Pre-download Chroma's default embedding model (downloads on first use — do it before the timer, not on hackathon Wi-Fi):
      `python -c "from chromadb.utils import embedding_functions as e; e.DefaultEmbeddingFunction()(['warm up'])"`

**Prompt:**
> Phase 0: create requirements.txt, .gitignore (.env, .venv, outputs/, .cache/, __pycache__),
> .env.example (no real values), empty folders per CLAUDE.md, and a script `smoke_test.py`
> that calls Gemini once and prints the reply. Do not read or print my .env.

**Check:** `python smoke_test.py` prints a reply.

---

## Phase 1 — Contracts, memory, sample data (0:20–0:50) · Owners: C, E
**Prompt:**
> Phase 1: implement schemas.py exactly as in CLAUDE.md (flat Pydantic v2 models).
> Create memory/seed_data.json as a list of records {key, type, domain, text} following the
> "Memory design (ChromaDB)" section in CLAUDE.md:
> - type=stack: one record each for Next.js, FastAPI, PostgreSQL, Redis, Kafka (text says what it is approved for)
> - type=compliance: PCI-DSS (tokenise card data, never store PAN/CVV, audit logging, encryption in transit/at rest)
>   and GDPR (consent, data minimisation, right to erasure, data retention limits) — one record per rule
> - type=estimation: Fibonacci scale [1,2,3,5,8,13] (store the list in the text as JSON)
> - type=pattern: 3–4 approved patterns (idempotency keys in Redis, transactional outbox to Kafka,
>   distributed lock for wallet balance, PSP tokenisation flow)
> Implement memory/store.py (PersistentClient at memory/chroma, collections enterprise_memory and past_runs,
> default embedding function, upsert by key) with: get_constraints() -> schemas.Memory (deterministic `get` by type),
> search(queries: list[str], n=5) -> list[dict] (semantic, types compliance/pattern/feedback, returns key+text+distance),
> add_feedback(text), add_run(run_id, gaps, stories).
> Implement memory/seed_memory.py to (re)build the DB from seed_data.json and print counts per type.
> Then write samples/make_brd.py that generates samples/checkout_brd.pdf with PyMuPDF:
> a 3–4 page SYNTHETIC BRD for "E-Commerce One-Click Checkout & Wallet" for a fictional company.
> Deliberately omit idempotency, checkout timeouts, wallet concurrency locks, refund flow and data retention
> so the agent can detect them as gaps. Number the sections (1, 1.1, 2 ...).

**Check:** PDF opens; `python memory/seed_memory.py` prints counts; a test search for
"prevent duplicate wallet payments" returns the idempotency/lock patterns in the top 3.

---

## Phase 2 — LLM wrapper (0:50–1:20) · Owner: C
**Prompt:**
> Phase 2: implement llm.py per CLAUDE.md "LLM rules": generate_json(system, user, schema)
> with google-genai structured output, file cache in .cache/, exponential backoff on 429/5xx (max 3),
> Ollama fallback with format=schema JSON schema, Pydantic validation and one repair retry.
> Log which provider answered. Add a tiny test calling it with the Plan schema.

**Check:** second identical call is served from cache; forcing a bad model name triggers fallback.

---

## Phase 3 — MCP server (0:20–1:50, parallel) · Owner: D
**Prompt:**
> Phase 3: implement mcp_server/server.py with FastMCP and three tools:
> 1) query_enterprise_memory(queries: list[str]) -> dict using memory/store.py:
>    {"constraints": get_constraints(), "relevant": search(queries), "similar_past": top past_runs matches}
> 2) generate_drawio_diagram(architecture_json: str, filename: str) -> dict {path, components, connections}
> 3) export_sprint_backlog(stories_json: str, filename: str) -> dict {path, rows}
> Also add save_feedback(text: str) -> dict (store.add_feedback) and
> save_run(run_id: str, gaps_json: str, stories_json: str) -> dict (store.add_run).
> Implement mcp_server/drawio.py per CLAUDE.md "draw.io rules" (deterministic tier rows, colours per tier,
> labelled edges, valid uncompressed XML). Add a __main__ test that writes outputs/test.drawio from a
> hard-coded 6-component sample architecture.

**Check:** `outputs/test.drawio` opens and is editable in draw.io desktop.

---

## Phase 4 — Prompts / skills (0:20–2:00, parallel) · Owner: B
**Prompt:**
> Phase 4: write prompts/planner.md, prompts/gaps_stories.md, prompts/architect.md.
> Each: role, rules, output schema reminder, one complete few-shot example.
> planner: produce the 4-stage plan from CLAUDE.md, adapted to the document (e.g. "payments detected → load PCI-DSS rules").
> gaps_stories: domain checklist for payments (idempotency, double-spend, timeouts, partial failure, retries,
> refunds, reconciliation, fraud, SCA/3DS) + cross-cutting NFRs (performance, availability, security, privacy,
> observability). Every gap cites source_section or "not stated". Stories: INVEST, "As a / I want / so that",
> 2–4 Gherkin scenarios incl. ≥1 negative/edge case, Fibonacci points from memory, link gap IDs, compliance tags.
> architect: use ONLY approved_stack (+ tier "External" for payment gateway/PSP), apply compliance rules
> (tokenisation, no card storage, audit log), map each component to requirements/gap IDs.
> Retrieved memory records are injected as a "MEMORY CONTEXT" block with their keys; gaps, stories and
> components should reference the memory key they applied (e.g. "applied: pci-tokenise").
> Rule for all: never invent facts; if not in the BRD, mark as gap or assumption.

**Check:** run each prompt through llm.py on the sample BRD; output validates.

---

## Phase 5 — Validators (1:20–2:00) · Owner: E
**Prompt:**
> Phase 5: implement validators.py per CLAUDE.md. Return clear error strings.
> Add pytest tests with one valid and one invalid example for each rule.

**Check:** `python -m pytest -q` passes.

---

## Phase 6 — Agent orchestrator (1:20–2:20) · Owner: C
**Prompt:**
> Phase 6: implement agent.py per CLAUDE.md "Agent flow". Use the mcp stdio client to start
> mcp_server/server.py and call tools. Split into two functions: plan_run(pdf_path) -> Plan
> and execute_run(pdf_path, plan, on_event) -> dict of results/paths. on_event(step, status, detail)
> is called for every step and every MCP call. Generate stories in batches of 3–5.
> Run validators; on errors do one repair call, then keep remaining errors as flags in the summary.
> Build memory queries from the extracted goals (e.g. "wallet payment", "one-click checkout card storage").
> Write outputs/summary.md (executive summary, critical gaps table, links to files, "Draft" label).
> After a successful run call save_run so the next run can reuse similar past stories.
> Add a CLI: python agent.py samples/checkout_brd.pdf (auto-approves plan).

**Check:** CLI produces summary.md, .drawio, backlog.csv.

---

## Phase 7 — UI (0:20–2:20 layout, then wire) · Owner: A
**Prompt:**
> Phase 7: implement app.py in Streamlit: PDF uploader → "Create plan" → show plan steps →
> "Approve & run" → live step log (st.status per step, MCP calls highlighted) →
> tabs: Summary & Gaps (severity colours) | Architecture (download .drawio + component table) |
> User Stories (expanders with Gherkin in code blocks, points, tags; download CSV) |
> Memory (hard constraints + retrieved records table: key, type, text, similarity score;
> feedback box that calls save_feedback).
> Keep state in st.session_state.

**Check:** full flow works in the browser.

---

## Phase 8 — Integration & hardening (2:20–3:30) · Owners: all
**Prompt:**
> Phase 8: run the full flow on samples/checkout_brd.pdf, fix errors, and make failures visible
> in the step log instead of crashing. Verify the Ollama fallback once. Make the planner output
> mention which memory rules it will apply. Then list anything in the Definition of Done not yet met.

**Check:** every item in CLAUDE.md "Definition of done" ticked.

---

## Phase 9 — Freeze & demo (3:30–4:00)
- [ ] Code freeze; commit and tag `demo`
- [ ] Pre-warm: one full run (fills cache, avoids rate limits on stage)
- [ ] Two rehearsals of the 5-minute demo (Goal → Plan → Skill → Memory → MCP → Output)
- [ ] Record a backup video of a full run

---

## Rules while working with Claude Code
- One phase per prompt; review the diff before accepting.
- If something breaks, paste the exact error and ask for the smallest fix.
- Ask Claude Code to update CLAUDE.md if a contract changes, so everyone stays in sync.
- At 2:00, if the flow isn't connected end to end, stop features and integrate.
- Never paste API keys into prompts; never use real client data.