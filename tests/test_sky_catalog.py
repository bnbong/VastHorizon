"""하늘 데이터 (12번) — 별 이진 형식 · 성운 행 · 은하수 안팎 판정 · 만들어 둔 web/data 파일. 외부 호출 없음.

    python -m unittest discover -s tests -t .
"""

from __future__ import annotations

import json
import unittest

import numpy as np

from vasthorizon.config import PROJECT_ROOT
from vasthorizon.data.sky_catalog import (decode_stars, dso_rows, encode_stars, inside_mask, load_star_index,
                                          milkyway_grid, star_rows)

WEB_DATA = PROJECT_ROOT / "web" / "data"


def star(hip, lon, lat, mag, bv="0.5"):
    return {"id": hip, "properties": {"mag": mag, "bv": bv}, "geometry": {"coordinates": [lon, lat]}}


class StarFormatTest(unittest.TestCase):
    def test_rows_sorted_and_roundtrip(self):
        rows = star_rows([star(1, -10.0, 5.0, 9.1, ""), star(32349, 101.287, -16.716, -1.44, "0.009")])
        self.assertEqual([r[0] for r in rows], [32349, 1])                 # 밝은 순
        self.assertAlmostEqual(rows[1][1], 350.0)                          # 경도 −10 → 적경 350
        self.assertEqual(rows[1][4], 0.6)                                  # 색지수 없음 → 태양 정도
        back = decode_stars(encode_stars(rows))
        for (h, ra, dec, mag, bv), (h2, ra2, dec2, mag2, bv2) in zip(rows, back):
            self.assertEqual(h, h2)
            self.assertAlmostEqual(ra, ra2, delta=0.006)
            self.assertAlmostEqual(dec, dec2, delta=0.003)
            self.assertAlmostEqual(mag, mag2, places=2)
            self.assertAlmostEqual(bv, bv2, places=3)

    def test_bad_magic(self):
        with self.assertRaises(ValueError):
            decode_stars(b"XXXX\x00\x00\x00\x00")


class DsoRowsTest(unittest.TestCase):
    def test_messier_linked_through_ngc_and_dark_nebula_has_no_mag(self):
        features = [
            {"id": "NGC 224", "properties": {"type": "s", "mag": "3.4", "dim": "178x63"}, "geometry": {"coordinates": [10.68, 41.27]}},
            {"id": "M 45", "properties": {"type": "sfr", "mag": "1.2", "dim": "110x110"}, "geometry": {"coordinates": [56.75, 24.12]}},
            {"id": "LDN 27", "properties": {"type": "dn", "mag": "1", "dim": "63"}, "geometry": {"coordinates": [-113.05, -15.12]}},
            {"id": "NGC 188", "properties": {"type": "oc", "mag": "", "dim": "15"}, "geometry": {"coordinates": [12.1, 85.2]}},
        ]
        messier = [{"properties": {"name": "M31", "desig": "NGC 224"}}, {"properties": {"name": "M45", "desig": ""}}]
        rows = {r[0]: r for r in dso_rows(features, messier)}
        self.assertEqual(rows["NGC 224"][7], "M31")                      # NGC 이름 → 메시에 번호
        self.assertEqual(rows["M45"][7], "M45")
        self.assertIsNone(rows["LDN 27"][4])                             # 불투명도 등급은 밝기 등급이 아니다
        self.assertAlmostEqual(rows["LDN 27"][2], 246.95)
        self.assertEqual((rows["NGC 188"][4], rows["NGC 188"][5], rows["NGC 188"][6]), (None, 15.0, 15.0))
        self.assertEqual([r[0] for r in dso_rows(features, messier)][:2], ["M45", "NGC 224"])   # 밝은 순, 등급 없는 것은 뒤


class MilkyWayTest(unittest.TestCase):
    def test_square_and_band_around_sky(self):
        square = [[[10, -10], [30, -10], [30, 10], [10, 10], [10, -10]]]
        mask = inside_mask(square, 36, 18)                                # 10도 격자
        self.assertTrue(mask[8, 2])                                       # 적경 25 · 적위 5
        self.assertFalse(mask[8, 5])
        # 하늘을 한 바퀴 감는 띠 (적위 −10 ~ 10) — 경도 ±180을 넘는 고리 둘
        north = [[lon, 10] for lon in range(-180, 181, 30)]
        south = [[lon, -10] for lon in range(180, -181, -30)]
        band = inside_mask([north, south], 36, 18)
        self.assertTrue(band[8].all() and band[9].all())
        self.assertFalse(band[3].any() or band[14].any())

    def test_levels_add_brightness(self):
        ring = [[[0, -5], [40, -5], [40, 5], [0, 5], [0, -5]]]
        features = [{"id": f"ol{i}", "geometry": {"coordinates": [ring]}} for i in (1, 2)]
        grid = milkyway_grid(features, 72, 36)
        self.assertEqual(grid.dtype, np.uint8)
        self.assertGreater(grid[17, 4], grid[17, 30])


class BuiltFilesTest(unittest.TestCase):
    """scripts.build_sky_data 로 만든 web/data — 화면이 그대로 쓰는 파일."""

    def test_star_files_and_index(self):
        index = load_star_index(WEB_DATA)
        self.assertEqual(len(index), 118216)
        ra, dec, mag, bv = index[32349]                                   # 시리우스
        self.assertAlmostEqual(mag, -1.44, places=2)
        self.assertAlmostEqual(ra, 101.29, delta=0.02)

    def test_dsos_and_meta(self):
        data = json.loads((WEB_DATA / "dsos.json").read_text(encoding="utf-8"))
        self.assertEqual(data["fields"][7], "messier")
        self.assertEqual(len(data["rows"]), 15809)
        self.assertGreaterEqual(len({r[7] for r in data["rows"] if r[7]}), 100)
        self.assertFalse(any(r[1] == "dn" and r[4] is not None for r in data["rows"]))
        meta = json.loads((WEB_DATA / "sky_meta.json").read_text(encoding="utf-8"))
        self.assertIn("BSD-3-Clause", meta["license"])


if __name__ == "__main__":
    unittest.main()
