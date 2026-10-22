"""별자리 펼치기 · 오늘 밤 나의 하늘 테스트 (F2010).

천문 계산은 알려진 값(북극성 고도 ≈ 위도, 지점 · 분점의 태양 적위)으로 확인한다.
가짜 LLM · 가짜 수집기를 쓴다. 외부 호출 · 토큰 사용 없음.

    python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import math
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient

from tests.fakes import FakeChat
from tests.test_api import ITEMS as API_ITEMS, FakeAsk, healthy
from tests.test_features import StubCollector, item, year_doc
from vasthorizon.api.app import create_app
from vasthorizon.api.services import Services
from vasthorizon.data.constellation_figures import figure_stats, load_figures, split_at_gaps
from vasthorizon.features import constellation
from vasthorizon.features.constellation import FigureUnavailableError, UnfoldResult, figure_for, star_table, unfold
from vasthorizon.features.evidence import COMPUTED_SOURCE
from vasthorizon.features.sky import (
    KST, SkyGuide, SkyInputError, SkyObject, SkyView, alt_az, as_aware, compute_sky, direction, local_sidereal_deg, mean_direction,
    sky_guide, sun_ra_dec,
)
from vasthorizon.rag.graph import REJECTED_ANSWER

REF_YEAR = 2026
POLARIS = (37.95, 89.26)          # 적경 · 적위 (도)


def star(hip, name, ly, mag, ra=83.0, dec=5.0) -> dict:
    return {"hip": hip, "name": name, "item_id": None, "ra_deg": ra, "dec_deg": dec, "mag": mag,
            "distance_ly": ly, "distance_basis": "wikidata" if ly else None}


ORION = item("Q8860", "오리온자리", "constellation", "별자리", **{"관측 계절": "겨울"})
FIGURE = {"item_id": "Q8860", "name": "오리온자리", "lines": [[1, 2], [2, 3, 4]],
          "stars": {"1": star(1, "타비트", 26.2, 3.19), "2": star(2, "베텔게우스", 548, 0.45),
                    "3": star(3, "먼 별", 5285, 4.64), "4": star(4, "거리 모름", None, 3.0)}}


def lst_zero_time(lon: float) -> datetime:
    """경도 lon에서 지방 항성시가 0도가 되는 시각 (2026-10-21 근처)."""
    at = datetime(2026, 10, 21, tzinfo=timezone.utc)
    return at - timedelta(days=local_sidereal_deg(at, lon) / 360.98564736629)


# ── 천문 계산 ─────────────────────────────────────────────────────────────

class SkyMathTest(unittest.TestCase):
    def test_polaris_altitude_equals_latitude(self):
        # 북극성은 천구 북극에서 1도 안 — 어느 시각이든 고도 ≈ 위도
        for lat in (37.57, 10.0, 60.0):
            for hour in (0, 6, 13, 21):
                at = as_aware(datetime(2026, 10, 22, hour))
                alt, _ = alt_az(*POLARIS, lat, local_sidereal_deg(at, 126.98))
                self.assertAlmostEqual(alt, lat, delta=1.0)

    def test_meridian_transit(self):
        # 시간각 0 (남중) — 고도 90 − |위도 − 적위|, 적위가 위도보다 낮으면 남쪽
        alt, az = alt_az(ra_deg=100.0, dec_deg=-10.0, lat=37.5, lst_deg=100.0)
        self.assertAlmostEqual(alt, 42.5, places=6)
        self.assertEqual(direction(az), "남")

    def test_east_and_west(self):
        # 적도의 별이 적도 관측자 기준 시간각 −90도면 동쪽 지평선, +90도면 서쪽 지평선
        alt, az = alt_az(ra_deg=90.0, dec_deg=0.0, lat=0.0, lst_deg=0.0)
        self.assertAlmostEqual(alt, 0.0, places=6)
        self.assertAlmostEqual(az, 90.0, places=6)
        _, az = alt_az(ra_deg=0.0, dec_deg=0.0, lat=0.0, lst_deg=90.0)
        self.assertAlmostEqual(az, 270.0, places=6)

    def test_directions(self):
        self.assertEqual([direction(a) for a in (0, 44, 46, 90, 180, 270, 338, 359.9)],
                         ["북", "북동", "북동", "동", "남", "서", "북", "북"])

    def test_naive_time_is_korea(self):
        self.assertEqual(as_aware(datetime(2026, 10, 22, 21)).utcoffset(), timedelta(hours=9))
        utc = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
        self.assertEqual(as_aware(utc), utc)

    def test_sun_declination_at_solstice_and_equinox(self):
        _, dec = sun_ra_dec(datetime(2026, 6, 21, 8, 24, tzinfo=timezone.utc))
        self.assertAlmostEqual(dec, 23.44, delta=0.05)
        _, dec = sun_ra_dec(datetime(2026, 3, 20, 14, 46, tzinfo=timezone.utc))
        self.assertAlmostEqual(dec, 0.0, delta=0.05)

    def test_mean_direction_across_zero_ra(self):
        # 적경 359도와 1도의 평균은 0도 — 단순 평균(180도)이 아니다
        ra, dec = mean_direction([{"ra_deg": 359.0, "dec_deg": 10.0}, {"ra_deg": 1.0, "dec_deg": 10.0}])
        self.assertAlmostEqual(min(ra, 360 - ra), 0.0, places=6)
        self.assertAlmostEqual(dec, 10.0, delta=0.01)


# ── 하늘 위치 ─────────────────────────────────────────────────────────────

def solar(qid, name, pos) -> dict:
    return {**item(qid, name, "solar_system", "행성"), "position_au": pos,
            "attrs": {"Horizons 위치 기준일": "2026-10-21"}}


SKY_ITEMS = [
    item("Q10", "작은곰자리", "constellation", "별자리"),
    item("Q11", "남쪽 별자리", "constellation", "별자리"),
    {**item("Q12", "좌표만 있는 별자리", "constellation", "별자리"), "ra_deg": 37.95, "dec_deg": 89.26},
    solar("Q2", "지구", [1.0, 0.0, 0.0]),
    solar("Q111", "화성", [2.0, 0.0, 0.0]),          # 지구에서 보면 적경 0 · 적위 0
    solar("Q319", "목성", [-4.0, 0.0, 0.0]),         # 지구에서 보면 적경 180 — 지평선 아래
]
SKY_FIGURES = {"Q10": {"stars": {"1": star(1, "북극성", 433, 1.98, *POLARIS)}},
               "Q11": {"stars": {"1": star(1, "남쪽 별", 100, 1.0, 100.0, -80.0)}}}


class ComputeSkyTest(unittest.TestCase):
    def test_visible_constellations_and_planets(self):
        at = lst_zero_time(0.0)                         # 적도 · 경도 0, 지방 항성시 0 — 적경 0이 머리 위
        view = compute_sky(SKY_ITEMS, SKY_FIGURES, 0.0, 0.0, at)
        self.assertEqual([p.name for p in view.planets], ["화성"])
        self.assertAlmostEqual(view.planets[0].alt_deg, 90.0, delta=0.2)
        self.assertEqual(view.planets[0].direction, "머리 위")           # 천정 근처는 방위 대신
        self.assertEqual(view.notes, [])

    def test_constellation_threshold_and_fallback_coordinates(self):
        view = compute_sky(SKY_ITEMS, SKY_FIGURES, 37.57, 126.98, datetime(2026, 10, 22, 21))
        names = [c.name for c in view.constellations]
        self.assertIn("작은곰자리", names)               # 모양 데이터의 별 방향
        self.assertIn("좌표만 있는 별자리", names)        # 모양 데이터가 없으면 항목 좌표
        self.assertNotIn("남쪽 별자리", names)           # 적위 −80도 — 서울에서는 뜨지 않는다
        self.assertEqual(view.constellations, sorted(view.constellations, key=lambda o: -o.alt_deg))

    def test_planets_skipped_far_from_epoch(self):
        view = compute_sky(SKY_ITEMS, SKY_FIGURES, 37.57, 126.98, datetime(2026, 12, 25, 21))
        self.assertEqual(view.planets, [])
        self.assertIn("2026-10-21", view.notes[0])

    def test_invalid_location(self):
        with self.assertRaises(SkyInputError):
            compute_sky(SKY_ITEMS, SKY_FIGURES, 95.0, 0.0)


class SkyGuideTest(unittest.TestCase):
    def night_view(self):
        view = compute_sky(SKY_ITEMS, SKY_FIGURES, 37.57, 126.98, datetime(2026, 10, 22, 21))
        self.assertTrue(view.is_night)
        return view

    def test_daytime_makes_no_llm_call(self):
        view = compute_sky(SKY_ITEMS, SKY_FIGURES, 37.57, 126.98, datetime(2026, 10, 22, 12))
        result = sky_guide(view, SKY_ITEMS, REF_YEAR, llm=FakeChat())     # 호출되면 FakeChat이 실패한다
        self.assertEqual((result.status, result.guide), ("daytime", None))

    def test_guide_evidence_is_computed_table_and_catalog(self):
        llm = FakeChat("북쪽 하늘 높이 작은곰자리가 있어요 [근거 1]. [근거 2]")
        result = sky_guide(self.night_view(), SKY_ITEMS, REF_YEAR, llm=llm)
        self.assertEqual(result.status, "cited")
        table = result.evidences[0]
        self.assertEqual((table.number, table.source_type), (1, COMPUTED_SOURCE))
        self.assertIn("작은곰자리: 북쪽 하늘", table.text)
        self.assertNotIn("머리 위", table.text)
        self.assertEqual([ev.number for ev in result.evidences], list(range(1, len(result.evidences) + 1)))
        self.assertEqual(result.evidences[1].chunk_id, result.view.constellations[0].item_id)

    def view(self, constellations, planets, notes=()):
        return SkyView(lat=37.57, lon=126.98, at=as_aware(datetime(2026, 10, 22, 21)), sun_alt_deg=-30.0,
                       constellations=constellations, planets=planets, notes=list(notes))

    def test_planets_only_still_guided(self):
        mars = SkyObject("화성", "Q111", "solar_system", 40.0, 120.0, "남동")
        llm = FakeChat("남동쪽 하늘 고도 약 40도에 화성이 있어요 [근거 1].")
        result = sky_guide(self.view([], [mars]), SKY_ITEMS, REF_YEAR, llm=llm)
        self.assertEqual((result.status, len(result.evidences)), ("cited", 1))
        self.assertIn("행성 화성: 남동쪽 하늘", result.evidences[0].text)

    def test_nothing_visible_is_empty_without_llm_and_keeps_notes(self):
        result = sky_guide(self.view([], [], notes=["행성 위치 기준일 초과"]), SKY_ITEMS, REF_YEAR, llm=FakeChat())
        self.assertEqual((result.status, result.guide), ("empty", None))
        self.assertEqual(result.warnings[0], "행성 위치 기준일 초과")

    def test_notes_kept_in_daytime_and_guided_results(self):
        day = compute_sky(SKY_ITEMS, SKY_FIGURES, 37.57, 126.98, datetime(2026, 12, 25, 12))
        self.assertIn("2026-10-21", sky_guide(day, SKY_ITEMS, REF_YEAR, llm=FakeChat()).warnings[0])
        night = compute_sky(SKY_ITEMS, SKY_FIGURES, 37.57, 126.98, datetime(2026, 12, 25, 21))
        result = sky_guide(night, SKY_ITEMS, REF_YEAR, llm=FakeChat("[근거 1] 북쪽 하늘이에요."))
        self.assertEqual(result.status, "cited")
        self.assertIn("2026-10-21", result.warnings[0])

    def test_invalid_citation_is_rejected(self):
        result = sky_guide(self.night_view(), SKY_ITEMS, REF_YEAR, llm=FakeChat("지어낸 안내 [근거 9].", "또 [근거 9]."))
        self.assertEqual((result.status, result.guide), ("rejected", REJECTED_ANSWER))


# ── 별자리 펼치기 ─────────────────────────────────────────────────────────

class UnfoldTest(unittest.TestCase):
    def test_figure_for(self):
        self.assertIs(figure_for(ORION, {"Q8860": FIGURE}), FIGURE)
        with self.assertRaises(FigureUnavailableError):
            figure_for(ORION, {})
        with self.assertRaises(FigureUnavailableError):
            figure_for(item("Q3409", "시리우스", "star", "항성", 8.6), {"Q3409": FIGURE})

    def test_star_table_keeps_nearest_and_farthest(self):
        with mock.patch.object(constellation, "TABLE_STARS", 1):        # 밝은 별 1개만 — 베텔게우스
            lines = star_table(FIGURE, figure_stats(FIGURE))
        body = [l for l in lines if l.startswith("- ")]
        self.assertEqual([l.split(" (")[0] for l in body], ["- 타비트", "- 베텔게우스", "- 먼 별"])   # 거리순
        self.assertIn("4개 중 거리가 알려진 별 3개", lines[0])
        self.assertIn("약 201.7배", lines[1])

    def test_unfold_evidence_and_own_doc(self):
        collector = StubCollector(year_doc("오리온자리"))
        llm = FakeChat("가장 가까운 타비트는 약 26.2광년이에요 [근거 2]. 오리온자리는 겨울 별자리예요 [근거 1].")
        result = unfold(ORION, FIGURE, REF_YEAR, llm=llm, collector=collector)
        self.assertEqual((result.status, collector.titles), ("cited", ["오리온자리"]))
        self.assertEqual([ev.number for ev in result.evidences], [1, 2, 3])
        self.assertIn("26.2광년", llm.received[0][-1].content)
        self.assertEqual(result.warnings, [])

    def test_unfold_without_doc_still_works(self):
        result = unfold(ORION, FIGURE, REF_YEAR, llm=FakeChat("약 26.2광년 [근거 2]."), collector=StubCollector(None))
        self.assertEqual((result.status, len(result.evidences)), ("cited", 2))
        self.assertIn("오리온자리", result.warnings[0])

    def test_too_few_known_distances(self):
        sparse = {**FIGURE, "stars": {"1": FIGURE["stars"]["1"], "4": FIGURE["stars"]["4"]}}
        with self.assertRaises(FigureUnavailableError):
            unfold(ORION, sparse, REF_YEAR, llm=FakeChat(), collector=StubCollector(None))   # LLM 호출 전에 막는다


class SplitAtGapsTest(unittest.TestCase):
    """8b 리뷰 — 미매칭 꼭짓점(None) 앞뒤 별을 직접 잇지 않는다."""

    def test_gap_in_middle(self):
        self.assertEqual(split_at_gaps([1, None, 3]), [])               # A → C를 만들지 않는다
        self.assertEqual(split_at_gaps([1, 2, None, 4, 5]), [[1, 2], [4, 5]])

    def test_gap_at_ends(self):
        self.assertEqual(split_at_gaps([None, 1, 2, 3]), [[1, 2, 3]])
        self.assertEqual(split_at_gaps([1, 2, 3, None]), [[1, 2, 3]])
        self.assertEqual(split_at_gaps([None, None]), [])

    def test_no_gap(self):
        self.assertEqual(split_at_gaps([1, 2, 3]), [[1, 2, 3]])

    def test_real_cetus_has_no_invented_line(self):
        # 실제 데이터 — 고래자리 선에서 HIP 12387 다음 꼭짓점이 미매칭: HIP 12387 – HIP 8645를 잇지 않는다
        figures = load_figures()
        cetus = next((f for f in figures.values() if f["name"] == "고래자리"), None)
        if cetus is None:
            self.skipTest("data/constellations.json 없음")
        pairs = {frozenset(p) for line in cetus["lines"] for p in zip(line, line[1:])}
        self.assertNotIn(frozenset((12387, 8645)), pairs)
        for line in cetus["lines"]:
            self.assertTrue(all(str(h) in cetus["stars"] for h in line))


# ── API ──────────────────────────────────────────────────────────────────

class SkyConstellationApiTest(unittest.TestCase):
    def client(self, sky_result=None):
        self.unfold_calls, self.sky_calls = [], []

        def fake_unfold(it, figure):
            self.unfold_calls.append((it["id"], figure["name"]))
            return UnfoldResult(item=it, figure=figure, stats=figure_stats(figure), explanation="설명 [근거 2]",
                                status="cited", cited=[], evidences=[])

        def fake_sky(view):
            self.sky_calls.append(view)
            return sky_result or SkyGuide(view=view, guide="안내 [근거 1]", status="cited")

        services = Services(items=API_ITEMS, ask=FakeAsk(), health=healthy, figures={"Q8860": FIGURE},
                            unfold=fake_unfold, sky_guide=fake_sky)
        return TestClient(create_app(services, web_dir=None), raise_server_exceptions=False)

    def test_figure(self):
        body = self.client().get("/api/constellations/Q8860/figure").json()
        self.assertEqual(body["lines"], [[1, 2], [2, 3, 4]])
        self.assertEqual([s["hip"] for s in body["stars"]], [2, 4, 1, 3])     # 밝은 순
        self.assertEqual((body["stats"]["nearest_hip"], body["stats"]["farthest_hip"]), (1, 3))
        self.assertIn("d3-celestial", body["licenses"])

    def test_figure_errors(self):
        c = self.client()
        r = c.get("/api/constellations/Q48469/figure")             # 별자리가 아님
        self.assertEqual((r.status_code, r.json()["code"]), (422, "figure_unavailable"))
        r = c.get("/api/constellations/Q999/figure")
        self.assertEqual((r.status_code, r.json()["code"]), (404, "item_not_found"))

    def test_unfold(self):
        c = self.client()
        body = c.post("/api/constellations/Q8860/unfold").json()
        self.assertEqual((body["status"], body["stats"]["known"], self.unfold_calls),
                         ("cited", 3, [("Q8860", "오리온자리")]))

    def test_sky_without_guide_makes_no_guide_call(self):
        c = self.client()
        body = c.post("/api/sky", json={"lat": 37.57, "lon": 126.98, "at": "2026-10-22T21:00:00", "guide": False}).json()
        self.assertEqual((body["status"], body["guide"], self.sky_calls), ("skipped", None, []))
        self.assertTrue(body["is_night"])
        self.assertEqual(body["at"][-6:], "+09:00")                 # 시간대 없는 시각은 한국 시간

    def test_sky_with_guide(self):
        body = self.client().post("/api/sky", json={"lat": 37.57, "lon": 126.98}).json()
        self.assertEqual((body["status"], body["guide"], len(self.sky_calls)), ("cited", "안내 [근거 1]", 1))

    def test_sky_daytime_has_no_notice(self):
        c = self.client()
        c.app.state.services.sky_guide = lambda view: SkyGuide(view=view, guide=None, status="daytime",
                                                              warnings=["낮"])
        body = c.post("/api/sky", json={"lat": 37.57, "lon": 126.98}).json()
        self.assertEqual((body["status"], body["notice"], body["warnings"]), ("daytime", None, ["낮"]))

    def test_sky_invalid_location(self):
        r = self.client().post("/api/sky", json={"lat": 100, "lon": 0})
        self.assertEqual((r.status_code, r.json()["code"]), (422, "invalid_request"))


if __name__ == "__main__":
    unittest.main()
