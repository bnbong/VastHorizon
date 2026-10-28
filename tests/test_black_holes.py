"""은하 중심 블랙홀 고르기 — 근거 있는 은하만, 가정 · 부정 문장은 근거로 쓰지 않는다."""

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest import mock

from scripts import build_blackholes
from tests.fakes import MILKY_WAY_IN_CATALOG, SKIP_UNTIL_MILKY_WAY
from vasthorizon.config import PROJECT_ROOT
from vasthorizon.data.black_holes import (
    SPARQL, black_hole_name, central_black_hole_sentence, fixed_quotes, missing_documents, select,
)

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
        self.assertTrue({"Q2469", "Q92258118", "Q14041", "Q91461627"} <= {g["id"] for g in data["galaxies"]})   # M31 · M84 · M87 · M104
        self.assertEqual({g["code"] for g in data["galaxies"] if g["code"]}, {"M31", "M84", "M87", "M104"})
        for g in data["galaxies"]:
            self.assertTrue(g["doc"] or g["wikidata"], g)
            if g["quote"]:
                self.assertIn("블랙홀", g["quote"])

    @unittest.skipUnless(MILKY_WAY_IN_CATALOG, SKIP_UNTIL_MILKY_WAY)
    def test_built_file_has_milky_way(self):
        data = json.loads((PROJECT_ROOT / "web" / "data" / "blackholes.json").read_text(encoding="utf-8"))
        by_id = {g["id"]: g for g in data["galaxies"]}
        self.assertEqual(set(by_id), {"Q2469", "Q92258118", "Q14041", "Q91461627", "Q321", "Q237284"})
        galaxy, sgr = by_id["Q321"], by_id["Q237284"]
        self.assertEqual((galaxy["code"], galaxy["center_id"], galaxy["black_hole"]), (None, "Q237284", "궁수자리 A*"))
        self.assertNotIn("self", galaxy)
        self.assertEqual((sgr["code"], sgr["self"]), (None, True))
        self.assertNotIn("center_id", sgr)
        for g in (galaxy, sgr):
            self.assertTrue(g["doc"]["permalink"].endswith("oldid=42571733"))
            self.assertEqual(g["wikidata"]["qid"], "Q237284")


# ── 우리 은하 · 궁수자리 A* — 2단계 연결 · 고정 인용문 · 문서 누락 ───────────────

SGR_TEXT = ("궁수자리 A*는 전파원이다. 천문학자들은 이러한 궁수자리 A*의 관측이, 태양계로부터 26,000 광년 떨어져 있는 "
            "우리 은하의 중심에 초대질량 블랙홀이 있다는 것에 대한 좋은 경험적인 증거를 제공하고 있다고 확신하고 있다.")
SGR_DOC = {"title": "궁수자리 A*", "url": "https://ko.wikipedia.org/wiki/x", "permalink": "https://ko.wikipedia.org/w/index.php?oldid=42571733",
           "license": "CC BY-SA 4.0 — 한국어 위키백과 기여자", "text": SGR_TEXT}
QUOTE = SGR_TEXT.split(". ", 1)[1]
ENRICH = {"Q321": {"name": "우리 은하", "quote": QUOTE,
                   "quote_doc": {"title": "궁수자리 A*", "url": "https://ko.wikipedia.org/wiki/x",
                                 "permalink": "https://ko.wikipedia.org/w/index.php?oldid=42571733"}},
          "Q2469": {"name": "안드로메다 은하", "quote": "문서와 무관하게 적어 둔 문장"}}         # quote_doc 없음 — 고정하지 않는다
GALAXY = {"id": "Q321", "name": "우리 은하", "wiki_title": "우리 은하", "group": "milky_way", "kind": "막대나선은하", "attrs": {}}
SGR = {"id": "Q237284", "name": "궁수자리 A*", "wiki_title": "궁수자리 A*", "group": "milky_way", "kind": "초거대질량 블랙홀",
       "attrs": {}}


class MilkyWayBlackHoleTest(unittest.TestCase):
    def test_sparql_follows_two_steps(self):
        self.assertIn("?g wdt:P527/wdt:P527 ?bh", SPARQL)
        self.assertIn("?bh wdt:P361/wdt:P361 ?g", SPARQL)
        self.assertIn("{ ?g wdt:P527 ?bh }", SPARQL.format(ids="wd:Q321"))

    def test_fixed_quote_checked_against_document(self):
        fixed, errors = fixed_quotes(ENRICH, {"궁수자리 A*": SGR_DOC})
        self.assertEqual((list(fixed), errors), (["Q321"], []))
        self.assertEqual(fixed["Q321"]["quote"], QUOTE)
        self.assertEqual(fixed["Q321"]["doc"]["license"], SGR_DOC["license"])
        changed = {**SGR_DOC, "text": "궁수자리 A*는 전파원이다."}
        fixed, errors = fixed_quotes(ENRICH, {"궁수자리 A*": changed})
        self.assertEqual(fixed, {})
        self.assertIn("고정 인용문", errors[0])

    def test_fixed_quote_without_cached_document_keeps_quote(self):
        fixed, errors = fixed_quotes(ENRICH, {}, default_license="CC BY-SA 4.0")
        self.assertEqual((errors, fixed["Q321"]["doc"]["license"]), ([], "CC BY-SA 4.0"))

    def test_select_center_and_self(self):
        fixed, _ = fixed_quotes(ENRICH, {"궁수자리 A*": SGR_DOC})
        out = select([GALAXY, SGR], {"궁수자리 A*": SGR_DOC}, {"Q321": {"qid": "Q237284", "label": "궁수자리 A*"}},
                     fixed=fixed, selves={"Q237284"}, catalog_ids={"Q321", "Q237284"})
        galaxy, sgr = out
        self.assertEqual((galaxy["code"], galaxy["center_id"], galaxy["black_hole"], galaxy["quote"]),
                         (None, "Q237284", "궁수자리 A*", QUOTE))
        self.assertEqual(galaxy["doc"]["permalink"], SGR_DOC["permalink"])
        self.assertNotIn("self", galaxy)
        self.assertEqual((sgr["self"], sgr["code"], sgr["wikidata"]["qid"], sgr["black_hole"]), (True, None, "Q237284", "궁수자리 A*"))
        self.assertNotIn("center_id", sgr)

    def test_missing_documents(self):
        self.assertEqual(missing_documents([GALAXY, SGR], {"궁수자리 A*": SGR_DOC}), ["우리 은하 (우리 은하)"])

    def build(self, items, docs, enrich=ENRICH, args=()):
        with mock.patch.object(build_blackholes, "load_docs", return_value=docs), \
                mock.patch.object(build_blackholes, "enrichment", return_value=enrich), \
                mock.patch.object(build_blackholes, "http") as http, \
                mock.patch("pathlib.Path.read_text", return_value=json.dumps({"items": items})), \
                mock.patch("pathlib.Path.write_text") as write, redirect_stdout(io.StringIO()) as out:
            code = build_blackholes.main(list(args))
        return code, http, write, out.getvalue()

    def test_build_fails_when_documents_missing(self):
        code, http, write, out = self.build([GALAXY, SGR], {"궁수자리 A*": SGR_DOC})
        self.assertEqual(code, 1)
        self.assertIn("우리 은하 (우리 은하)", out)
        http.assert_not_called()
        write.assert_not_called()

    def test_build_fails_when_fixed_quote_not_in_document(self):
        docs = {"우리 은하": {**SGR_DOC, "title": "우리 은하"}, "궁수자리 A*": {**SGR_DOC, "text": "다른 본문"}}
        code, http, write, out = self.build([GALAXY, SGR], docs)
        self.assertEqual(code, 1)
        self.assertIn("고정 인용문", out)
        write.assert_not_called()

    def test_build_targets(self):
        m87 = {"id": "Q14041", "name": "처녀자리 A 은하", "wiki_title": "처녀자리 A 은하", "group": "messier", "kind": "BC 은하"}
        m45 = {"id": "Q13423", "name": "플레이아데스 성단", "wiki_title": "x", "group": "messier", "kind": "산개 성단"}
        targets, selves = build_blackholes.targets_of([m45, m87, GALAXY, SGR])
        self.assertEqual(([t["id"] for t in targets], selves), (["Q14041", "Q321", "Q237284"], {"Q237284"}))


if __name__ == "__main__":
    unittest.main()
