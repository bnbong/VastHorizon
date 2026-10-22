"""VastHorizon 검증 페이지 (Streamlit) — 검색 방식 비교 (F2014) · RAG 전후 비교 (F2015).

    streamlit run app/streamlit_app.py

| 탭               | 내용                                                                   |
|------------------|------------------------------------------------------------------------|
| 검색 방식 비교   | 같은 항목 · 질문 · 색인으로 유사도 검색과 MMR 근거를 나란히 (LLM 호출 없음) |
| RAG 전후 비교    | 기획안 7장 질문을 근거 없이 · 근거와 함께 답한 결과를 나란히 (저장된 결과) |
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:                  # streamlit은 스크립트 폴더만 경로에 넣는다
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

from vasthorizon.config import get_settings  # noqa: E402

METHOD_LABELS = {"similarity": "유사도 검색", "mmr": "MMR 검색"}
DEFAULT_QUESTIONS = {
    "보이저 1호": "보이저 1호는 태양계를 벗어났나?",
    "플레이아데스 성단": "플레이아데스 성단은 왜 푸른빛으로 보이나?",
    "베텔게우스": "베텔게우스는 곧 초신성이 되나?",
}


@st.cache_data(show_spinner=False)
def catalog() -> list[dict]:
    from vasthorizon.data.catalog import load_items
    try:
        return load_items()
    except (FileNotFoundError, ValueError):
        return []


def indexed_ids() -> list[str]:
    from vasthorizon.store.doc_index import indexed_item_ids
    try:
        return indexed_item_ids(get_settings().collections.docs)
    except Exception:  # noqa: BLE001 — 색인을 읽지 못하면 비교할 항목이 없다고 안내한다
        return []


def hit_card(hit, shared: bool) -> None:
    where = f" › {hit.section}" if hit.section else ""
    badge = " · 🔁 두 방식 공통" if shared else ""
    score = f"{hit.score:.3f}" if hit.score is not None else "—"
    st.markdown(f"**{hit.rank}. [{hit.title}{where}]({hit.url})**  \n"
                f"<small>{hit.source_type} · 유사도 {score}{badge}</small>", unsafe_allow_html=True)
    with st.expander("청크 본문"):
        st.caption(hit.chunk_id)
        st.write(hit.text)


def show_compare() -> None:
    from vasthorizon.features.compare import METHODS, compare_search
    from vasthorizon.llm import MissingApiKeyError
    from vasthorizon.store.chroma import EmbeddingMismatchError

    cfg = get_settings().retrieval
    st.subheader("검색 방식 비교 (F2014)")
    st.caption("같은 항목 · 질문 · 색인으로 유사도 검색과 MMR을 나란히 실행합니다. 답변은 만들지 않습니다.")

    items = {it["id"]: it for it in catalog()}
    ids = [i for i in indexed_ids() if i in items]
    if not ids:
        st.warning("문서 색인에 항목이 없습니다. `python -m scripts.index_docs --demo` 로 시연 항목을 먼저 색인하세요.")
        return

    with st.sidebar:
        st.header("검색 설정")
        top_k = st.slider("top-k (근거 수)", 1, 10, cfg.top_k_docs)
        fetch_k = st.slider("fetch-k (MMR 후보 수)", top_k, 50, max(cfg.mmr_fetch_k, top_k))
        lam = st.slider("lambda (1 = 관련성만, 0 = 다양성만)", 0.0, 1.0, float(cfg.mmr_lambda), 0.05)
        st.caption(f"설정 파일 기본값 — 검색 방식 {cfg.search_type} · top-k {cfg.top_k_docs} · "
                   f"fetch-k {cfg.mmr_fetch_k} · lambda {cfg.mmr_lambda}")

    names = sorted(ids, key=lambda i: items[i]["name"])
    # 시연 질문이 있는 항목(문서가 많은 항목)을 기본으로 — 청크가 적으면 두 방식 결과가 같아진다
    first = next((i for i in names if items[i]["name"] in DEFAULT_QUESTIONS), names[0])
    item_id = st.selectbox("항목 (문서가 색인된 항목)", names, index=names.index(first), format_func=lambda i: items[i]["name"])
    question = st.text_input("질문", DEFAULT_QUESTIONS.get(items[item_id]["name"], f"{items[item_id]['name']}은 무엇인가?"),
                             max_chars=300)
    if not st.button("비교하기", type="primary") or not question.strip():
        return

    try:
        with st.spinner("두 방식으로 검색하는 중…"):
            result = compare_search(item_id, question.strip(), top_k=top_k, fetch_k=fetch_k, lambda_mult=lam)
    except MissingApiKeyError:
        st.error("AI 서비스 키(GMS_KEY)가 없어 질문을 임베딩할 수 없습니다. .env 설정을 확인하세요.")
        return
    except EmbeddingMismatchError:
        st.error("색인과 현재 임베딩 설정이 맞지 않습니다. 문서 색인을 재구축해야 합니다.")
        return

    s = result.settings
    st.caption(f"top-k {s['top_k']} · fetch-k {s['fetch_k']} · lambda {s['lambda']} · 컬렉션 {s['collection']} · "
               f"이 항목의 청크 {result.chunks_in_scope}개")
    for w in result.warnings:
        (st.error if result.status in ("failed", "index_missing") else st.info)(w)
    if result.status != "ok":
        return
    if result.chunks_in_scope <= s["top_k"]:
        st.info(f"이 항목의 청크가 {result.chunks_in_scope}개로 top-k({s['top_k']}) 이하라 두 방식이 같은 청크를 고릅니다. "
                "청크가 많은 항목(예: 보이저 1호)에서 차이가 드러납니다.")

    overlap = result.overlap
    m1, m2, m3 = st.columns(3)
    m1.metric("두 방식 공통 근거", f"{len(overlap)}개")
    for col, method in zip((m2, m3), METHODS):
        col.metric(f"{METHOD_LABELS[method]} — 서로 다른 문서", f"{len({h.title for h in result.hits[method]})}개")

    for col, method in zip(st.columns(2), METHODS):
        with col:
            path = " (정확 비교로 재계산)" if result.paths.get(method) == "exact" else ""
            st.markdown(f"#### {METHOD_LABELS[method]}{path}")
            for hit in result.hits[method]:
                hit_card(hit, hit.chunk_id in overlap)


def rag_result_path() -> Path:
    return get_settings().paths.data_dir / "eval" / "rag_comparison.json"


def load_rag_results() -> dict | None:
    import json
    path = rag_result_path()
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def answer_column(title: str, side: dict, evidence: bool) -> None:
    st.markdown(f"#### {title}")
    st.write(side["answer"])
    m = side["metrics"]
    st.caption(f"근거 인용 {m['citations']}회 · 수치 {m['numbers']}개 · {side['seconds']}초"
               + (" · '확인되지 않음' 표현" if m["not_found"] else ""))
    if evidence:
        if not side.get("cited"):
            st.warning("인용된 근거가 없습니다.")
        for ev in side.get("cited", []):
            where = f" › {ev['section']}" if ev.get("section") else ""
            with st.expander(f"[근거 {ev['number']}] {ev['title']}{where} · {ev['source_type']}"):
                st.caption(ev["kind"])
                st.write(ev["excerpt"])
                if ev.get("url"):
                    st.markdown(f"[원문]({ev['url']})")
        for w in side.get("warnings", []):
            st.caption(f"⚠ {w}")


def run_label(run: dict | None) -> str:
    if not run:
        return "실행 정보 없음 (이전 형식)"
    return f"{run['run_id']} · {run['started_at'][:16].replace('T', ' ')} · {run['chat_model']}"


def show_conditions(rows: list[dict]) -> None:
    """결과에 섞인 실행 조건 — 다른 모델 · 설정의 결과를 한 번에 실행한 것처럼 보이지 않게."""
    from vasthorizon.features.rag_compare import conditions_summary
    summary = conditions_summary(rows)
    if summary["mixed"]:
        st.warning("서로 다른 조건(모델 · 검색 · 청킹 설정 · 프롬프트)으로 실행한 결과, 또는 실행 정보가 없는 결과가 섞여 있습니다. "
                   "문항별 실행 정보를 함께 보세요.")
    for g in summary["groups"]:
        r = g["run"]
        st.caption(f"조건 {r['conditions_id']} — 문항 {', '.join(map(str, g['numbers']))} · 모델 {r['chat_model']} · "
                   f"임베딩 {r['embedding_model']} · 검색 {r['retrieval']['search_type']} (top-k {r['retrieval']['top_k']}, "
                   f"fetch-k {r['retrieval']['fetch_k']}, λ {r['retrieval']['lambda']}) · 청크 {r['chunking']['size']}/{r['chunking']['overlap']} · "
                   f"프롬프트 {r['prompts']} · 실행 {', '.join(sorted(g['run_ids']))}")
    if summary["unknown"]:
        st.caption(f"실행 정보 없음 — 문항 {', '.join(map(str, summary['unknown']))}")


def show_rag_compare() -> None:
    st.subheader("RAG 전후 비교 (F2015)")
    st.caption("기획안 7장 '근거가 필요한 질문'을 같은 모델 · 말투 · 길이로, 근거 없이 / 근거와 함께 답하게 한 결과입니다. "
               "판정과 해설은 docs/05_rag_comparison.md에 있습니다.")
    data = load_rag_results()
    if not data:
        st.warning("저장된 비교 결과가 없습니다. `python -m scripts.compare_rag` 로 먼저 실행하세요.")
        return
    rows = data["rows"]
    show_conditions(rows)
    st.dataframe([{"#": r["number"], "버전": f"v{r.get('question_version', 1)}", "질문": r["question"],
                   "RAG 없이 인용": r["baseline"]["metrics"]["citations"], "RAG 인용": r["rag"]["metrics"]["citations"],
                   "RAG 상태": r["rag"]["status"], "실행": run_label(r.get("run")),
                   "근거 문서": ", ".join(dict.fromkeys(ev["title"] for ev in r["rag"]["cited"]))} for r in rows],
                 hide_index=True, use_container_width=True)
    pick = st.selectbox("질문", rows, format_func=lambda r: f"{r['number']} (v{r.get('question_version', 1)}). {r['question']}  "
                                                       f"(기준 항목: {r['item_name']})")
    st.caption(f"이 문항의 실행: {run_label(pick.get('run'))}")
    left, right = st.columns(2)
    with left:
        answer_column("RAG 없이 — 근거 없이 답함", pick["baseline"], evidence=False)
    with right:
        answer_column("RAG — 수집 문서를 근거로", pick["rag"], evidence=True)


def main() -> None:
    st.set_page_config(page_title="VastHorizon 검증", page_icon="🔭", layout="wide")
    st.title("VastHorizon 검증 페이지")
    retrieval_tab, rag_tab = st.tabs(["검색 방식 비교 (F2014)", "RAG 전후 비교 (F2015)"])
    with retrieval_tab:
        show_compare()
    with rag_tab:
        show_rag_compare()


main()
