"""VastHorizon 검증 페이지 (Streamlit) — 검색 방식 비교 (F2014).

    streamlit run app/streamlit_app.py

같은 항목 · 질문 · 색인으로 유사도 검색과 MMR을 나란히 실행해 근거 청크를 비교한다.
답변은 만들지 않는다 (LLM 호출 없음, 질문 임베딩 1회).
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


def main() -> None:
    st.set_page_config(page_title="VastHorizon 검증", page_icon="🔭", layout="wide")
    st.title("VastHorizon 검증 페이지")
    show_compare()


main()
