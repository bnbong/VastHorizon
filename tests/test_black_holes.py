"""은하 중심 블랙홀 고르기 — 근거 있는 은하만, 가정 · 부정 문장은 근거로 쓰지 않는다."""

import json
import unittest

from vasthorizon.config import PROJECT_ROOT
from vasthorizon.data.black_holes import black_hole_name, central_black_hole_sentence, select

M31 = "안드로메다 은하는 나선 은하이다. 은하의 핵은 중심부에 있는 초대질량 블랙홀 M31*을 중심으로 하고 있다."
M15 = "M15의 중심부는 중심붕괴중으로, 중심부 밀도가 높아지면 중앙에 블랙홀이 생겨날 가능성이 있다."
M33 = "삼각형자리 은하핵에는 초대질량 블랙홀이 나타나지 않으며, 중간 질량 블랙홀이 있을 것으로 추정된다."
M104 = ("전문적 천문학자들은 솜브레로 은하의 큰 팽대부, 중심의 초대질량블랙홀, 짙은 먼지 띠에 관심을 가지고 연구하고 있다. "
        "하지만 핵에서 초대질량블랙홀이 발견되었기 때문에, 이 활동은하핵이 에너지원으로 생각된다.")


class CentralBlackHoleTest(unittest.TestCase):
    def test_fact_sentence(self):
        self.assertIn("M31*", central_black_hole_sentence(M31))

    def test_hedged_or_negative_sentences_are_not_evidence(self):
        self.assertIsNone(central_black_hole_sentence(M15))      # 생겨날 가능성
        self.assertIsNone(central_black_hole_sentence(M33))      # 나타나지 않으며
        self.assertIsNone(central_black_hole_sentence("항성 질량 블랙홀 M33 X-7이 발견되었다."))   # 중심 · 초대질량이 아님

    def test_prefers_sentence_stating_existence(self):
        self.assertTrue(central_black_hole_sentence(M104).startswith("하지만 핵에서"))

    def test_name(self):
        self.assertEqual(black_hole_name(M31, None), "M31*")
        self.assertEqual(black_hole_name("문장", "M87*"), "M87*")
        self.assertIsNone(black_hole_name("이름 없는 문장", None))

    def test_select_needs_evidence(self):
        gals = [{"id": "Q1", "name": "A", "wiki_title": "A", "attrs": {"메시에 번호": "M31"}},
                {"id": "Q2", "name": "B", "wiki_title": "B", "attrs": {"메시에 번호": "M33"}},
                {"id": "Q3", "name": "C", "wiki_title": None, "attrs": {"메시에 번호": "M87"}}]
        docs = {"A": {"title": "A", "url": "u", "text": M31}, "B": {"title": "B", "url": "u", "text": M33}}
        out = select(gals, docs, {"Q3": {"qid": "Q9", "label": "M87*"}})
        self.assertEqual([o["code"] for o in out], ["M31", "M87"])
        self.assertEqual(out[1]["wikidata"]["qid"], "Q9")
        self.assertIsNone(out[1]["quote"])

    def test_built_file_has_sources(self):
        data = json.loads((PROJECT_ROOT / "web" / "data" / "blackholes.json").read_text(encoding="utf-8"))
        self.assertIn("상상도", data["note"])
        self.assertEqual({g["code"] for g in data["galaxies"]}, {"M31", "M84", "M87", "M104"})
        for g in data["galaxies"]:
            self.assertTrue(g["doc"] or g["wikidata"], g)
            if g["quote"]:
                self.assertIn("블랙홀", g["quote"])


if __name__ == "__main__":
    unittest.main()
