"""실행 환경 점검 — 설정 · 키 · 외부 API 연결을 한 번에 확인한다.

    python -m scripts.check_env            # 설정 · 외부 API만 확인 (토큰 사용 없음)
    python -m scripts.check_env --llm      # 채팅 · 임베딩도 1회씩 호출

키 값은 출력하지 않는다.
"""

from __future__ import annotations

import argparse
import sys

from vasthorizon.config import get_contact, get_llm_key, get_settings, key_name
from vasthorizon.http import http

OK, FAIL, WARN = "[ OK ]", "[FAIL]", "[WARN]"

EXTERNAL = {
    "한국어 위키백과": ("https://ko.wikipedia.org/w/api.php", {"action": "query", "meta": "siteinfo", "format": "json"}),
    "Wikidata": ("https://www.wikidata.org/w/api.php", {"action": "query", "meta": "siteinfo", "format": "json"}),
    "JPL Horizons": ("https://ssd.jpl.nasa.gov/api/horizons.api", {"format": "json", "COMMAND": "'499'", "OBJ_DATA": "NO", "MAKE_EPHEM": "NO"}),
    "CelesTrak SATCAT": ("https://celestrak.org/satcat/records.php", {"CATNR": "25544", "FORMAT": "json"}),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", action="store_true", help="채팅 · 임베딩을 실제로 1회 호출한다")
    args = parser.parse_args()
    failed = False

    s = get_settings()
    print(f"{OK} 설정 파일: {s.config_path.name}")
    chat = s.llm.anthropic_model if s.llm.provider == "anthropic" else s.llm.chat_model
    embed = s.llm.local_embedding_model if s.llm.embedding_provider == "local" else s.llm.embedding_model
    print(f"       제공자: {s.llm.provider} / 임베딩: {s.llm.embedding_provider}")
    print(f"       모델: {chat} / 임베딩: {embed}")
    print(f"       청크: {s.chunking.chunk_size}자 · 중복 {s.chunking.chunk_overlap}자 / "
          f"검색: {s.retrieval.search_type} · Top-k {s.retrieval.top_k_docs}")

    if get_llm_key():
        print(f"{OK} {key_name()} 설정됨")
    else:
        print(f"{FAIL} {key_name()}가 없습니다 — .env를 확인하세요")
        failed = True

    print(f"{OK} 연락처 설정됨" if get_contact() else f"{WARN} WIKI_CONTACT가 없습니다 — 외부 API 한도가 줄어듭니다")
    print(f"       User-Agent 형식: {s.http.app_name} (연락처) python-requests/x.y")

    for name, (url, params) in EXTERNAL.items():
        try:
            http().get(url, params=params)
            print(f"{OK} {name}")
        except Exception as e:  # 점검 스크립트이므로 종류와 무관하게 실패로 표시
            print(f"{FAIL} {name}: {type(e).__name__}")
            failed = True

    if args.llm and get_llm_key():
        label = "Claude" if s.llm.provider == "anthropic" else "GMS"
        elabel = "로컬" if s.llm.embedding_provider == "local" else "GMS"
        from vasthorizon.llm import chat_model, embeddings, reply_text

        try:
            reply = chat_model().invoke("한 단어로만 답하세요: 지구의 위성 이름은?")
            print(f"{OK} {label} 채팅 응답: {reply_text(reply).strip()[:30]}")
        except Exception as e:
            print(f"{FAIL} {label} 채팅: {type(e).__name__}")
            failed = True
        try:
            vec = embeddings().embed_query("우주")
            print(f"{OK} {elabel} 임베딩 차원: {len(vec)}")
        except Exception as e:
            print(f"{FAIL} {elabel} 임베딩: {type(e).__name__}")
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
