"""ArchiSpec Streamlit UI: upload BRD → plan → approve → live step log → result tabs.

Run: streamlit run app.py
"""
import os
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

import agent
from mcp_server.drawio import DRAFT_LABEL

ROOT = Path(__file__).resolve().parent
UPLOAD_DIR = ROOT / os.getenv("OUTPUT_DIR", "outputs") / "uploads"
SAMPLE_BRD = ROOT / "samples" / "checkout_brd.pdf"

STEP_LABELS = {
    "ingest": "📄 Ingest BRD",
    "plan": "🧭 Plan · planner skill",
    "mcp": "🔌 MCP · connect to server",
    "mcp:query_enterprise_memory": "🔌 MCP tool · query_enterprise_memory",
    "gaps": "🧠 Skill · gap detection",
    "stories": "🧠 Skill · user stories",
    "architect": "🏗️ Skill · architect",
    "validate": "✅ Validators",
    "mcp:generate_drawio_diagram": "🔌 MCP tool · generate_drawio_diagram",
    "mcp:export_sprint_backlog": "🔌 MCP tool · export_sprint_backlog",
    "summary": "📝 Summary",
    "mcp:save_run": "🔌 MCP tool · save_run",
    "run": "❌ Run failed",
}
SEVERITY_COLOURS = {"High": "background-color: #f8cecc", "Medium": "background-color: #fff2cc",
                    "Low": "background-color: #d5e8d4"}


class StepLog:
    """Renders agent events as one st.status box per step; also used to replay stored events."""

    def __init__(self, record: bool):
        self.record = record
        self.boxes: dict[str, Any] = {}
        self.last: str | None = None

    def __call__(self, step: str, status: str, detail: str) -> None:
        if self.record:
            st.session_state.events.append((step, status, detail))
        self.render(step, status, detail)

    def render(self, step: str, status: str, detail: str) -> None:
        if step == "llm":  # provider / retry / fallback lines belong to the current step
            if self.last:
                with self.boxes[self.last]:
                    (st.warning if status == "warning" else st.caption)(f"LLM · {detail}")
            return
        label = STEP_LABELS.get(step, step)
        if step not in self.boxes:
            self.boxes[step] = st.status(label, state="running", expanded=step.startswith("mcp:"))
        self.last = step
        box = self.boxes[step]
        with box:
            if status == "error":
                st.error(detail)
            elif status == "warning":
                st.warning(detail)
            elif step.startswith("mcp:"):
                st.info(detail)  # highlight MCP tool calls
            else:
                st.write(detail)
        if status == "done":
            box.update(label=label, state="complete")
        elif status == "error":
            box.update(label=label, state="error", expanded=True)

    def replay(self, events: list[tuple[str, str, str]]) -> None:
        for event in events:
            self.render(*event)
        if st.session_state.result:  # run finished: close any box still marked running
            for box in self.boxes.values():
                box.update(state="complete")


def init_state() -> None:
    defaults = {"pdf_path": None, "plan": None, "events": [], "result": None, "error": None}
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def select_pdf(path: Path) -> None:
    """Start over with a new BRD."""
    if st.session_state.pdf_path != str(path):
        st.session_state.update(pdf_path=str(path), plan=None, events=[], result=None, error=None)


def sidebar() -> None:
    with st.sidebar:
        st.header("1 · Business Requirement Document")
        upload = st.file_uploader("Upload BRD (PDF)", type=["pdf"])
        if upload is not None:
            UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            path = UPLOAD_DIR / Path(upload.name).name
            path.write_bytes(upload.getvalue())
            select_pdf(path)
        if st.button("Use sample BRD (synthetic)"):
            select_pdf(SAMPLE_BRD)
        if st.session_state.pdf_path:
            st.success(f"Selected: {Path(st.session_state.pdf_path).name}")
        st.caption("Use synthetic documents only — never real client data.")


def plan_section() -> None:
    st.subheader("2 · Plan")
    if st.button("Create plan", type="primary", disabled=not st.session_state.pdf_path):
        st.session_state.update(events=[], result=None, error=None)
        try:
            st.session_state.plan = agent.plan_run(st.session_state.pdf_path, StepLog(record=True))
        except Exception as exc:  # surface, don't crash
            st.session_state.error = f"Planning failed — {type(exc).__name__}: {exc}"
        st.rerun()

    plan = st.session_state.plan
    if plan:
        for s in plan.steps:
            st.markdown(f"**{s.id}. {s.title}** &nbsp; `{s.executor}`  \n{s.purpose}")


def run_section() -> None:
    plan = st.session_state.plan
    if not plan:
        return
    st.subheader("3 · Execute")
    if st.button("Approve & run", type="primary", disabled=st.session_state.result is not None):
        st.session_state.update(events=[], error=None)
        try:
            st.session_state.result = agent.execute_run(st.session_state.pdf_path, plan, StepLog(record=True))
        except Exception as exc:
            st.session_state.error = f"Run failed — {type(exc).__name__}: {exc}"
        st.rerun()

    if st.session_state.events:
        st.markdown("**Step log**")
        StepLog(record=False).replay(st.session_state.events)


def download(label: str, path: str, mime: str) -> None:
    p = Path(path)
    if p.exists():
        st.download_button(label, p.read_bytes(), file_name=p.name, mime=mime, on_click="ignore")
    else:
        st.warning(f"File not found: {p.name}")


def summary_tab(r: dict) -> None:
    gaps, stories, arch = r["gaps"].gaps, r["stories"].stories, r["architecture"]
    cols = st.columns(5)
    cols[0].metric("Gaps", len(gaps))
    cols[1].metric("High severity", sum(g.severity == "High" for g in gaps))
    cols[2].metric("User stories", len(stories))
    cols[3].metric("Story points", sum(s.story_points for s in stories))
    cols[4].metric("Components", len(arch.components))

    if r["flags"]:
        st.warning("Open validation issues:\n\n" + "\n".join(f"- {f}" for f in r["flags"]))
    else:
        st.success("All validators passed.")
    st.markdown(f"**Memory applied:** {', '.join(agent.applied_keys(r['gaps'], r['stories'], arch)) or 'none'}")

    df = pd.DataFrame([{"ID": g.id, "Severity": g.severity, "Category": g.category, "Gap": g.title,
                        "BRD section": g.source_section, "Suggested requirement": g.suggested_requirement}
                       for g in gaps])
    if not df.empty:
        st.dataframe(df.style.map(lambda v: SEVERITY_COLOURS.get(v, ""), subset=["Severity"]),
                     hide_index=True, width="stretch")
    download("Download summary.md", r["paths"]["summary"], "text/markdown")


def architecture_tab(r: dict) -> None:
    arch = r["architecture"]
    download("Download architecture.drawio", r["paths"]["drawio"], "application/xml")
    st.caption("Open in draw.io (desktop or app.diagrams.net) to edit.")
    st.dataframe(pd.DataFrame([{"ID": c.id, "Name": c.name, "Tech": c.tech, "Tier": c.tier,
                                "Requirements": ", ".join(c.requirements)} for c in arch.components]),
                 hide_index=True, width="stretch")
    st.markdown("**Connections**")
    st.dataframe(pd.DataFrame([c.model_dump() for c in arch.connections]),
                 hide_index=True, width="stretch")


def stories_tab(r: dict) -> None:
    download("Download Jira backlog (CSV)", r["paths"]["backlog"], "text/csv")
    for s in r["stories"].stories:
        with st.expander(f"{s.id} · {s.title} — {s.story_points} pts"):
            st.markdown(f"As a **{s.as_a}**, I want **{s.i_want}**, so that **{s.so_that}**.")
            st.code(s.gherkin, language="gherkin")
            st.markdown(f"**Linked gaps:** {', '.join(s.linked_gaps) or '–'}  \n"
                        f"**Compliance tags:** {', '.join(s.compliance_tags) or '–'}")


def memory_tab(r: dict) -> None:
    c = r["memory"]["constraints"]
    st.markdown("**Hard constraints** (deterministic lookup)")
    st.markdown(f"- Approved stack: {', '.join(c['approved_stack'])}\n"
                f"- Estimation scale: {c['estimation_scale']}\n"
                f"- Compliance rules: {len(c['compliance_rules'])} · Feedback records: {len(c['feedback'])}")
    st.markdown("**Retrieved records** (semantic search on BRD headings)")
    st.dataframe(pd.DataFrame([{"Key": m["key"], "Type": m["type"], "Text": m["text"],
                                "Similarity": round(1 - m["distance"], 2)} for m in r["memory"]["relevant"]]),
                 hide_index=True, width="stretch")
    if r["memory"]["similar_past"]:
        st.markdown("**Similar items from past runs**")
        st.dataframe(pd.DataFrame([{"Kind": m["kind"], "Text": m["text"],
                                    "Similarity": round(1 - m["distance"], 2)}
                                   for m in r["memory"]["similar_past"]]),
                     hide_index=True, width="stretch")

    st.markdown("**Teach ArchiSpec** — feedback is stored in memory and retrieved on the next run.")
    with st.form("feedback", clear_on_submit=True):
        text = st.text_area("Feedback", placeholder="e.g. Always add a reconciliation story for wallet top-ups.")
        if st.form_submit_button("Save feedback") and text.strip():
            try:
                st.success(f"Saved to memory as `{agent.save_feedback(text.strip())['key']}`")
            except Exception as exc:
                st.error(f"Could not save feedback — {type(exc).__name__}: {exc}")


def results_section() -> None:
    r = st.session_state.result
    if not r:
        return
    st.subheader(f"4 · Results — {r['title']}")
    st.caption(f"⚠️ {DRAFT_LABEL}")
    tabs = st.tabs(["Summary & Gaps", "Architecture", "User Stories", "Memory"])
    for tab, render in zip(tabs, (summary_tab, architecture_tab, stories_tab, memory_tab)):
        with tab:
            render(r)


def main() -> None:
    st.set_page_config(page_title="ArchiSpec", page_icon="🏛️", layout="wide")
    init_state()
    st.title("🏛️ ArchiSpec")
    st.caption(f"BRD → gaps, user stories and architecture · {DRAFT_LABEL}")
    sidebar()
    if st.session_state.error:
        st.error(st.session_state.error)
    plan_section()
    run_section()
    results_section()


main()
