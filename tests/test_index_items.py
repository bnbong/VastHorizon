"""항목 색인 텍스트 · 메타데이터 색인 테스트 — 외부 호출 · 토큰 사용 없음.

    python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import unittest

from vasthorizon.data import item_text
from vasthorizon.data.items.common import LY_KM, REF_GEOCENTER, REF_SURFACE_ALTITUDE

REF_YEAR = 2026


def dist(km: float, **kw) -> dict:
    data = {"km": km, "ly": km / LY_KM, "basis": "wikidata", "reference": "지구에서 천체까지",
            "approximate": False, "method": None, "km_min": None, "km_max": None, "n_values": 1}
    data.update(kw)
    return data


def item(qid: str, name: str, group: str = "messier", **kw) -> dict:
    data = {"id": qid, "group": group, "name": name, "wiki_title": name, "name_en": None, "kind": "산개 성단",
            "distance": None, "ra_deg": 56.75, "dec_deg": 24.1, "attrs": {},
            "sources": [{"name": "Wikidata", "url": f"https://www.wikidata.org/wiki/{qid}"}]}
    data.update(kw)
    return data


class ItemTextTest(unittest.TestCase):
    def test_korean_number_units(self):
        self.assertEqual(item_text.korean_number(2_540_000), "254만")
        self.assertEqual(item_text.korean_number(227_300_000), "2.27억")
        self.assertEqual(item_text.korean_number(393_000), "39.3만")
        self.assertEqual(item_text.korean_number(639), "639")

    def test_light_time(self):
        self.assertEqual(item_text.light_time_text(384_400), "약 1.3초")
        self.assertEqual(item_text.light_time_text(149_597_870), "약 8.3분")
        self.assertEqual(item_text.light_time_text(439 * LY_KM), "약 439년")

    def test_departure_year_and_era(self):
        self.assertEqual(item_text.departure_year(439, REF_YEAR), 1587)
        self.assertEqual(item_text.korean_era(1587), "조선 시대")
        self.assertEqual(item_text.korean_era(1180), "고려 시대")
        self.assertEqual(item_text.departure_year(2100, REF_YEAR), -75)   # 0년이 없으므로 기원전 75년
        self.assertEqual(item_text.year_text(-75), "기원전 75년")

    def test_josa(self):
        self.assertEqual(item_text.josa("보이저 1호", "은는"), "보이저 1호는")
        self.assertEqual(item_text.josa("다누리", "은는"), "다누리는")
        self.assertEqual(item_text.copula("산개 성단"), "산개 성단이다")
        self.assertEqual(item_text.copula("소멸(재진입)"), "소멸(재진입)이다")
        self.assertEqual(item_text.euro("항성"), "항성으로")
        self.assertEqual(item_text.euro("별자리"), "별자리로")
        self.assertEqual(item_text.euro("나선 은하"), "나선 은하로")

    def test_summary_sentence_from_attributes_only(self):
        voyager = item("Q48469", "보이저 1호", group="human_made", kind="우주 탐사선",
                       attrs={"국가": "미국", "발사일": "1977-09-05", "현재 위치": "태양계 탈출 궤도 (Horizons 직접 계산)",
                              "운용 상태": "확장 임무"})
        self.assertEqual(item_text.summary_sentence(voyager),
                         "보이저 1호는 미국이 1977년에 발사한 우주 탐사선이다. "
                         "지금은 태양계를 벗어나 성간 공간 쪽으로 날아가고 있다. 운용 상태는 확장 임무다.")
        tiangong = item("Q1", "톈궁 1호", group="human_made", kind="우주정거장",
                        attrs={"국가": "중국", "발사일": "2011-09-29", "현재 위치": "대기권 재진입 (2018-04-02)"})
        self.assertIn("2018-04-02에 대기권으로 재진입해 지금은 궤도에 없다", item_text.summary_sentence(tiangong))

    def test_text_has_search_attributes(self):
        pleiades = item("Q13423", "플레이아데스 성단", name_en="Pleiades",
                        attrs={"별자리": "황소자리", "맨눈 관측": True},
                        distance=dist(439 * LY_KM, km_min=424 * LY_KM, km_max=444 * LY_KM, n_values=3))
        text = item_text.build_item_text(pleiades, REF_YEAR)
        self.assertIn("[메시에 천체] 플레이아데스 성단 (Pleiades)", text)
        self.assertIn("맨눈 관측: 예", text)
        self.assertIn("약 439광년 (출처 3개 값의 중앙값, 범위 424~444광년)", text)
        self.assertIn("1587년 무렵 (조선 시대)", text)

    def test_surface_altitude_is_not_light_distance(self):
        sat = item("Q1", "아리랑 1호", group="human_made", kind="지구 관측 위성",
                   attrs={"한국 관련": True},
                   distance=dist(639, reference=REF_SURFACE_ALTITUDE, approximate=True, method="고도 평균"),
                   sources=[{"name": "Wikidata", "url": "u"},
                            {"name": "JPL Horizons", "url": "u", "used_for": "표시용 근삿값 — 지구 위치"}])
        text = item_text.build_item_text(sat, REF_YEAR)
        self.assertIn("지표면 위 고도 약 639km (근삿값 · 고도 평균)", text)
        self.assertNotIn("빛이 걸리는 시간", text)
        self.assertNotIn("JPL Horizons", text)             # 표시용으로만 쓴 출처는 근거에서 뺀다

    def test_false_attrs_hidden_except_informative(self):
        star = item("Q2", "어떤 별", group="star", attrs={"한국 관련": False, "맨눈 관측": False})
        text = item_text.build_item_text(star, REF_YEAR)
        self.assertNotIn("한국 관련", text)
        self.assertIn("맨눈 관측: 아니오", text)

    def test_metadata_scalar_only_with_filters(self):
        probe = item("Q3", "다누리", group="human_made", ra_deg=None, dec_deg=None,
                     attrs={"한국 관련": True}, distance=dist(393_000, basis="horizons", reference=REF_GEOCENTER))
        text = item_text.build_item_text(probe, REF_YEAR)
        meta = item_text.build_item_metadata(probe, REF_YEAR, text)
        self.assertTrue(all(isinstance(v, (str, int, float, bool)) for v in meta.values()))
        self.assertEqual(meta["item_id"], "Q3")
        self.assertEqual(meta["source_type"], "항목 메타데이터")
        self.assertTrue(meta["korean"])
        self.assertNotIn("light_departure_year", meta)      # 1광년 미만
        self.assertNotIn("ra_deg", meta)

    def test_korean_number_keeps_integer_zeros(self):
        """[P1] 정수부의 0을 지우지 않고, 반올림 경계에서는 한 단위 위로 올린다."""
        cases = {
            1_000_000: "100만", 1_500_000: "150만", 10_000_000: "1,000만", 100_000_000_000_000: "100조",
            9_999: "9,999", 9_999.7: "1만", 10_000: "1만", 99_999_999: "1억", 100_000_000: "1억",
            10**12: "1조", 12_345: "1.23만", 120_000: "12만", 1_050_000: "105만", 639: "639", 8.6: "8.6",
        }
        for value, expected in cases.items():
            self.assertEqual(item_text.korean_number(value), expected, value)


class MilkyWayTextTest(unittest.TestCase):
    """우리 은하 — '우리 은하까지 n광년' · '지금 보는 빛이 출발한 때'가 새어 나오지 않는다."""

    def setUp(self):
        from tests.test_collect_items import milky_way_items
        self.galaxy, self.sgr = milky_way_items()

    def test_distance_text_is_to_galactic_center(self):
        self.assertTrue(item_text.distance_text(self.galaxy["distance"]).startswith("지구에서 우리 은하 중심까지 약 2.6만광년"))

    def test_summary_sentences(self):
        galaxy = item_text.summary_sentence(self.galaxy)
        self.assertTrue(galaxy.startswith("우리 은하는 막대나선은하다. 지구에서 은하 중심까지 약 2.6만광년이다."), galaxy)
        self.assertNotIn("우리 은하까지", galaxy)
        self.assertNotIn("떨어져 있다", galaxy)
        self.assertEqual(item_text.summary_sentence(self.sgr),
                         "궁수자리 A*는 궁수자리에 있는 초거대질량 블랙홀로, 지구에서 약 2.6만광년 떨어져 있다.")

    def test_item_text_has_no_light_departure(self):
        galaxy = item_text.build_item_text(self.galaxy, REF_YEAR)
        self.assertIn("[우리 은하] 우리 은하 (Milky Way)", galaxy)
        self.assertNotIn("빛이 걸리는 시간", galaxy)                   # 한 점에서 출발한 빛이 아니다
        self.assertNotIn("지금 보는 빛이 출발한 때", galaxy)
        sgr = item_text.build_item_text(self.sgr, REF_YEAR)
        self.assertIn("빛이 걸리는 시간: 약 2.6만년", sgr)
        self.assertNotIn("지금 보는 빛이 출발한 때", sgr)              # 눈으로 보지 못하는 천체
        self.assertIn("(Wikidata 값 · 불확도 범위 2.46만~2.74만광년)", sgr)

    def test_light_lines_departure_flag(self):
        dist_ = dist(439 * LY_KM)
        self.assertEqual(len(item_text.light_lines(dist_, REF_YEAR)), 2)
        self.assertEqual(item_text.light_lines(dist_, REF_YEAR, departure=False), ["빛이 걸리는 시간: 약 439년"])

    def test_metadata(self):
        galaxy = item_text.build_item_metadata(self.galaxy, REF_YEAR, "t")
        for key in ("distance_km", "distance_ly", "light_departure_year"):
            self.assertNotIn(key, galaxy)                              # '가장 가까운 은하' · 거리 조건에 걸리지 않는다
        self.assertEqual(galaxy["distance_reference"], "지구에서 우리 은하 중심까지")
        self.assertEqual((galaxy["group"], galaxy["group_ko"], galaxy["category"]), ("milky_way", "우리 은하", "은하"))
        self.assertIs(galaxy["black_hole"], True)
        self.assertEqual(galaxy["black_hole_name"], "궁수자리 A*")
        self.assertIs(galaxy["seoul_visible"], True)
        sgr = item_text.build_item_metadata(self.sgr, REF_YEAR, "t")
        self.assertAlmostEqual(sgr["distance_ly"], 26000)
        self.assertNotIn("light_departure_year", sgr)
        self.assertEqual(sgr["category"], "블랙홀")
        self.assertIs(sgr["black_hole"], True)                         # 블랙홀 자체 — '블랙홀' 조건에 걸린다
        self.assertEqual(sgr["black_hole_name"], "궁수자리 A*")
        self.assertEqual(sgr["black_hole_mass"], "약 410만 태양질량 (Wikidata 값 3개, 402만~431만)")
        self.assertEqual(sgr["black_hole_source"], "Wikidata https://www.wikidata.org/wiki/Q237284")
        self.assertNotIn("seoul_visible", sgr)
        self.assertNotIn("중심에", item_text.fact_sentences(self.sgr))     # '중심에 … 블랙홀이 있다'는 은하에만


if __name__ == "__main__":
    unittest.main()


