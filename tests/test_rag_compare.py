"""RAG 전후 비교 테스트 (F2015) — 가짜 LLM · 가짜 질의응답 · 임시 결과 파일. 외부 호출 · 토큰 사용 없음.

    python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests.fakes import FakeChat
from vasthorizon.config import get_settings
from vasthorizon.features import rag_compare
from vasthorizon.features.rag_compare import (
    QUESTIONS, compare_one, conditions_summary, merge_results, metrics, run_all, run_info,
)
from vasthorizon.rag.graph import clean_reply, generate_validated
from vasthorizon.rag.prompts import BASELINE_SYSTEM
from vasthorizon.rag.retrieval import Evidence

APP = Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py"
EV = Evidence(number=1, chunk_id="c1", kind="외부 문서", source_type="위키백과", title="보이저 1호", section="성간 공간",
              url="https://ko.wikipedia.org/wiki/보이저_1호", text="[보이저 1호 > 성간 공간]\n2012년 8월 25일 태양권계면을 넘었다.")
SUN = Evidence(number=1, chunk_id="c2", kind="외부 문서", source_type="위키백과", title="태양", section="이름",
               url="u", text="[태양 > 이름]\n산스크리트어로 태양은 सूर्य(수리야)라고 한다.")


def fake_ask(item, question):
    fake_ask.questions.append(question)
    return SimpleNamespace(answer="2012년 8월 25일 태양권계면을 넘었습니다.[근거 1]", raw_answer="2012년 8월 25일 태양권계면을 넘었습니다.[근거 1]⟦END⟧",
                           status="cited", cited=[EV], warnings=[])


fake_ask.questions = []
ITEMS = [{"id": f"Q{i}", "name": name} for i, (_, _, name, _) in enumerate(QUESTIONS)]


def settings_with(**changes):
    """현재 설정에서 일부만 바꾼 설정 — 모델 · 검색 설정 변경을 흉내 낸다."""
    s = get_settings()
    parts = {}
    if "chat_model" in changes:
        parts["llm"] = dataclasses.replace(s.llm, chat_model=changes["chat_model"])
    if "search_type" in changes:
        parts["retrieval"] = dataclasses.replace(s.retrieval, search_type=changes["search_type"])
    return dataclasses.replace(s, **parts)


# ── 비교 · 지표 ───────────────────────────────────────────────────────────

class RagCompareTest(unittest.TestCase):
    def test_both_sides_get_the_same_complete_question(self):
        fake_ask.questions.clear()
        number, version, name, question = next(q for q in QUESTIONS if q[0] == 6)
        llm = FakeChat("근거 없이 답한 내용.")
        row = compare_one(number, {"id": "Q525", "name": name}, question, fake_ask, llm, version=version)
        self.assertIn("3월 21일~4월 19일", question)                          # 6번 v2 — 날짜 · 기준이 담긴 완전한 질문
        self.assertEqual(version, 2)
        self.assertIn(question, llm.received[0][-1].content)                  # RAG 없이 — 같은 질문
        self.assertEqual(fake_ask.questions, [question])                      # RAG — 같은 질문
        self.assertEqual(llm.received[0][0].content, BASELINE_SYSTEM)
        self.assertNotIn("[근거]", llm.received[0][-1].content)
        self.assertEqual((row["question_version"], row["rag"]["metrics"]["citations"]), (2, 1))
        self.assertTrue(row["rag"]["raw_answer"].endswith("⟦END⟧"))          # 원본 응답은 따로 보존

    def test_metrics(self):
        m = metrics("제공된 문서에서는 확인되지 않습니다. 약 444광년, 1582년 [근거 1][근거 2]")
        self.assertEqual((m["citations"], m["numbers"], m["not_found"]), (2, 2, True))

    def test_questions_match_plan_and_catalog(self):
        self.assertEqual([n for n, _, _, _ in QUESTIONS], list(range(1, 9)))
        names = {i["name"] for i in json.loads((get_settings().paths.data_dir / "items.json").read_text(encoding="utf-8"))["items"]}
        self.assertTrue({name for _, _, name, _ in QUESTIONS} <= names)

    def test_run_only_selected_and_each_row_has_run_info(self):
        run = run_info("r1", "2026-10-22T00:00:00+00:00")
        data = run_all(ITEMS, fake_ask, llm=FakeChat("답 1", "답 2"), only={3, 7}, progress=lambda _: None, run=run)
        self.assertEqual([r["number"] for r in data["rows"]], [3, 7])
        self.assertTrue(all(r["run"]["run_id"] == "r1" for r in data["rows"]))
        self.assertNotIn("model", data)                                       # 최상위 모델 · 시각 없음 — 문항별로만


# ── 실행 정보 · 병합 (리뷰 P2-1) ──────────────────────────────────────────

class RunInfoTest(unittest.TestCase):
    def test_run_info_records_conditions(self):
        r = run_info("r1", "t")
        for key in ("chat_model", "embedding_model", "retrieval", "chunking", "prompts", "code_version", "conditions_id"):
            self.assertIn(key, r)
        self.assertEqual(run_info("r2", "t2")["conditions_id"], r["conditions_id"])   # 같은 조건 — 실행 · 시각만 다름

    def test_conditions_change_with_model_or_retrieval(self):
        base = run_info("r1", "t")["conditions_id"]
        with mock.patch.object(rag_compare, "get_settings", return_value=settings_with(chat_model="gpt-other")):
            model_changed = run_info("r2", "t")["conditions_id"]
        with mock.patch.object(rag_compare, "get_settings", return_value=settings_with(search_type="mmr")):
            search_changed = run_info("r3", "t")["conditions_id"]
        self.assertEqual(len({base, model_changed, search_changed}), 3)


def row(number, run, version=1, answer="답"):
    return {"number": number, "question_version": version, "question": f"질문 {number}", "item_id": "Q1", "item_name": "x",
            "run": run, "baseline": {"answer": answer}, "rag": {"answer": answer}}


class MergeTest(unittest.TestCase):
    def test_partial_rerun_same_conditions(self):
        a, b = run_info("old", "2026-10-21T00:00:00+00:00"), run_info("new", "2026-10-22T00:00:00+00:00")
        merged = merge_results({"schema": 2, "rows": [row(1, a), row(2, a)]}, {"schema": 2, "rows": [row(2, b, answer="새 답")]})
        runs = {r["number"]: r["run"]["run_id"] for r in merged["rows"]}
        self.assertEqual(runs, {1: "old", 2: "new"})                          # 1번은 원래 실행 정보 그대로
        s = conditions_summary(merged["rows"])
        self.assertFalse(s["mixed"])                                          # 같은 조건 · 다른 실행
        self.assertEqual(s["groups"][0]["run_ids"], {"old", "new"})

    def test_partial_rerun_after_model_change_is_marked_mixed(self):
        a = run_info("old", "t1")
        with mock.patch.object(rag_compare, "get_settings", return_value=settings_with(chat_model="gpt-other")):
            b = run_info("new", "t2")
        merged = merge_results({"schema": 2, "rows": [row(1, a)]}, {"schema": 2, "rows": [row(2, b)]})
        self.assertEqual(merged["rows"][0]["run"]["chat_model"], a["chat_model"])
        self.assertTrue(conditions_summary(merged["rows"])["mixed"])

    def test_partial_rerun_after_retrieval_change_is_marked_mixed(self):
        a = run_info("old", "t1")
        with mock.patch.object(rag_compare, "get_settings", return_value=settings_with(search_type="mmr")):
            b = run_info("new", "t2")
        merged = merge_results({"schema": 2, "rows": [row(1, a)]}, {"schema": 2, "rows": [row(1, b, version=2)]})
        self.assertTrue(conditions_summary(merged["rows"])["mixed"])

    def test_legacy_rows_are_not_filled_from_current_settings(self):
        legacy = {"generated_at": "2026-10-22T05:30:24+00:00", "model": "gpt-6-luna",
                  "rows": [{"number": 1, "question": "q", "baseline": {}, "rag": {}}]}
        merged = merge_results(legacy, {"schema": 2, "rows": [row(2, run_info("new", "t"))]})
        old = next(r for r in merged["rows"] if r["number"] == 1)
        self.assertIsNone(old["run"])                                         # 추정해 채우지 않는다
        s = conditions_summary(merged["rows"])
        self.assertEqual((s["unknown"], s["mixed"]), ([1], True))

    def test_question_versions_kept_apart(self):
        a = run_info("old", "t1")
        merged = merge_results({"schema": 2, "rows": [row(6, a, version=1)]}, {"schema": 2, "rows": [row(6, a, version=2)]})
        self.assertEqual([(r["number"], r["question_version"]) for r in merged["rows"]], [(6, 1), (6, 2)])


class ScriptTest(unittest.TestCase):
    def run_script(self, argv, path):
        from scripts import compare_rag
        with mock.patch("builtins.print"):
            return compare_rag.main(argv, items=ITEMS, ask_fn=fake_ask, llm=FakeChat(*["답"] * 20), path=path)

    def test_full_run_archives_previous_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rag_comparison.json"
            path.write_text(json.dumps({"model": "old", "rows": [{"number": 1}]}), encoding="utf-8")
            self.assertEqual(self.run_script([], path), 0)
            archived = list((Path(tmp) / "archive").glob("rag_comparison_*.json"))
            self.assertEqual(len(archived), 1)
            self.assertEqual(json.loads(archived[0].read_text(encoding="utf-8"))["model"], "old")
            new = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual((new["schema"], len(new["rows"])), (2, 8))
            self.assertEqual(len({r["run"]["run_id"] for r in new["rows"]}), 1)

    def test_partial_run_preserves_other_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rag_comparison.json"
            self.run_script([], path)
            first = {r["number"]: r["run"]["run_id"] for r in json.loads(path.read_text(encoding="utf-8"))["rows"]}
            self.run_script(["--only", "3"], path)
            after = {r["number"]: r["run"]["run_id"] for r in json.loads(path.read_text(encoding="utf-8"))["rows"]}
            self.assertNotEqual(after[3], first[3])
            self.assertEqual({k: v for k, v in after.items() if k != 3}, {k: v for k, v in first.items() if k != 3})


# ── 답변 정리 · 언어 혼입 (리뷰 P2-2) ─────────────────────────────────────

class ReplyCleanupTest(unittest.TestCase):
    def test_control_marks_removed_content_kept(self):
        self.assertEqual(clean_reply("L2 주변을 맴돕니다.[근거 6]⟦END⟧"), "L2 주변을 맴돕니다.[근거 6]")
        self.assertEqual(clean_reply("답<|end|>"), "답")
        self.assertEqual(clean_reply("The quoted name is सूर्य [근거 1]."), "The quoted name is सूर्य [근거 1].")   # 문자권으로 지우지 않음

    def test_quoted_name_from_evidence_is_kept_without_retry(self):
        llm = FakeChat("산스크리트어 이름은 सूर्य(수리야)입니다.[근거 1]")
        result = generate_validated(llm, [], [SUN])
        self.assertEqual((result["status"], result["attempts"], result["notes"]), ("cited", 1, []))
        self.assertIn("सूर्य", result["answer"])

    def test_mixed_script_quote_kept(self):
        mixed = Evidence(number=1, chunk_id="c3", kind="외부 문서", source_type="위키백과", title="베텔게우스", section="",
                         url="u", text="이름은 아랍어 يد الجوزاء 에서 왔다. 산스크리트어 문헌에는 आर्द्रा 로 나온다.")
        result = generate_validated(FakeChat("아랍어 يد الجوزاء, 산스크리트어 आर्द्रा 에서 왔습니다.[근거 1]"), [], [mixed])
        self.assertEqual(result["attempts"], 1)
        self.assertIn("आर्द्रा", result["answer"])

    def test_stray_script_not_in_evidence_triggers_regeneration(self):
        llm = FakeChat("크게 다릅니다.[근거 1] એટલે 오리온자리는 멉니다.[근거 1]", "크게 다릅니다.[근거 1] 그래서 오리온자리는 멉니다.[근거 1]")
        result = generate_validated(llm, [], [EV])
        self.assertEqual((result["status"], result["attempts"]), ("cited", 2))
        self.assertNotIn("એટલે", result["answer"])
        self.assertIn("다른 언어 문자", result["issues"][0])
        self.assertIn("한국어로만", llm.received[1][-1].content)               # 재생성 요청

    def test_persisting_stray_script_is_flagged_not_silently_deleted(self):
        bad = "2012년에 넘었습니다.[근거 1] એટલે 지금은 성간 공간입니다.[근거 1]"
        result = generate_validated(FakeChat(bad, bad), [], [EV])
        self.assertEqual(result["status"], "cited")
        self.assertIn("지금은 성간 공간입니다", result["answer"])             # 사실 내용은 그대로
        self.assertIn("એટલે", result["answer"])                              # 지우지 않고
        self.assertTrue(result["notes"])                                       # 알린다

    def test_rejected_still_records_raw(self):
        result = generate_validated(FakeChat("지어낸 답 [근거 9]", "또 [근거 9]"), [], [EV])
        self.assertEqual((result["status"], result["raw_answer"]), ("rejected", "또 [근거 9]"))


class ConstellationEvidenceTest(unittest.TestCase):
    def test_constellation_gets_star_distance_table(self):
        from tests.test_sky_constellation import FIGURE, ORION
        from vasthorizon.features.extra_evidence import figure_evidence
        ev = figure_evidence(ORION, {"Q8860": FIGURE})
        self.assertEqual((ev.chunk_id, ev.source_type), ("figure:Q8860", "계산값 (카탈로그 좌표 · 거리)"))
        self.assertIn("가장 가까운 별: 타비트", ev.text)
        self.assertIsNone(figure_evidence({"id": "Q3409", "group": "star"}, {"Q8860": FIGURE}))

    def test_extra_evidence_falls_back_to_live_position(self):
        from vasthorizon.features import extra_evidence as mod
        with mock.patch.object(mod, "figure_evidence", return_value=None), \
                mock.patch.object(mod, "live_evidence", return_value=("live", None)) as live:
            self.assertEqual(mod.extra_evidence({"id": "Q48469", "group": "human_made"}), ("live", None))
        live.assert_called_once()


# ── Streamlit 'RAG 전후 비교' 탭 ──────────────────────────────────────────

class RagCompareTabTest(unittest.TestCase):
    def app(self, data):
        from streamlit.testing.v1 import AppTest
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        if data is not None:
            (Path(tmp.name) / "eval").mkdir()
            (Path(tmp.name) / "eval" / "rag_comparison.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        s = get_settings()
        patched = dataclasses.replace(s, paths=dataclasses.replace(s.paths, data_dir=Path(tmp.name)))
        for target, value in (("vasthorizon.config.get_settings", patched), ("vasthorizon.data.catalog.load_items", []),
                              ("vasthorizon.store.doc_index.indexed_item_ids", [])):
            p = mock.patch(target, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        at = AppTest.from_file(str(APP), default_timeout=30)
        at.run()
        return at

    def test_side_by_side_with_run_info(self):
        run = run_info("r1", "2026-10-22T05:00:00+00:00")
        r = compare_one(3, {"id": "Q48469", "name": "보이저 1호"}, "보이저 1호는 태양계를 벗어났나?", fake_ask,
                        FakeChat("이미 벗어났습니다."), run=run)
        at = self.app({"schema": 2, "rows": [r]})
        self.assertFalse(at.exception)
        headers = [m.value for m in at.markdown if m.value.startswith("####")]
        self.assertIn("#### RAG 없이 — 근거 없이 답함", headers)
        self.assertTrue(any("[근거 1] 보이저 1호" in e.label for e in at.expander))
        self.assertTrue(any("이 문항의 실행: r1" in c.value for c in at.caption))
        self.assertFalse([w for w in at.warning if "섞여" in w.value])          # 한 조건 — 섞임 경고 없음 (F2014 탭 경고는 별개)

    def test_mixed_conditions_warned(self):
        a = run_info("r1", "t1")
        with mock.patch.object(rag_compare, "get_settings", return_value=settings_with(chat_model="gpt-other")):
            b = run_info("r2", "t2")
        r1 = compare_one(1, {"id": "Q1", "name": "x"}, "q1", fake_ask, FakeChat("a"), run=a)
        r2 = compare_one(2, {"id": "Q2", "name": "y"}, "q2", fake_ask, FakeChat("b"), run=b)
        legacy = {**compare_one(3, {"id": "Q3", "name": "z"}, "q3", fake_ask, FakeChat("c")), "run": None}
        at = self.app({"schema": 2, "rows": [r1, r2, legacy]})
        self.assertTrue(any("섞여 있습니다" in w.value for w in at.warning))
        self.assertTrue(any("실행 정보 없음 — 문항 3" in c.value for c in at.caption))

    def test_no_results(self):
        at = self.app(None)
        self.assertTrue(any("저장된 비교 결과가 없습니다" in w.value for w in at.warning))


if __name__ == "__main__":
    unittest.main()
