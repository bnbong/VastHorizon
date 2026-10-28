"""항목 메타데이터 수집 파이프라인 회귀 테스트 — 외부 호출 없음.

    python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from scripts import collect_items
from vasthorizon.data import catalog, sources
from vasthorizon.data.enrich import enrich_items
from vasthorizon.data.items import human_made, milky_way
from vasthorizon.data.items.common import (
    AU_KM, LY_KM, REF_GALACTIC_CENTER, REF_GEOCENTER, REF_SURFACE_ALTITUDE, Distance, Item,
)

EPOCH = "2026-10-21"
EARTH_POS = [0.9, 0.4, 0.17]
MOON_POS = [0.9025, 0.4, 0.17]


def make_items(n: int) -> list[Item]:
    """카탈로그 그룹(GROUP_KEYS)에 고르게 나눈 유효한 항목 n개."""
    groups = catalog.GROUP_KEYS
    return [
        Item(id=f"Q{i + 1}", group=groups[i % len(groups)], name=f"항목{i}", wiki_title=f"항목{i}",
             sources=[{"name": "Wikidata", "url": f"https://www.wikidata.org/wiki/Q{i + 1}"}])
        for i in range(n)
    ]


def bodies() -> dict[str, Item]:
    earth = Item(id="Q2", group="solar_system", name="지구", wiki_title="지구",
                 position_au=EARTH_POS, position_basis="horizons")
    moon = Item(id="Q405", group="solar_system", name="달", wiki_title="달",
                position_au=MOON_POS, position_basis="horizons",
                distance=Distance(km=384_400, basis="horizons", reference=REF_GEOCENTER))
    return {"Earth": earth, "Moon": moon}


def satcat_row(**kw) -> dict:
    row = {"OBJECT_NAME": "SAT", "OBJECT_ID": "2000-001A", "OBJECT_TYPE": "PAY", "OPS_STATUS_CODE": "+",
           "OWNER": "US", "LAUNCH_DATE": "2000-01-01", "DECAY_DATE": "", "PERIOD": "95.0",
           "APOGEE": "600", "PERIGEE": "500", "ORBIT_CENTER": "EA", "ORBIT_TYPE": "ORB"}
    row.update(kw)
    return row


# ── [P1] 1. 실패한 수집이 기존 카탈로그를 덮어쓰지 않는다 ────────────────────

class CatalogSaveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "items.json"
        catalog.save_items([it.to_dict() for it in make_items(120)], {"total": 120}, self.path)
        self.original = self.path.read_bytes()
        self.patch = mock.patch.object(catalog, "items_path", return_value=self.path)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def run_main(self, items: list[Item]) -> int:
        with mock.patch.object(collect_items, "collect_all", return_value=items), redirect_stdout(io.StringIO()):
            return collect_items.main(["--epoch", EPOCH])

    def test_zero_items_keeps_existing_file(self):
        self.assertEqual(self.run_main([]), 1)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_99_items_keeps_existing_file(self):
        self.assertEqual(self.run_main(make_items(99)), 1)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_collector_exception_keeps_existing_file(self):
        with mock.patch.object(collect_items, "collect_all", side_effect=RuntimeError("boom")), \
                redirect_stdout(io.StringIO()):
            self.assertEqual(collect_items.main(["--epoch", EPOCH]), 1)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_valid_collection_replaces_file(self):
        self.assertEqual(self.run_main(make_items(130)), 0)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8"))["meta"]["total"], 130)

    def test_write_failure_preserves_file_and_cleans_temp(self):
        with mock.patch("vasthorizon.data.atomic.os.replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                catalog.save_items([it.to_dict() for it in make_items(130)], {}, self.path)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual([p.name for p in self.path.parent.iterdir()], ["items.json"])

    def test_invalid_epoch_rejected_before_collection(self):
        with mock.patch.object(collect_items, "collect_all") as collect, redirect_stdout(io.StringIO()), \
                mock.patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit):
                collect_items.main(["--epoch", "2026-13-40"])
            collect.assert_not_called()

    def test_validation_rejects_duplicate_qid_and_bad_coordinates(self):
        items = [it.to_dict() for it in make_items(120)]
        items[1]["id"] = items[0]["id"]
        items[2]["ra_deg"] = 400
        items[3]["position_au"] = [0, 0, 0]          # 근거 없는 실제 좌표
        errors = catalog.validate_items(items)
        self.assertTrue(any("QID 중복" in e for e in errors))
        self.assertTrue(any("적경" in e for e in errors))
        self.assertTrue(any("position_basis" in e for e in errors))


    def test_validation_requires_milky_way_group(self):
        items = [it.to_dict() for it in make_items(120) if it.group != "milky_way"]
        self.assertIn("그룹 milky_way 항목 0건", catalog.validate_items(items, min_items=1))

# ── [P1] 2 · 3. 실제 좌표와 근삿값을 구분한다 ──────────────────────────────

class LocateTest(unittest.TestCase):
    def test_earth_orbit_has_no_real_position(self):
        place = human_made.locate(satcat_row(), None, EARTH_POS, bodies(), EPOCH, EPOCH)
        self.assertIsNone(place.position_au)
        self.assertIsNone(place.position_basis)
        self.assertEqual(place.position_proxy["body"], "지구")
        self.assertEqual(place.distance.reference, REF_SURFACE_ALTITUDE)
        self.assertTrue(place.distance.approximate)
        self.assertEqual(place.distance.km, 550)

    def test_horizons_failure_on_moon_orbit_is_marked_as_proxy(self):
        place = human_made.locate(satcat_row(ORBIT_CENTER="MO"), None, EARTH_POS, bodies(), EPOCH, EPOCH)
        self.assertIsNone(place.position_au)
        self.assertEqual(place.position_proxy["body"], "달")
        self.assertEqual(place.position_proxy["position_au"], MOON_POS)
        self.assertEqual(place.distance.basis, "parent_body")
        self.assertTrue(place.distance.approximate)
        self.assertIn("달", place.distance.method)
        self.assertTrue(place.horizons_used_for.startswith("근삿값"))

    def test_horizons_success_is_direct(self):
        probe = [1.5, 0.2, 0.1]
        place = human_made.locate(satcat_row(ORBIT_CENTER="MO"), probe, EARTH_POS, bodies(), EPOCH, EPOCH)
        self.assertEqual(place.position_au, probe)
        self.assertEqual(place.position_basis, "horizons")
        self.assertIsNone(place.position_proxy)
        self.assertFalse(place.distance.approximate)
        self.assertEqual(place.distance.basis, "horizons")
        self.assertEqual(place.location, "심우주 (태양 궤도) (Horizons 직접 계산)")

    def test_direct_position_named_by_nearest_body_not_stale_satcat_center(self):
        """SATCAT이 태양 궤도(SU)로 남아 있어도 실제 위치가 달 곁이면 '달 부근'."""
        near_moon = [MOON_POS[0] + 0.0001, MOON_POS[1], MOON_POS[2]]
        place = human_made.locate(satcat_row(ORBIT_CENTER="SU"), near_moon, EARTH_POS, bodies(), EPOCH, EPOCH)
        self.assertEqual(place.location, "달 부근 (Horizons 직접 계산)")

    def test_planet_preferred_over_far_moon(self):
        """목성 영향권 안이지만 위성 영향권 밖이면 '목성 부근' (주노 사례)."""
        jupiter = Item(id="Q319", group="solar_system", name="목성", wiki_title="목성",
                       position_au=[5.0, 0.0, 0.0], position_basis="horizons")
        ganymede = Item(id="Q3169", group="solar_system", name="가니메데", wiki_title="가니메데",
                        position_au=[5.007, 0.0, 0.0], position_basis="horizons")
        world = {**bodies(), "Jupiter": jupiter, "Ganymede (moon)": ganymede}
        juno = [5.0, 0.01, 0.0]          # 목성에서 약 150만 km, 가니메데에서는 그보다 멀다
        place = human_made.locate(satcat_row(ORBIT_CENTER="JU"), juno, EARTH_POS, world, EPOCH, EPOCH)
        self.assertEqual(place.location, "목성 부근 (Horizons 직접 계산)")

    def test_lagrange_point_is_approximate(self):
        place = human_made.locate(satcat_row(ORBIT_CENTER="EL2"), None, EARTH_POS, bodies(), EPOCH, EPOCH)
        self.assertIsNone(place.position_au)
        self.assertTrue(place.distance.approximate)
        offset = [p - e for p, e in zip(place.position_proxy["position_au"], EARTH_POS)]
        self.assertAlmostEqual(sum(o * o for o in offset) ** 0.5 * AU_KM, human_made.LAGRANGE_KM, delta=1)


# ── [P2] 4. 기준일 이후 발사 항목은 제외한다 ─────────────────────────────────

class LaunchPolicyTest(unittest.TestCase):
    def test_future_launch_with_cospar_excluded(self):
        rec = {"title": ["미래 위성"], "launch": ["2030-01-01T00:00:00Z"], "cospar": ["2030-001A"]}
        launch, _ = human_made.launch_date(rec, None)
        self.assertFalse(human_made.is_launched(launch, EPOCH))

    def test_launched_by_epoch_included(self):
        rec = {"title": ["위성"], "launch": ["2020-05-01T00:00:00Z"]}
        self.assertTrue(human_made.is_launched(human_made.launch_date(rec, None)[0], EPOCH))

    def test_missing_wikidata_date_falls_back_to_satcat(self):
        rec = {"title": ["위성"], "cospar": ["2000-001A"]}
        sc = human_made.match_satcat(rec, {"2000-001A": satcat_row()})
        self.assertEqual(human_made.launch_date(rec, sc), ("2000-01-01", "CelesTrak SATCAT"))

    def test_missing_all_dates_excluded(self):
        rec = {"title": ["위성"], "cospar": ["2000-001A"]}
        self.assertFalse(human_made.is_launched(human_made.launch_date(rec, None)[0], EPOCH))

    def test_satcat_match_requires_payload_and_same_launch(self):
        rec = {"title": ["갈릴레오"], "launch": ["1989-10-18T00:00:00Z"], "cospar": ["1989-084E"]}
        debris = satcat_row(OBJECT_ID="1989-084E", OBJECT_TYPE="DEB", LAUNCH_DATE="1989-10-18")
        self.assertIsNone(human_made.match_satcat(rec, {"1989-084E": debris}))
        other_day = satcat_row(OBJECT_ID="1989-084E", LAUNCH_DATE="1990-01-01")
        self.assertIsNone(human_made.match_satcat(rec, {"1989-084E": other_day}))


# ── [P2] 5. SATCAT 스냅샷 시점과 기준일을 구분한다 ──────────────────────────

class SnapshotTimeTest(unittest.TestCase):
    def test_decay_after_epoch_is_not_asserted(self):
        sc = satcat_row(DECAY_DATE="2026-12-01", OPS_STATUS_CODE="D")
        place = human_made.locate(sc, None, EARTH_POS, bodies(), "2026-10-21", "2027-01-01")
        self.assertFalse(place.status_known)
        self.assertIsNone(place.distance)
        self.assertIn("기준일 상태 미상", place.location)

    def test_decay_before_epoch_is_reentry(self):
        sc = satcat_row(DECAY_DATE="2018-04-02", OPS_STATUS_CODE="D", ORBIT_TYPE="IMP")
        place = human_made.locate(sc, None, EARTH_POS, bodies(), EPOCH, EPOCH)
        self.assertTrue(place.location.startswith("대기권 재진입 (2018-04-02)"))

    def test_cache_records_and_estimates_fetch_time(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(sources, "raw_dir", return_value=Path(tmp)):
            sources.cached("fresh", lambda: {"a": 1}, refresh=True)
            self.assertFalse(sources.SNAPSHOTS["fresh"]["estimated"])
            self.assertTrue((Path(tmp) / "fresh.json.meta.json").exists())

            (Path(tmp) / "legacy.json").write_text("{}", encoding="utf-8")   # 시각 기록 없는 예전 캐시
            sources.cached("legacy", lambda: self.fail("캐시를 써야 한다"))
            self.assertTrue(sources.SNAPSHOTS["legacy"]["estimated"])

    def test_collected_item_records_snapshot_and_real_sources(self):
        """Horizons 실패 + 달 궤도 탐사선을 실제 collect 경로로 통과시킨다."""
        rows = [
            {"item": "http://www.wikidata.org/entity/Q1", "title": "다누리", "launch": "2022-08-04T00:00:00Z",
             "cospar": "2022-097A", "countryLabel": "대한민국"},
            {"item": "http://www.wikidata.org/entity/Q2030", "title": "미래 탐사선",
             "launch": "2030-01-01T00:00:00Z", "cospar": "2030-001A"},
        ]
        satcat = {"2022-097A": satcat_row(OBJECT_ID="2022-097A", LAUNCH_DATE="2022-08-04",
                                          ORBIT_CENTER="MO", OWNER="SKOR")}
        fake_cache = {"human_made_wikidata": rows, "human_made_pages": {}}
        with mock.patch.object(sources, "cached", side_effect=lambda name, fetch, refresh=False: fake_cache[name]), \
                mock.patch.object(sources, "satcat_by_cospar",
                                  return_value=(satcat, {"fetched_at": "2026-10-21T05:00:00+00:00", "estimated": False})), \
                mock.patch.object(sources, "horizons_position", return_value=None):
            items = human_made.collect(EPOCH, bodies())

        self.assertEqual([it.name for it in items], ["다누리"])          # 미래 발사 항목 제외
        item = items[0]
        self.assertIsNone(item.position_au)
        self.assertEqual(item.position_proxy["body"], "달")
        self.assertEqual(item.attrs["SATCAT 스냅샷"], "2026-10-21")
        self.assertNotIn("Horizons 위치 기준일", item.attrs)
        horizons = [s for s in item.sources if s["name"] == "JPL Horizons"]
        self.assertEqual(len(horizons), 1)
        self.assertTrue(horizons[0]["used_for"].startswith("근삿값"))
        item_errors = [e for e in catalog.validate_items([item.to_dict()], min_items=0) if not e.startswith("그룹")]
        self.assertEqual(item_errors, [])


# ── [P2] 6. 리다이렉트 별칭을 모두 보존한다 ──────────────────────────────────

class RedirectTest(unittest.TestCase):
    def test_all_aliases_resolve_to_target(self):
        response = {"query": {
            "normalized": [{"from": "a_lias", "to": "A lias"}],
            "redirects": [
                {"from": "A lias", "to": "Target"},
                {"from": "B", "to": "Target"},
                {"from": "C", "to": "D"},
                {"from": "D", "to": "Target"},
            ],
            "pages": [
                {"title": "Target", "length": 1234, "pageid": 7},
                {"title": "Nope", "missing": True},
            ],
        }}
        fake = mock.Mock()
        fake.get_json.return_value = response
        with mock.patch.object(sources, "http", return_value=fake):
            info = sources.kowiki_page_info(["a_lias", "B", "C", "Target", "Nope"])

        for title in ("a_lias", "B", "C", "Target"):
            self.assertEqual(info[title]["resolved"], "Target", title)
            self.assertEqual(info[title]["length"], 1234)
        self.assertNotIn("Nope", info)


if __name__ == "__main__":
    unittest.main()


# ── 8b 데이터 품질 — 등급 파장대 · 거리 검증 ───────────────────────────────

class MagnitudeBandTest(unittest.TestCase):
    V = "http://www.wikidata.org/entity/Q4892529"
    K = "http://www.wikidata.org/entity/Q6346"

    def test_prefers_v_band_over_brighter_infrared(self):
        from vasthorizon.data.items.messier import visual_magnitude
        # M60 — K 5.7(적외선)을 고르면 맨눈 관측 가능으로 잘못 바뀐다
        self.assertEqual(visual_magnitude({f"8.8|{self.V}", f"5.7|{self.K}"}), 8.8)

    def test_unbanded_value_used_when_no_v_band(self):
        from vasthorizon.data.items.messier import visual_magnitude
        self.assertEqual(visual_magnitude({"6.3|", f"4.0|{self.K}"}), 6.3)

    def test_only_infrared_or_blank_is_unknown(self):
        from vasthorizon.data.items.messier import visual_magnitude
        self.assertIsNone(visual_magnitude({f"5.7|{self.K}"}))
        self.assertIsNone(visual_magnitude({"t123abc|", f"bad|{self.V}"}))      # 값 미상(빈 노드)은 건너뛴다


class ParallaxCheckTest(unittest.TestCase):
    PC_KM = 3.261563777 * 9_460_730_472_580.8

    def test_drops_values_that_disagree_with_parallax(self):
        from vasthorizon.data.items.common import distance_with_parallax
        # 타비트 — 8파섹 값 3개 + 39,533파섹(자릿수 오류) 값 3개, 연주시차 124.6 밀리각초
        values = [8.0 * self.PC_KM, 8.03 * self.PC_KM, 8.05 * self.PC_KM] + [39_533 * self.PC_KM] * 3
        dist = distance_with_parallax(values, 124.6)
        self.assertAlmostEqual(dist.ly, 8.03 * 3.261563777, delta=0.1)
        self.assertIn("어긋난 값 3개 제외", dist.method)

    def test_falls_back_to_parallax_when_nothing_agrees(self):
        from vasthorizon.data.items.common import distance_with_parallax
        dist = distance_with_parallax([1000 * self.PC_KM], 100.0)
        self.assertEqual(dist.basis, "parallax")
        self.assertAlmostEqual(dist.ly, 10 * 3.261563777, delta=0.01)

    def test_small_parallax_is_not_an_anchor(self):
        from vasthorizon.data.items.common import distance_with_parallax
        # 알니타크 — 연주시차 4.43 밀리각초는 오차가 커서 출처 값(약 1,260광년)을 그대로 쓴다
        dist = distance_with_parallax([386 * self.PC_KM], 4.43)
        self.assertEqual(dist.basis, "wikidata")
        self.assertAlmostEqual(dist.ly, 386 * 3.261563777, delta=0.1)

    def test_no_values_uses_parallax(self):
        from vasthorizon.data.items.common import distance_with_parallax
        self.assertEqual(distance_with_parallax([], 2.0).basis, "parallax")
        self.assertIsNone(distance_with_parallax([], None))


class ParallaxRangeTest(unittest.TestCase):
    """8b 리뷰 — 중앙값이 맞아도 범위 · 개수에 이상값이 남지 않아야 한다."""
    PC_KM = ParallaxCheckTest.PC_KM

    def check(self, factors, plx=100.0):
        from vasthorizon.data.items.common import distance_with_parallax
        a = 10 * self.PC_KM                                  # 연주시차 100 밀리각초 = 10파섹
        return distance_with_parallax([f * a for f in factors], plx), a

    def test_outlier_removed_from_range_when_median_agrees(self):
        dist, a = self.check([1.0, 1.01, 1.02, 1000.0])
        self.assertEqual(dist.n_values, 3)
        self.assertAlmostEqual(dist.km_max, 1.02 * a)
        self.assertAlmostEqual(dist.km_min, a)
        self.assertIn("어긋난 값 1개 제외", dist.method)

    def test_wrong_median(self):
        dist, a = self.check([1.0, 1.01, 1000.0, 1000.0, 1000.0])
        self.assertEqual((dist.n_values, dist.km_max), (2, 1.01 * a))

    def test_all_values_agree_keeps_original(self):
        dist, a = self.check([0.9, 1.0, 1.1])
        self.assertEqual((dist.n_values, dist.km_min, dist.km_max), (3, 0.9 * a, 1.1 * a))
        self.assertEqual(dist.method, "출처 3개 값의 중앙값")

    def test_parallax_only(self):
        dist, a = self.check([])
        self.assertEqual((dist.basis, dist.n_values), ("parallax", 1))
        self.assertAlmostEqual(dist.km, a)

    def test_small_parallax_keeps_source_range(self):
        # 먼 별(연주시차 < 5 밀리각초)은 검증 기준이 아니다 — 출처 값 범위를 그대로 둔다
        from vasthorizon.data.items.common import distance_with_parallax
        dist = distance_with_parallax([300 * self.PC_KM, 400 * self.PC_KM], 1.0)
        self.assertEqual((dist.basis, dist.n_values), ("wikidata", 2))

    def test_outlier_not_in_light_letter_year_range(self):
        from dataclasses import asdict
        from vasthorizon.features.light_letter import compute_departure
        dist, _ = self.check([1.0, 1.01, 1.02, 1000.0])
        star = {"name": "검증 별", "distance": {**asdict(dist), "ly": dist.ly}}
        far, near = compute_departure(star, 2026).year_range
        self.assertLess(near - far, 2)                       # 이상값(약 3.3만 광년)이 범위에 들어가지 않는다
        self.assertGreater(far, 1980)


# ── 우리 은하 그룹 — 고정 SPARQL 행으로 (네트워크 없음) ─────────────────────

def _wd(qid: str) -> str:
    return f"http://www.wikidata.org/entity/{qid}"


# Wikidata 실측값 (2026-10-28) 모양의 SPARQL 행 — 값 하나마다 행 하나, OPTIONAL이 비면 키가 없다
MILKY_WAY_ROWS = [
    {"item": _wd("Q321"), "title": "우리 은하", "en": "Milky Way", "typeLabel": "막대나선은하"},
    {"item": _wd("Q321"), "title": "우리 은하", "en": "Milky Way", "typeLabel": "천체"},
    {"item": _wd("Q649112"), "title": "은하중심", "ra": "266.41500889", "dec": "-29.00611111",
     "distRec": f"8|{_wd('Q11929860')}||"},                                      # 8 킬로파섹
    {"item": _wd("Q237284"), "title": "궁수자리 A*", "en": "Sagittarius A*", "typeLabel": "초거대질량 블랙홀",
     "ra": "266.416816625", "dec": "-29.007824972", "conLabel": "궁수자리",
     "distRec": f"26000|{_wd('Q531')}|24600|27400", "massRec": f"4310000|{_wd('Q180892')}"},
    {"item": _wd("Q237284"), "title": "궁수자리 A*", "en": "Sagittarius A*", "typeLabel": "전파원",
     "massRec": f"4020000|{_wd('Q180892')}"},
    {"item": _wd("Q237284"), "title": "궁수자리 A*", "massRec": "1|http://www.wikidata.org/entity/Q11570"},   # 킬로그램 — 질량에서 뺀다
    {"item": _wd("Q237284"), "title": "궁수자리 A*", "massRec": f"4100000|{_wd('Q180892')}"},
]
KPC_8_KM = 8000 * 3.261563777 * LY_KM


def milky_way_items(rows: list[dict] | None = None) -> list[dict]:
    """고정 SPARQL 행으로 모은 우리 은하 · 궁수자리 A* — 보강(enrich.json)까지 적용한 카탈로그 모양."""
    with mock.patch.object(sources, "cached", return_value=MILKY_WAY_ROWS if rows is None else rows):
        return enrich_items([it.to_dict() for it in milky_way.collect()])


class MilkyWayCollectTest(unittest.TestCase):
    def setUp(self):
        self.galaxy, self.sgr = milky_way_items()

    def test_milky_way_uses_galactic_center(self):
        g = self.galaxy
        self.assertEqual((g["id"], g["group"], g["name"], g["wiki_title"], g["name_en"]),
                         ("Q321", "milky_way", "우리 은하", "우리 은하", "Milky Way"))
        self.assertEqual(g["kind"], "막대나선은하")
        self.assertEqual((g["ra_deg"], g["dec_deg"]), (266.41500889, -29.00611111))     # 은하 중심(Q649112) 좌표
        d = g["distance"]
        self.assertEqual(d["reference"], REF_GALACTIC_CENTER)
        self.assertAlmostEqual(d["km"], (26000 * LY_KM + KPC_8_KM) / 2, delta=1e3)      # 26,000광년과 8kpc의 중앙값
        self.assertAlmostEqual(d["km_min"], 26000 * LY_KM, delta=1e3)
        self.assertAlmostEqual(d["km_max"], KPC_8_KM, delta=1e3)
        self.assertEqual(d["n_values"], 2)
        self.assertIn("Q649112", d["method"])
        self.assertEqual({s["url"].rsplit("/", 1)[-1] for s in g["sources"] if s["name"] == "Wikidata"},
                         {"Q321", "Q649112", "Q237284"})

    def test_sgr_a_star_uses_original_value_not_normalized(self):
        s = self.sgr
        self.assertEqual((s["id"], s["group"], s["name"], s["kind"]), ("Q237284", "milky_way", "궁수자리 A*", "초거대질량 블랙홀"))
        d = s["distance"]
        self.assertAlmostEqual(d["km"], 26000 * LY_KM, delta=1e3)            # psn의 2.5e20 m(약 26,425광년)가 아니다
        self.assertAlmostEqual(d["km_min"], 24600 * LY_KM, delta=1e3)
        self.assertAlmostEqual(d["km_max"], 27400 * LY_KM, delta=1e3)
        self.assertEqual(d["n_values"], 1)
        self.assertEqual(d["method"], "Wikidata 값 · 불확도 범위 2.46만~2.74만광년")
        self.assertEqual(s["attrs"]["별자리"], "궁수자리")
        self.assertEqual(s["attrs"]["분류"], "초거대질량 블랙홀, 전파원")
        self.assertEqual(s["attrs"]["질량"], "약 410만 태양질량 (Wikidata 값 3개, 402만~431만)")
        self.assertIs(s["attrs"]["맨눈 관측"], False)

    def test_enrichment_and_seoul_visibility(self):
        self.assertEqual(self.galaxy["attrs"]["블랙홀"], "궁수자리 A*")
        self.assertIs(self.galaxy["attrs"]["맨눈 관측"], True)
        self.assertIs(self.galaxy["attrs"]["서울에서_관측"], True)            # 은하 중심 적위 -29° — 서울에서 떠오른다
        self.assertTrue(any(s.get("used_for", "").startswith("블랙홀") for s in self.galaxy["sources"]))
        self.assertNotIn("서울에서_관측", self.sgr["attrs"])                   # 눈에 보이지 않는 천체는 계산하지 않는다
        self.assertIn("가시광선", self.sgr["attrs"]["관측"])
        self.assertFalse([e for e in catalog.validate_items([self.galaxy, self.sgr], min_items=1) if "Q321" in e or "Q237284" in e])

    def test_unknown_unit_is_dropped(self):
        unknown = {"item": _wd("Q237284"), "title": "궁수자리 A*", "distRec": f"3|{_wd('Q828224')}||"}   # 킬로미터
        with self.assertLogs("vasthorizon.data.items.milky_way", "WARNING") as logs:
            galaxy, sgr = milky_way_items(MILKY_WAY_ROWS + [unknown])
        self.assertEqual(len(logs.records), 1)
        self.assertEqual((galaxy["distance"]["n_values"], sgr["distance"]["n_values"]), (2, 1))
        rows = [r for r in MILKY_WAY_ROWS if "distRec" not in r] + [unknown, {"item": _wd("Q649112"), "ra": "266.4", "dec": "-29.0"}]
        with self.assertLogs("vasthorizon.data.items.milky_way", "WARNING"), self.assertRaises(ValueError):
            milky_way_items(rows)                                        # 알 수 없는 값만 남으면 궁수자리 A* 거리가 0건 — 수집 실패

    def test_missing_sgr_distance_raises(self):
        # 궁수자리 A* 거리 기록이 0건이면 거리 None으로 검증을 통과해 지도 점이 사라진다 — 수집을 실패시켜 기존 카탈로그를 지킨다
        rows = [{k: v for k, v in r.items() if k != "distRec"} if r["item"] == _wd("Q237284") else r for r in MILKY_WAY_ROWS]
        with self.assertRaisesRegex(ValueError, "Q237284"):
            milky_way_items(rows)

    def test_missing_kowiki_title_raises(self):
        rows = [r for r in MILKY_WAY_ROWS if r["item"] != _wd("Q237284")] + [
            {"item": _wd("Q237284"), "ra": "266.4", "dec": "-29.0"}]
        with self.assertRaises(ValueError):
            milky_way_items(rows)

    def test_missing_center_coordinates_raises(self):
        rows = [r for r in MILKY_WAY_ROWS if r["item"] != _wd("Q649112")]
        with self.assertRaises(ValueError):
            milky_way_items(rows)


class CollectOnlyGroupTest(unittest.TestCase):
    """--only GROUP — 그 그룹만 바꿔 끼우고 나머지 · 기준일은 그대로 둔다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "items.json"
        # 실제 카탈로그처럼 그룹 순서대로 모여 있는 다른 그룹 항목
        order = list(catalog.GROUP_KEYS)
        others = sorted((it.to_dict() for it in make_items(150) if it.group != "milky_way"),
                        key=lambda it: order.index(it["group"]))
        self.others = enrich_items(others)
        self.meta = {"collected_at": "2026-10-21", "horizons_epoch": EPOCH, "time_policy": "정책",
                     "counts": {}, "total": len(self.others),
                     "source_snapshots": {"messier_wikidata_v2": {"fetched_at": "2026-10-21T00:00:00+00:00"}},
                     "licenses": catalog.LICENSES}
        # 우리 은하 그룹이 없는 기존 카탈로그 — 지금 검증 규칙으로는 저장할 수 없어 직접 쓴다
        self.path.write_text(json.dumps({"meta": self.meta, "items": self.others}, ensure_ascii=False), encoding="utf-8")
        self.original = self.path.read_bytes()
        self.patch = mock.patch.object(catalog, "items_path", return_value=self.path)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def run_only(self, *args, **patch) -> int:
        with mock.patch.object(collect_items, "collect_group", **patch) as group, \
                mock.patch.object(collect_items, "collect_all") as full, redirect_stdout(io.StringIO()):
            code = collect_items.main(["--only", "milky_way", *args])
        full.assert_not_called()
        self.group_calls = group.call_args_list
        return code

    def milky_way(self) -> list[Item]:
        with mock.patch.object(sources, "cached", return_value=MILKY_WAY_ROWS):
            return milky_way.collect()

    def test_replaces_only_that_group(self):
        self.assertEqual(self.run_only(return_value=self.milky_way()), 0)
        self.assertEqual(self.group_calls[0].args, ("milky_way", EPOCH, False))   # 기존 카탈로그의 위치 기준일
        data = json.loads(self.path.read_text(encoding="utf-8"))
        items, meta = data["items"], data["meta"]
        self.assertEqual([it for it in items if it["group"] != "milky_way"], self.others)    # 다른 그룹은 그대로
        self.assertEqual([it["id"] for it in items if it["group"] == "milky_way"], ["Q321", "Q237284"])
        groups = [it["group"] for it in items]                                    # 그룹 순서: 메시에 뒤, 별자리 앞
        self.assertLess(max(i for i, g in enumerate(groups) if g == "messier"), groups.index("milky_way"))
        self.assertLess(max(i for i, g in enumerate(groups) if g == "milky_way"), groups.index("constellation"))
        self.assertEqual((meta["collected_at"], meta["horizons_epoch"], meta["time_policy"]), ("2026-10-21", EPOCH, "정책"))
        self.assertEqual(meta["total"], len(self.others) + 2)
        self.assertEqual(meta["counts"]["우리 은하"], 2)
        self.assertIn("messier_wikidata_v2", meta["source_snapshots"])          # 기존 스냅샷 기록은 남는다
        self.assertIn("milky_way", meta["partial_collections"])
        self.assertIs(next(it for it in items if it["id"] == "Q321")["attrs"]["맨눈 관측"], True)   # 보강 적용

    def test_duplicate_qid_keeps_existing_item(self):
        galaxy, sgr = self.milky_way()
        sgr.id = self.others[0]["id"]
        self.assertEqual(self.run_only(return_value=[galaxy, sgr]), 0)
        items = json.loads(self.path.read_text(encoding="utf-8"))["items"]
        self.assertEqual(next(it for it in items if it["id"] == sgr.id), self.others[0])

    def test_collect_failure_keeps_file(self):
        self.assertEqual(self.run_only(side_effect=RuntimeError("boom")), 1)
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_validation_failure_keeps_file(self):
        self.assertEqual(self.run_only(return_value=[]), 1)                      # 우리 은하 0건 — 검증 실패
        self.assertEqual(self.path.read_bytes(), self.original)

    def test_other_epoch_rejected(self):
        self.assertEqual(self.run_only("--epoch", "2026-10-28", return_value=self.milky_way()), 1)
        self.assertEqual(self.group_calls, [])
        self.assertEqual(self.path.read_bytes(), self.original)

