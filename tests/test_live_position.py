"""실시간 위치 근거 테스트 — 질문한 날의 JPL Horizons 위치 (9번 작업 피드백).

Horizons 호출은 가짜로 바꾼다. 외부 호출 · 토큰 사용 없음.

    python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import unittest
from datetime import date
from unittest import mock

import requests

from tests.test_rag import VOYAGER, IsolatedRagTest
from vasthorizon.data import sources
from vasthorizon.data.item_text import build_item_text
from vasthorizon.data.items.common import AU_KM
from vasthorizon.features.live_position import horizons_command, live_evidence
from vasthorizon.rag.retrieval import Evidence, retrieve_evidence

TODAY = date(2026, 10, 22)
CATALOG_VOYAGER = {
    "id": "Q48469", "name": "보이저 1호", "group": "human_made", "kind": "우주선", "wiki_title": "보이저 1호",
    "name_en": "Voyager 1", "position_basis": "horizons", "position_au": [-30.0, -150.0, 35.0],
    "attrs": {"COSPAR ID": "1977-084A", "Horizons 위치 기준일": "2026-10-21"},
    "distance": {"km": 171.9 * AU_KM, "ly": 0.0027, "basis": "horizons", "reference": "지구 중심에서 천체 중심까지",
                 "approximate": False, "method": None, "km_min": None, "km_max": None, "n_values": 1},
    "sources": [{"name": "JPL Horizons", "url": "https://ssd.jpl.nasa.gov/horizons/"}],
}


def fake_positions(command, day):
    return {"-31": [173.0, 0.0, 0.0], "399": [1.0, 0.0, 0.0]}[command]


class HorizonsCommandTest(unittest.TestCase):
    def test_only_horizons_computed_items(self):
        self.assertEqual(horizons_command(CATALOG_VOYAGER), "-31")
        self.assertEqual(horizons_command({**CATALOG_VOYAGER, "position_basis": None}), None)      # 근삿값 · 미계산
        mars = {"position_basis": "horizons", "attrs": {"horizons_id": "499"}}
        self.assertEqual(horizons_command(mars), "499")
        self.assertIsNone(horizons_command({"position_basis": "horizons", "attrs": {"horizons_id": "399"}}))  # 지구
        self.assertIsNone(horizons_command(VOYAGER))                  # 테스트 고정 항목은 외부 호출 대상이 아님


class LiveEvidenceTest(unittest.TestCase):
    def test_today_distance_with_date_and_change(self):
        with mock.patch.object(sources, "horizons_position", side_effect=fake_positions) as spy:
            ev, warning = live_evidence(CATALOG_VOYAGER, TODAY)
        self.assertIsNone(warning)
        self.assertEqual({c.args for c in spy.call_args_list}, {("-31", "2026-10-22"), ("399", "2026-10-22")})
        self.assertIn("2026-10-22 기준", ev.text)
        self.assertIn("(173.0천문단위)", ev.text)                                 # 태양으로부터
        self.assertIn(f"({172 * AU_KM:,.0f}km)", ev.text)                         # 지구로부터 정확한 값
        last = ev.text.splitlines()[-1]                                           # 수집일(171.9AU)보다 멀어짐
        self.assertTrue(last.startswith("수집 기준일(2026-10-21) 값과 비교") and last.endswith("멀어짐"), last)

    def test_failure_falls_back_with_warning(self):
        for error in (requests.ConnectionError("down"), ValueError("bad")):
            with mock.patch.object(sources, "horizons_position", side_effect=error):
                ev, warning = live_evidence(CATALOG_VOYAGER, TODAY)
            self.assertIsNone(ev)
            self.assertIn("수집 기준일 값으로", warning)
        with mock.patch.object(sources, "horizons_position", return_value=None):
            self.assertIsNone(live_evidence(CATALOG_VOYAGER, TODAY)[0])

    def test_not_a_target_makes_no_call(self):
        with mock.patch.object(sources, "horizons_position") as spy:
            self.assertEqual(live_evidence({**CATALOG_VOYAGER, "position_basis": None}, TODAY), (None, None))
        spy.assert_not_called()


class ItemTextDateTest(unittest.TestCase):
    def test_horizons_distance_states_its_date(self):
        text = build_item_text(CATALOG_VOYAGER, 2026)
        self.assertIn("(2026-10-21 기준, JPL Horizons 계산)", text)
        star = {**CATALOG_VOYAGER, "distance": {**CATALOG_VOYAGER["distance"], "basis": "wikidata"}}
        self.assertNotIn("기준, JPL Horizons", build_item_text(star, 2026))


class LiveRetrievalTest(IsolatedRagTest):
    def test_live_evidence_comes_right_after_item(self):
        live = Evidence(number=0, chunk_id="live:Q48469:2026-10-22", kind="항목 메타데이터", source_type="JPL Horizons 실시간 계산",
                        title="보이저 1호 오늘 위치", section="", url="u", text="[보이저 1호 오늘 위치]\n2026-10-22 기준")
        found = retrieve_evidence(VOYAGER, "얼마나 멀리 갔어?", embedding=self.emb, db=self.db, live=lambda it: (live, None))
        self.assertEqual([ev.chunk_id for ev in found.evidences[:2]], ["Q48469", "live:Q48469:2026-10-22"])
        self.assertEqual([ev.number for ev in found.evidences], list(range(1, len(found.evidences) + 1)))

    def test_live_warning_is_reported(self):
        found = retrieve_evidence(VOYAGER, "질문", embedding=self.emb, db=self.db, live=lambda it: (None, "계산 실패"))
        self.assertIn("계산 실패", found.warnings)
        self.assertFalse(any(ev.chunk_id.startswith("live:") for ev in found.evidences))


if __name__ == "__main__":
    unittest.main()
