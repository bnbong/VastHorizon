"""3D 화면용 API 테스트 — 우주 지도 배치 · 별자리 목록 · 정적 파일 형식 (9번 작업).

외부 호출 · 토큰 사용 없음.

    python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from tests.test_api import FakeAsk, healthy
from tests.test_features import dist, item
from tests.test_sky_constellation import FIGURE
from vasthorizon.api.app import create_app
from vasthorizon.api.services import Services
from vasthorizon.data.items.common import REF_SURFACE_ALTITUDE
from vasthorizon.features.space_map import illustrative_direction, map_points


def solar(qid, name, pos, ly=None):
    return {**item(qid, name, "solar_system", "행성", ly), "position_au": pos}


EARTH = solar("Q2", "지구", [1.0, 0.0, 0.0])
ITEMS = [
    EARTH,
    solar("Q111", "화성", [2.0, 0.0, 0.0], ly=1e-5),
    {**item("Q3409", "시리우스", "star", "항성", 8.6), "ra_deg": 101.29, "dec_deg": -16.72},
    {**item("Q25271", "국제우주정거장", "human_made", "우주정거장"),
     "distance": dist(4.4e-11, reference=REF_SURFACE_ALTITUDE),
     "position_proxy": {"body": "지구", "position_au": [1.0, 0.0, 0.0], "method": "모천체 위치"}},
    {**item("Q9", "달 궤도선", "human_made", "탐사선", 4e-8),
     "position_proxy": {"body": "달", "position_au": [1.0, 0.002, 0.0], "method": "모천체 위치"}},
    {**item("Q5", "재진입한 위성", "human_made", "인공위성"), "attrs": {"현재 위치": "대기권 재진입 (2013-07-08)"}},
    item("Q8860", "오리온자리", "constellation", "별자리"),
]


class MapPointsTest(unittest.TestCase):
    def setUp(self):
        data = map_points(ITEMS)
        self.points = {p["name"]: p for p in data["points"]}
        self.unplaced = {u["name"]: u for u in data["unplaced"]}
        self.rings = data["rings"]

    def test_catalog_code_links_sky_data(self):
        # 하늘 데이터(web/data)의 별 · 성운과 잇는 번호 — 메시에 번호 · 히파르코스 번호 (12번)
        from vasthorizon.features.space_map import _point
        self.assertEqual(_point({"id": "Q1", "name": "M", "group": "messier", "attrs": {"메시에 번호": "M31"}}, [1, 0, 0], 1.0, "sky")["code"], "M31")
        self.assertEqual(_point({"id": "Q2", "name": "S", "group": "star", "attrs": {"히파르코스 번호": "HIP 32349"}}, [1, 0, 0], 1.0, "sky")["code"], "HIP 32349")
        self.assertIsNone(_point({"id": "Q3", "name": "J", "group": "human_made", "attrs": {}}, None, 1.0, "computed")["code"])
        self.assertEqual(_point({"id": "Q4", "name": "B", "group": "star", "attrs": {"분광형": "M1-2Ia"}}, [1, 0, 0], 1.0, "sky")["spectral"], "M1-2Ia")

    def test_placements(self):
        self.assertEqual({n: p["placement"] for n, p in self.points.items()}, {
            "지구": "origin", "화성": "computed", "시리우스": "sky", "국제우주정거장": "illustrative", "달 궤도선": "proxy"})
        self.assertNotIn("오리온자리", self.points)                      # 별자리는 천구 보기에서

    def test_directions_are_unit_vectors_from_earth(self):
        self.assertEqual(self.points["화성"]["dir"], [1.0, 0.0, 0.0])    # 화성 − 지구 = +x
        self.assertEqual(self.points["달 궤도선"]["dir"], [0.0, 1.0, 0.0])
        for name in ("시리우스", "국제우주정거장"):
            self.assertAlmostEqual(math.hypot(*self.points[name]["dir"]), 1.0, places=5)

    def test_earth_orbit_satellite_never_gets_zero_direction(self):
        # 모천체가 지구인 근삿값은 지구 − 지구 = 0 — 예시 방향으로 둔다 (9번 작업 중 발견)
        self.assertEqual(self.points["국제우주정거장"]["dir"], [round(c, 6) for c in illustrative_direction("Q25271")])

    def test_solar_points_carry_heliocentric_position(self):
        # 하늘 보기가 그날의 지구 위치를 빼 방향을 다시 계산한다 (왜행성 · 소행성 · 혜성 표식, 위성 위상)
        self.assertEqual(self.points["화성"]["position_au"], [2.0, 0.0, 0.0])
        self.assertNotIn("position_au", self.points["시리우스"])

    def test_unplaced_keeps_reason(self):
        self.assertIn("재진입", self.unplaced["재진입한 위성"]["reason"])

    def test_rings_increase(self):
        kms = [r["km"] for r in self.rings]
        self.assertEqual(kms, sorted(kms))
        self.assertTrue(self.rings[-1].get("edge"))                              # 마지막은 관측 가능한 우주의 끝
        self.assertAlmostEqual(self.rings[-1]["km"] / (9_460_730_472_580.8 * 1e9), 46.5)


class WebApiTest(unittest.TestCase):
    def client(self, web_dir=None):
        services = Services(items=ITEMS, ask=FakeAsk(), health=healthy, figures={"Q8860": FIGURE},
                            sky_stars=[[10.0, 20.0, 3.5, 0.6]])
        return TestClient(create_app(services, web_dir=web_dir), raise_server_exceptions=False)

    def test_map_endpoint_is_cached(self):
        c = self.client()
        with mock.patch("vasthorizon.api.app.map_points", wraps=map_points) as spy:
            first = c.get("/api/map").json()
            self.assertEqual(c.get("/api/map").json(), first)
        self.assertEqual((len(first["points"]), spy.call_count), (5, 1))     # 항목이 바뀌지 않으므로 한 번만 계산
        self.assertEqual(first["ref_year"], 2026)                               # 빛이 출발한 해 계산 기준

    def test_constellations_endpoint(self):
        body = self.client().get("/api/constellations").json()
        con = body["constellations"][0]
        self.assertEqual((con["item_id"], con["lines"], len(con["stars"])), ("Q8860", [[1, 2], [2, 3, 4]], 4))
        self.assertEqual(set(con["stars"][0]), {"hip", "name", "item_id", "ra_deg", "dec_deg", "mag", "distance_ly"})
        self.assertEqual(body["sky_stars"], [[10.0, 20.0, 3.5, 0.6]])

    def test_static_module_scripts_are_javascript(self):
        # Windows 레지스트리가 .js를 text/plain으로 알려 주면 브라우저가 모듈 스크립트를 거부한다
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "index.html").write_text("<!doctype html>", encoding="utf-8")
            Path(tmp, "app.js").write_text("export {};", encoding="utf-8")
            Path(tmp, "style.css").write_text("body{}", encoding="utf-8")
            Path(tmp, "stars.bin").write_bytes(b"VHS1" + bytes(4))
            c = self.client(Path(tmp))
            self.assertEqual(c.get("/stars.bin").headers["content-type"], "application/octet-stream")   # 하늘 데이터 (12번)
            self.assertTrue(c.get("/app.js").headers["content-type"].startswith("text/javascript"))
            self.assertTrue(c.get("/style.css").headers["content-type"].startswith("text/css"))
            self.assertEqual(c.get("/").status_code, 200)
            self.assertEqual(c.get("/api/map").status_code, 200)          # API가 정적 파일보다 먼저


if __name__ == "__main__":
    unittest.main()
