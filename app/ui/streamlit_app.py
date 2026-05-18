"""Streamlit UI for the multi-agent code development system.

A flow-tracking interface: enter a task, watch each agent work in real time,
and inspect exactly what every agent produced -- the plan, the generated code,
the review findings, and the test output.

Run from the project root:

    streamlit run app/ui/streamlit_app.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st

from app.graph.state import AgentState
from app.graph.workflow import build_workflow
from app.history import load_history, record_run
from app.llm.pool import build_default_pool, set_pool

DEFAULT_TASK = (
    "Write a BankAccount class with deposit and withdraw methods. "
    "Withdraw must reject amounts larger than the balance."
)

STAGES: list[tuple[str, str]] = [
    ("rag", "RAG"),
    ("analyst", "Analyst"),
    ("developer", "Developer"),
    ("reviewer", "Reviewer"),
    ("qa", "QA"),
    ("supervisor", "Supervisor"),
    ("integrator", "Integrator"),
]
_LABELS = dict(STAGES)
_ICON = {"done": "✅", "active": "⚡", "wait": "⬜"}
_LOOP_STAGES = ("developer", "reviewer", "qa", "supervisor")


def render_tracker(box: Any, statuses: dict[str, str], iteration: int) -> None:
    """Render the compact flow tracker into the given placeholder."""
    cells = [
        f"{_ICON[statuses.get(key, 'wait')]} {label}" for key, label in STAGES
    ]
    box.markdown(f"**İterasyon {iteration}**  ·  " + "  →  ".join(cells))


def next_stage(node: str, update: dict[str, Any]) -> str | None:
    """Return the stage that becomes active after `node` completes."""
    linear = {
        "rag": "analyst",
        "analyst": "developer",
        "developer": "reviewer",
        "reviewer": "qa",
        "qa": "supervisor",
    }
    if node in linear:
        return linear[node]
    if node == "supervisor":
        status = update.get("status")
        if status == "RUNNING":
            return "developer"
        if status == "SUCCESS":
            return "integrator"
    return None


def render_node_detail(node: str, update: dict[str, Any], iteration: int) -> None:
    """Add an expander showing the full output of a completed agent."""
    label = _LABELS.get(node, node)
    with st.expander(f"✅ {label}  ·  iterasyon {iteration}", expanded=True):
        if node == "rag":
            sources = update.get("rag_sources") or []
            if sources:
                st.markdown(f"Bilgi tabanından **{len(sources)} parça** çekti:")
                for source in sources:
                    st.markdown(f"- `{source}`")
            else:
                st.info("RAG bağlamı yok — standartsız devam ediliyor.")
        elif node == "analyst":
            steps = update.get("plan") or []
            st.markdown(f"Görevi **{len(steps)} adıma** böldü:")
            for index, step in enumerate(steps, 1):
                st.markdown(f"{index}. {step}")
        elif node == "developer":
            approach = update.get("dev_approach")
            if approach:
                st.markdown("**Yaklaşım — Developer ne düşündü:**")
                st.info(approach)
            assumptions = update.get("dev_assumptions") or []
            if assumptions:
                st.markdown("**Varsayımlar ve kararlar:**")
                for item in assumptions:
                    st.markdown(f"- {item}")
            code = update.get("code") or {}
            st.markdown(f"**{len(code)} dosya** üretti / güncelledi:")
            for filename, content in code.items():
                st.markdown(f"`{filename}`")
                st.code(content, language="python")
        elif node == "reviewer":
            findings = update.get("review_feedback") or []
            if not findings:
                st.success("Bulgu yok — kod temiz.")
            else:
                st.markdown(f"**{len(findings)} bulgu** raporladı:")
                for finding in findings:
                    st.markdown(f"**[{finding.severity}]** {finding.issue}")
                    if finding.suggestion:
                        st.caption(f"Öneri: {finding.suggestion}")
        elif node == "qa":
            results = update.get("test_results")
            if results is not None:
                summary = f"{results.passed} test geçti, {results.failed} kaldı"
                (st.success if results.failed == 0 else st.error)(summary)
            test_code = update.get("test_code")
            if test_code:
                st.markdown("**Yazılan test senaryoları:**")
                st.code(test_code, language="python")
            if results is not None and results.output:
                st.markdown("**pytest çıktısı:**")
                st.code(results.output, language="text")
        elif node == "supervisor":
            st.markdown(f"**Karar:** {update.get('status')}")
            history = update.get("issue_count_history")
            if history:
                st.caption(f"İterasyon başına sorun sayısı: {history}")
        elif node == "integrator":
            st.markdown("Üretilen kod yerel bir git feature branch'ine commit edildi.")


def render_result(box: Any, state: dict[str, Any]) -> None:
    """Render the final result: overall status and the produced code."""
    status = state.get("status", "?")
    box.subheader("Sonuç")
    if status == "SUCCESS":
        box.success(f"Tamamlandı — {status}")
    elif status == "COMPLETED_WITH_WARNINGS":
        box.warning(f"Tamamlandı — {status}")
    else:
        box.error(f"Tamamlanamadı — {status}")

    results = state.get("test_results")
    if results is not None:
        box.write(f"**Testler:** {results.passed} geçti, {results.failed} kaldı")

    for filename, content in (state.get("code") or {}).items():
        box.markdown(f"**{filename}**")
        box.code(content, language="python")


def render_history() -> None:
    """Render the collapsible panel of past workflow runs."""
    history = load_history()
    with st.expander(f"📋 Geçmiş Görevler ({len(history)})"):
        if not history:
            st.caption(
                "Henüz çalıştırılmış görev yok. Bir görev çalıştırınca "
                "burada listelenir."
            )
            return
        st.dataframe(
            [
                {
                    "Zaman": entry.get("timestamp", "?"),
                    "Görev": str(entry.get("task", ""))[:60],
                    "Durum": entry.get("status", "?"),
                    "Test": (
                        f"{entry.get('tests_passed', 0)}/"
                        f"{entry.get('tests_passed', 0) + entry.get('tests_failed', 0)}"
                    ),
                    "İterasyon": entry.get("iterations", 0),
                }
                for entry in history
            ],
            use_container_width=True,
            hide_index=True,
        )


async def run_workflow(
    task: str,
    max_iterations: int,
    use_rag: bool,
    status_box: Any,
    tracker_box: Any,
    detail_container: Any,
    result_box: Any,
) -> None:
    """Run the workflow, updating the UI live as each agent completes."""
    statuses = {key: "wait" for key, _ in STAGES}
    iteration = 0

    status_box.info("Model hazırlanıyor...")
    pool = build_default_pool()
    set_pool(pool)
    await pool.warm_up()

    workflow = build_workflow()
    initial: AgentState = {
        "task": task,
        "task_id": uuid.uuid4().hex[:8],
        "mode": "generate",
        "iteration": 0,
        "status": "RUNNING",
        "max_iterations": max_iterations,
        "use_rag": use_rag,
    }

    statuses["rag"] = "active"
    render_tracker(tracker_box, statuses, iteration)
    status_box.info("Ajanlar çalışıyor...")

    final_state: dict[str, Any] = dict(initial)

    async for chunk in workflow.astream(
        initial, stream_mode="updates", config={"recursion_limit": 50}
    ):
        for node, raw_update in chunk.items():
            update = raw_update or {}
            final_state.update(update)
            statuses[node] = "done"
            iteration = final_state.get("iteration", 0)

            with detail_container:
                render_node_detail(node, update, iteration)

            nxt = next_stage(node, update)
            if node == "supervisor" and nxt == "developer":
                for key in _LOOP_STAGES:
                    statuses[key] = "wait"
            if nxt is not None:
                statuses[nxt] = "active"
            render_tracker(tracker_box, statuses, iteration)

    await pool.aclose()
    status_box.empty()
    render_result(result_box, final_state)
    record_run(final_state)


st.set_page_config(page_title="Multi-Agent Code Team", page_icon="🤖")
st.title("🤖 Multi-Agent Code Team")
st.caption("Yerel LLM'lerle çalışan çok-ajanlı kod geliştirme ekibi")

render_history()

with st.sidebar:
    st.header("Ayarlar")
    cfg_max_iterations = st.slider("Maksimum iterasyon", min_value=1, max_value=5, value=3)
    cfg_use_rag = st.toggle("RAG (bilgi tabanı)", value=True)
    st.caption(
        "Maksimum iterasyon: Developer-Reviewer döngüsünün üst sınırı. "
        "RAG kapalıyken ajanlar standart bağlamı olmadan çalışır."
    )

task_input = st.text_area("Görev", value=DEFAULT_TASK, height=110)
go = st.button("▶ Çalıştır", type="primary")

if go:
    if not task_input.strip():
        st.error("Lütfen bir görev girin.")
    else:
        status_ph = st.empty()
        tracker_ph = st.empty()
        st.markdown("### Akış Detayları")
        detail_box = st.container()
        st.divider()
        result_ph = st.container()
        asyncio.run(
            run_workflow(
                task_input.strip(),
                cfg_max_iterations,
                cfg_use_rag,
                status_ph,
                tracker_ph,
                detail_box,
                result_ph,
            )
        )
