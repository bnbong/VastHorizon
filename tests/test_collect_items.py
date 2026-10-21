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
from vasthorizon.data.items import human_made
from vasthorizon.data.items.common import (
    AU_KM, REF_GEOCENTER, REF_SURFACE_ALTITUDE, Distance, Item,
)

EPOCH = "2026-10-21"
EARTH_POS = [0.9, 0.4, 0.17]
MOON_POS = [0.9025, 0.4, 0.17]


def make_items(n: int) -> list[Item]:
    """5개 그룹에 고르게 나눈 유효한 항목 n개."""
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
