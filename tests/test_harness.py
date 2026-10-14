import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from xml.sax.saxutils import escape

import kinetics_audit.reference_store as reference_store
from kinetics_audit.databases import enzyme_record, solution_links, solution_record
from kinetics_audit.guard import GuardError, check_source
from kinetics_audit.numbers import measurements, number_tokens
from kinetics_audit.reference_store import offline_page, offline_search
from kinetics_audit.report_file import (
    _kinetics_sentences_from_text,
    _table_to_sentences,
    extract_report,
    locate_report,
)
from kinetics_audit.sandbox import execute
from kinetics_audit.search import fetch_page, search_web, useful_result
from kinetics_audit.tools import Job, dispatch

_FIXTURE_CACHE = Path(__file__).resolve().parent / "fixtures" / "reference_cache"
reference_store._ROOT = _FIXTURE_CACHE
reference_store._INDEX = None


def _report(job, text, experiment="皂化反应"):
    return dispatch(job, "record_report", {"experiment": experiment, "text": text})


def _open_page(job, url, title, text, claim_id, query):
    hit = {"title": title, "url": url, "excerpt": text[:80]}
    with patch("kinetics_audit.tools.search_web", return_value=[hit]), patch("kinetics_audit.tools.fetch_page", return_value=text):
        found = dispatch(job, "search_references", {"query": query, "claim_id": claim_id})
        opened = dispatch(job, "read_reference", {"url": url})
    return found, opened


def _kinetic(quote):
        return {
        "id": "v1",
        "kind": "value",
        "quote": quote,
        "quantity": "活化能",
        "dosage": "0.10 mol/L",
        "temperature": "25摄氏度",
        "method": "电导法",
        }


class HarnessTest(unittest.TestCase):
    def test_method_error_requires_the_same_slot(self):
        job = Job.closed()
        report = "本实验直接用摄氏温度拟合速率常数。"
        _report(job, report)
        extracted = dispatch(
            job,
            "extract_claims",
            {"claims": [{"id": "m1", "kind": "method", "quote": report, "slot": "摄氏温度"}]},
        )
        self.assertTrue(extracted["ok"])
        page = "实验使用玻璃烧杯装样品。拟合必须使用热力学温度，不能把摄氏温度直接代入。"
        found, opened = _open_page(job, "https://example.test/arrhenius", "阿伦尼乌斯公式", page, "m1", "Arrhenius 温度")
        self.assertTrue(found["ok"])
        self.assertGreaterEqual(opened["sentence_count"], 2)
        selected = dispatch(job, "select_evidence", {"claim_id": "m1", "url": "https://example.test/arrhenius"})
        self.assertTrue(selected["ok"])
        self.assertIn("热力学温度", selected["sentences"][0]["text"])
        blocked = dispatch(
            job,
            "judge_claim",
            {"claim_id": "m1", "verdict": "contradicts", "url": "https://example.test/arrhenius", "sentence_id": "s9"},
        )
        self.assertEqual(blocked["error"], "evidence_required")
        glass = next(item for item in selected["sentences"] if "玻璃" in item["text"])
        weak = dispatch(
            job,
            "judge_claim",
            {
                "claim_id": "m1",
                "verdict": "contradicts",
                "url": "https://example.test/arrhenius",
                "sentence_id": glass["id"],
                "literature_span": "热力学温度",
            },
        )
        self.assertEqual(weak["judgment"]["status"], "not_enough")
        relevant = next(item for item in selected["sentences"] if "热力学温度" in item["text"])
        judged = dispatch(
            job,
            "judge_claim",
            {
                "claim_id": "m1",
                "verdict": "contradicts",
                "url": "https://example.test/arrhenius",
                "sentence_id": relevant["id"],
                "literature_span": "热力学温度",
                "explanation": "报告把摄氏温度直接代入 Arrhenius 拟合。",
                "improvement": "拟合前把摄氏温度换成热力学温度。",
            },
        )
        self.assertEqual(judged["judgment"]["status"], "contradicts")
        self.assertIn(report, judged["judgment"]["statement"])
        self.assertIn("摄氏温度直接代入", judged["judgment"]["statement"])
        review = dispatch(
            job,
            "finish_review",
            {"summary": "主要问题是温度单位用法；建议改用热力学温度再拟合。"},
        )
        self.assertEqual(review["review"]["confirmed_errors"][0]["claim_id"], "m1")
        self.assertEqual(review["review"]["confirmed_errors"][0]["improvement"], "拟合前把摄氏温度换成热力学温度。")
        self.assertIn("热力学温度", review["review"]["summary"])
        self.assertFalse(review["review"]["insufficient"])

    def test_method_model_can_keep_a_program_hit_as_insufficient(self):
        job = Job.closed()
        report = "本实验直接用摄氏温度拟合速率常数。"
        _report(job, report)
        dispatch(job, "extract_claims", {"claims": [{"id": "m1", "kind": "method", "quote": report, "slot": "摄氏温度"}]})
        page = "拟合必须使用热力学温度，不能把摄氏温度直接代入。"
        _open_page(job, "https://example.test/arrhenius", "阿伦尼乌斯公式", page, "m1", "Arrhenius 温度")
        selected = dispatch(
            job,
            "select_evidence",
            {"claim_id": "m1", "url": "https://example.test/arrhenius", "focus": "热力学温度 拟合"},
        )
        self.assertEqual(selected["focus"], "热力学温度 拟合")
        relevant = next(item for item in selected["sentences"] if "热力学温度" in item["text"])
        cautious = dispatch(
            job,
            "judge_claim",
            {
                "claim_id": "m1",
                "verdict": "not_enough",
            "url": "https://example.test/arrhenius",
                "sentence_id": relevant["id"],
                "literature_span": "热力学温度",
                "explanation": "文献句讨论的是通用拟合要求，还需要更多上下文。",
            },
        )
        self.assertEqual(cautious["judgment"]["status"], "not_enough")
        self.assertEqual(cautious["judgment"]["reason"], "model_caution")
        self.assertEqual(cautious["judgment"]["program_status"], "contradicts")
        review = dispatch(job, "finish_review", {"summary": "温度做法证据不足，暂不判错。"})
        self.assertFalse(review["review"]["confirmed_errors"])
        self.assertEqual(review["review"]["insufficient"][0]["status"], "not_enough")

    def test_unrelated_method_wording_is_not_a_report_error(self):
        job = Job.closed()
        report = "做法：在 5、10、15、20 min 用电导法测定电导并回归速率常数。"
        _report(job, report)
        dispatch(job, "extract_claims", {"claims": [{"id": "m1", "kind": "method", "quote": report, "slot": "电导法"}]})
        page = "NDRL/NIST 溶液动力学库记录。反应 ·OH + CH3CO2C2H5。Experimental method: Pulse radiolysis。Analytical technique: Vis-UV absorption。"
        _open_page(job, "https://example.test/radical", "自由基", page, "m1", "ethyl acetate")
        selected = dispatch(job, "select_evidence", {"claim_id": "m1", "url": "https://example.test/radical"})
        judged = dispatch(
            job,
            "judge_claim",
            {
                "claim_id": "m1",
                "verdict": "contradicts",
                "url": "https://example.test/radical",
                "sentence_id": selected["sentences"][0]["id"],
                "literature_span": "Pulse radiolysis",
            },
        )
        self.assertEqual(judged["judgment"]["status"], "not_enough")
        review = dispatch(job, "finish_review", {})
        self.assertFalse(review["review"]["confirmed_errors"])
        self.assertEqual(review["review"]["insufficient"][0]["status"], "not_enough")

    def test_conflicting_method_sources_do_not_convict_the_report(self):
        job = Job.closed()
        report = "本实验直接用摄氏温度拟合速率常数。"
        _report(job, report)
        dispatch(job, "extract_claims", {"claims": [{"id": "m1", "kind": "method", "quote": report, "slot": "摄氏温度"}]})
        page = "拟合必须使用热力学温度，不能把摄氏温度直接代入。记录和拟合都可以直接使用摄氏温度。"
        _open_page(job, "https://example.test/mixed", "温度", page, "m1", "摄氏温度 拟合")
        selected = dispatch(job, "select_evidence", {"claim_id": "m1", "url": "https://example.test/mixed"})
        for item in selected["sentences"]:
            span = "热力学温度" if "热力学温度" in item["text"] else "摄氏温度"
            dispatch(
                job,
                "judge_claim",
                {
                    "claim_id": "m1",
                    "verdict": "contradicts",
                    "url": "https://example.test/mixed",
                    "sentence_id": item["id"],
                    "literature_span": span,
                },
            )
        review = dispatch(job, "finish_review", {})
        self.assertFalse(review["review"]["confirmed_errors"])
        self.assertEqual(review["review"]["insufficient"][0]["status"], "literature_inconsistent")

    def test_values_use_program_pairing_and_conditions(self):
        report = "在 0.10 mol/L、25摄氏度、电导法下测得活化能为 30 kJ/mol。"
        evidence = "0.10 mol/L、25摄氏度、电导法下皂化反应活化能约为 48.5 kJ/mol。"
        job = Job.closed()
        _report(job, report)
        self.assertTrue(dispatch(job, "extract_claims", {"claims": [_kinetic(report)]})["ok"])
        self.assertEqual(number_tokens("测得活化能为 300 kJ/mol。"), ["300"])
        _open_page(job, "https://example.test/ea", "乙酸乙酯皂化", evidence, "v1", "皂化 活化能")
        selected = dispatch(job, "select_evidence", {"claim_id": "v1", "url": "https://example.test/ea"})
        judged = dispatch(
            job,
            "judge_claim",
            {"claim_id": "v1", "verdict": "supports", "url": "https://example.test/ea", "sentence_id": selected["sentences"][0]["id"]},
        )
        self.assertEqual(judged["judgment"]["status"], "contradicts")
        self.assertEqual(judged["judgment"]["reported"], "30")
        self.assertEqual(judged["judgment"]["reference"], "48.5")
        close = Job.closed()
        close_report = "在 0.10 mol/L、25摄氏度、电导法下测得活化能为 40 kJ/mol。"
        _report(close, close_report)
        dispatch(close, "extract_claims", {"claims": [_kinetic(close_report)]})
        _open_page(close, "https://example.test/ea", "乙酸乙酯皂化", evidence, "v1", "皂化 活化能")
        picked = dispatch(close, "select_evidence", {"claim_id": "v1", "url": "https://example.test/ea"})
        widened = dispatch(
            close,
            "judge_claim",
            {"claim_id": "v1", "verdict": "contradicts", "url": "https://example.test/ea", "sentence_id": picked["sentences"][0]["id"]},
        )
        self.assertEqual(widened["judgment"]["status"], "supports")
        bare = Job.closed()
        _report(bare, report)
        dispatch(bare, "extract_claims", {"claims": [_kinetic(report)]})
        _open_page(bare, "https://example.test/ea", "乙酸乙酯皂化", "皂化反应活化能约为 48.5 kJ/mol。", "v1", "活化能")
        picked = dispatch(bare, "select_evidence", {"claim_id": "v1", "url": "https://example.test/ea"})
        self.assertTrue(picked["abstain"])
        self.assertFalse(picked["sentences"])
        self.assertEqual(bare.judgments[-1]["status"], "not_comparable")

    def test_rate_constant_with_a_different_dosage_is_not_comparable(self):
        report = "在 0.10 mol/L、25摄氏度、电导法下测得速率常数为 0.020 s^-1。"
        evidence = "在 0.02 mol/L、25摄氏度、电导法下速率常数为 0.001 s^-1。"
        job = Job.closed()
        _report(job, report)
        claim = _kinetic(report)
        claim["quantity"] = "速率常数"
        self.assertTrue(dispatch(job, "extract_claims", {"claims": [claim]})["ok"])
        _open_page(job, "https://example.test/rate", "速率", evidence, "v1", "速率常数")
        selected = dispatch(job, "select_evidence", {"claim_id": "v1", "url": "https://example.test/rate"})
        judged = dispatch(
            job,
            "judge_claim",
            {"claim_id": "v1", "verdict": "contradicts", "url": "https://example.test/rate", "sentence_id": selected["sentences"][0]["id"]},
        )
        self.assertEqual(judged["judgment"]["status"], "contradicts")
        self.assertIn("不随初始用量改变", judged["judgment"]["statement"])

    def test_conductivity_above_the_dilute_limit_is_an_unreasonable_step(self):
        report = "在 0.50 mol/L、25摄氏度、电导法下测得速率常数为 0.020 s^-1。"
        evidence = "在 0.50 mol/L、25摄氏度、电导法下速率常数为 0.020 s^-1。"
        job = Job.closed()
        _report(job, report)
        claim = _kinetic(report)
        claim["quantity"] = "速率常数"
        claim["dosage"] = "0.50 mol/L"
        dispatch(job, "extract_claims", {"claims": [claim]})
        _open_page(job, "https://example.test/dense", "电导", evidence, "v1", "电导")
        selected = dispatch(job, "select_evidence", {"claim_id": "v1", "url": "https://example.test/dense"})
        judged = dispatch(
            job,
            "judge_claim",
            {"claim_id": "v1", "verdict": "supports", "url": "https://example.test/dense", "sentence_id": selected["sentences"][0]["id"]},
        )
        self.assertEqual(judged["judgment"]["status"], "contradicts")
        self.assertEqual(judged["judgment"]["reason"], "setup")
        review = dispatch(job, "finish_review", {})
        self.assertEqual(review["review"]["confirmed_errors"][0]["claim_id"], "v1")

    def test_matching_conditions_compare_the_number_even_when_the_wording_differs(self):
        report = "在 0.0101 mol/L、25℃、电导法下测得速率常数为 5.193 L/(mol·min)。"
        evidence = "At 25 °C and 0.01 mol/L, the conductivity method gives k = 6.43 L/(mol·min)."
        job = Job.closed()
        _report(job, report)
        claim = _kinetic(report)
        claim["quantity"] = "速率常数"
        claim["dosage"] = "0.0101 mol/L"
        claim["temperature"] = "25℃"
        self.assertTrue(dispatch(job, "extract_claims", {"claims": [claim]})["ok"])
        _open_page(job, "https://example.test/cond", "电导", evidence, "v1", "saponification")
        selected = dispatch(job, "select_evidence", {"claim_id": "v1", "url": "https://example.test/cond"})
        judged = dispatch(
            job,
            "judge_claim",
            {"claim_id": "v1", "verdict": "supports", "url": "https://example.test/cond", "sentence_id": selected["sentences"][0]["id"]},
        )
        self.assertEqual(judged["judgment"]["status"], "contradicts")
        hotter = "At 35 °C and 0.01 mol/L, the conductivity method gives k = 6.43 L/(mol·min)."
        other = Job.closed()
        _report(other, report)
        dispatch(other, "extract_claims", {"claims": [claim]})
        _open_page(other, "https://example.test/hot", "电导", hotter, "v1", "saponification")
        picked = dispatch(other, "select_evidence", {"claim_id": "v1", "url": "https://example.test/hot"})
        self.assertTrue(picked["abstain"])
        self.assertFalse(picked["sentences"])
        self.assertEqual(other.judgments[-1]["status"], "not_comparable")
        radical = "At 25 °C and 0.01 mol/L, Experimental method: Pulse radiolysis, k = 4.0E8 L/(mol·s)."
        third = Job.closed()
        _report(third, report)
        dispatch(third, "extract_claims", {"claims": [claim]})
        _open_page(third, "https://example.test/pulse", "辐解", radical, "v1", "ethyl acetate")
        picked = dispatch(third, "select_evidence", {"claim_id": "v1", "url": "https://example.test/pulse"})
        self.assertTrue(picked["abstain"])
        self.assertEqual(third.judgments[-1]["status"], "not_comparable")

    def test_a_different_reaction_is_not_compared(self):
        report = "乙酸乙酯皂化。在 0.0101 mol/L、25℃、电导法下测得速率常数为 5.193 L/(mol·min)。"
        evidence = "At 25 °C the conductivity method for ·OH + ethyl acetate gives k = 4.0E8 L/(mol·s)."
        job = Job.closed()
        _report(job, report, "乙酸乙酯皂化")
        claim = _kinetic(report)
        claim["quantity"] = "速率常数"
        claim["dosage"] = "0.0101 mol/L"
        claim["temperature"] = "25℃"
        dispatch(job, "extract_claims", {"claims": [claim]})
        _open_page(job, "https://example.test/radical-k", "自由基", evidence, "v1", "ethyl acetate")
        selected = dispatch(job, "select_evidence", {"claim_id": "v1", "url": "https://example.test/radical-k"})
        self.assertTrue(selected["abstain"])
        self.assertFalse(selected["sentences"])
        self.assertEqual(job.judgments[-1]["status"], "not_comparable")
        self.assertEqual(job.judgments[-1]["reason"], "reaction")

    def test_radical_family_without_plus_sign_is_still_blocked(self):
        report = "在 0.0101 mol/L、25℃、电导法下测得速率常数为 5.193 L/(mol·min)。"
        evidence = "Hydroxyl radical ethyl acetate rate constant at 25 °C by pulse radiolysis is 4.0E8 L/(mol·s)."
        job = Job.closed()
        _report(job, report, "乙酸乙酯皂化")
        claim = _kinetic(report)
        claim["quantity"] = "速率常数"
        claim["dosage"] = "0.0101 mol/L"
        claim["temperature"] = "25℃"
        dispatch(job, "extract_claims", {"claims": [claim]})
        _open_page(job, "https://example.test/radical-family", "自由基", evidence, "v1", "ethyl acetate")
        selected = dispatch(job, "select_evidence", {"claim_id": "v1", "url": "https://example.test/radical-family"})
        self.assertTrue(selected["abstain"])
        self.assertFalse(selected["sentences"])
        self.assertEqual(job.judgments[-1]["status"], "not_comparable")
        self.assertIn(job.judgments[-1]["reason"], {"reaction", "conditions"})

    def test_saponification_literature_naming_naoh_remains_comparable(self):
        report = "乙酸乙酯皂化。在 0.10 mol/L、25摄氏度、电导法下测得活化能为 30 kJ/mol。"
        evidence = "氢氧化钠与乙酸乙酯皂化反应，0.10 mol/L、25摄氏度、电导法下活化能约为 48.5 kJ/mol。"
        job = Job.closed()
        _report(job, report, "乙酸乙酯皂化")
        dispatch(job, "extract_claims", {"claims": [_kinetic(report)]})
        _open_page(job, "https://example.test/naoh-ea", "皂化", evidence, "v1", "皂化 活化能")
        selected = dispatch(job, "select_evidence", {"claim_id": "v1", "url": "https://example.test/naoh-ea"})
        self.assertTrue(selected["sentences"][0]["same_reaction"])
        judged = dispatch(
            job,
            "judge_claim",
            {"claim_id": "v1", "verdict": "supports", "url": "https://example.test/naoh-ea", "sentence_id": selected["sentences"][0]["id"]},
        )
        self.assertEqual(judged["judgment"]["status"], "contradicts")
        self.assertNotEqual(judged["judgment"].get("reason"), "reaction")

    def test_dictionary_pages_are_not_search_results(self):
        self.assertFalse(useful_result("速率_百度百科", "https://baike.baidu.com/item/%E9%80%9F%E7%8E%87/1181335"))
        self.assertFalse(useful_result("ethyl", "https://global.bing.com/dict/search?q=ethyl"))
        self.assertTrue(useful_result("乙酸乙酯皂化反应速率常数", "https://etcps.fudan.edu.cn/images/report.pdf"))

    def test_activation_energy_can_use_an_independence_statement(self):
        report = "在 0.10 mol/L、25摄氏度、电导法下测得活化能为 30 kJ/mol。"
        evidence = "该反应活化能与用量无关，约为 48.5 kJ/mol。"
        job = Job.closed()
        _report(job, report)
        dispatch(job, "extract_claims", {"claims": [_kinetic(report)]})
        _open_page(job, "https://example.test/free", "活化能", evidence, "v1", "活化能 用量")
        selected = dispatch(job, "select_evidence", {"claim_id": "v1", "url": "https://example.test/free"})
        judged = dispatch(
            job,
            "judge_claim",
            {"claim_id": "v1", "verdict": "supports", "url": "https://example.test/free", "sentence_id": selected["sentences"][0]["id"]},
        )
        self.assertEqual(judged["judgment"]["status"], "contradicts")

    def test_arrhenius_is_recomputed_from_the_report(self):
        report = "25摄氏度时速率常数为 0.001 s^-1，35摄氏度时速率常数为 0.002 s^-1，活化能为 10 kJ/mol。"
        job = Job.closed()
        _report(job, report)
        extracted = dispatch(
            job,
            "extract_claims",
            {"claims": [{"id": "c1", "kind": "calculation", "quote": report, "expression": "arrhenius", "reported": "10"}]},
        )
        self.assertTrue(extracted["ok"])
        judged = dispatch(job, "judge_claim", {"claim_id": "c1", "verdict": "supports"})
        self.assertEqual(judged["judgment"]["status"], "contradicts")
        self.assertGreater(judged["judgment"]["computed"], 40)

    def test_rate_is_computed_from_the_equation_and_the_report(self):
        equation = "CH3COOC2H5 + NaOH → CH3COONa + C2H5OH"
        report = f"反应式 {equation}。0.0100 mol/L 下速率常数为 6.00 L/(mol·min)，速率为 0.000600 mol/(L·min)。"
        job = Job.closed()
        _report(job, report)
        extracted = dispatch(
            job,
            "extract_claims",
            {"claims": [{"id": "c1", "kind": "calculation", "quote": report, "expression": "rate", "equation": equation, "reported": "0.000600"}]},
        )
        self.assertTrue(extracted["ok"], extracted)
        judged = dispatch(job, "judge_claim", {"claim_id": "c1", "verdict": "supports"})
        self.assertEqual(judged["judgment"]["status"], "supports")
        wrong = f"反应式 {equation}。0.0100 mol/L 下速率常数为 6.00 L/(mol·min)，速率为 0.006000 mol/(L·min)。"
        other = Job.closed()
        _report(other, wrong)
        dispatch(
            other,
            "extract_claims",
            {"claims": [{"id": "c1", "kind": "calculation", "quote": wrong, "expression": "rate", "equation": equation, "reported": "0.006000"}]},
        )
        contradicted = dispatch(other, "judge_claim", {"claim_id": "c1", "verdict": "supports"})
        self.assertEqual(contradicted["judgment"]["status"], "contradicts")

    def test_dilution_concentration_is_recomputed_from_the_report(self):
        good = "取 10.0 mL 的 0.100 mol/L 母液，定容至 100 mL，得到工作浓度 0.010 mol/L。"
        job = Job.closed()
        _report(job, good)
        extracted = dispatch(
            job,
            "extract_claims",
            {"claims": [{"id": "d1", "kind": "calculation", "quote": good, "expression": "dilution", "reported": "0.010"}]},
        )
        self.assertTrue(extracted["ok"], extracted)
        judged = dispatch(job, "judge_claim", {"claim_id": "d1", "verdict": "supports"})
        self.assertEqual(judged["judgment"]["status"], "supports")
        self.assertAlmostEqual(judged["judgment"]["expected_working_concentration"], 0.01, places=6)
        wrong = "取 10.0 mL 的 0.100 mol/L 母液，定容至 100 mL，得到工作浓度 0.050 mol/L。"
        other = Job.closed()
        _report(other, wrong)
        dispatch(
            other,
            "extract_claims",
            {"claims": [{"id": "d1", "kind": "calculation", "quote": wrong, "expression": "dilution", "reported": "0.050"}]},
        )
        contradicted = dispatch(other, "judge_claim", {"claim_id": "d1", "verdict": "supports", "improvement": "应按 0.010 mol/L 书写工作浓度。"})
        self.assertEqual(contradicted["judgment"]["status"], "contradicts")
        self.assertIn("配制计量错误", contradicted["judgment"]["statement"])
        self.assertAlmostEqual(contradicted["judgment"]["expected_working_concentration"], 0.01, places=6)

    def test_dilution_missing_volumes_returns_a_hint(self):
        report = "用 0.100 mol/L 母液配成工作浓度 0.010 mol/L。"
        job = Job.closed()
        _report(job, report)
        extracted = dispatch(
            job,
            "extract_claims",
            {"claims": [{"id": "d1", "kind": "calculation", "quote": report, "expression": "dilution", "reported": "0.010"}]},
        )
        self.assertFalse(extracted["ok"])
        self.assertEqual(extracted["rejected"][0]["error"], "dilution_missing_volumes")
        self.assertIn("移取体积", extracted["rejected"][0]["hint"])

    def test_offline_cache_serves_pages_when_web_fails(self):
        self.assertTrue(offline_search("乙酸乙酯皂化 电导法 速率常数"))
        self.assertIn("皂化", fetch_page("https://example.test/offline/saponification-conductivity"))
        with patch("kinetics_audit.search._search_bing", side_effect=OSError("offline")):
            found = search_web("乙酸乙酯皂化 电导法 速率常数")
        self.assertTrue(found)
        self.assertTrue(any(item.get("offline") for item in found))
        self.assertTrue(any("saponification-conductivity" in item["url"] for item in found))

    def test_offline_radical_page_does_not_convict_saponification(self):
        report = "乙酸乙酯皂化。在 0.050 mol/L、25摄氏度、电导法下测得速率常数为 0.020 L/(mol·s)。"
        job = Job.closed()
        _report(job, report, "乙酸乙酯皂化")
        claim = {
            "id": "v1",
            "kind": "value",
            "quote": "在 0.050 mol/L、25摄氏度、电导法下测得速率常数为 0.020 L/(mol·s)。",
            "quantity": "速率常数",
            "dosage": "0.050 mol/L",
            "temperature": "25摄氏度",
            "method": "电导法",
        }
        dispatch(job, "extract_claims", {"claims": [claim]})
        radical = offline_page("https://example.test/offline/radical-ethyl-acetate")
        self.assertIn("·OH", radical)
        _open_page(job, "https://example.test/offline/radical-ethyl-acetate", "自由基", radical, "v1", "乙酸乙酯")
        selected = dispatch(job, "select_evidence", {"claim_id": "v1", "url": "https://example.test/offline/radical-ethyl-acetate"})
        self.assertTrue(selected["abstain"])
        self.assertFalse(selected["sentences"])
        self.assertGreater(selected["filtered_out"], 0)
        review = dispatch(job, "finish_review", {})
        self.assertFalse(review["review"]["confirmed_errors"])
        self.assertEqual(review["review"]["insufficient"][0]["status"], "not_comparable")

    def test_stoichiometry_equal_initial_requires_the_claim(self):
        equation = "CH3COOC2H5 + NaOH → CH3COONa + C2H5OH"
        claimed = f"反应式 {equation}。等浓度下乙酸乙酯 0.020 mol/L，氢氧化钠 0.010 mol/L。"
        job = Job.closed()
        _report(job, claimed)
        extracted = dispatch(
            job,
            "extract_claims",
            {
                "claims": [
                    {
                        "id": "s1",
                        "kind": "calculation",
                        "quote": claimed,
                        "expression": "stoichiometry",
                        "equation": equation,
                        "reported": "0.020",
                    }
                ]
            },
        )
        self.assertTrue(extracted["ok"], extracted)
        judged = dispatch(job, "judge_claim", {"claim_id": "s1", "verdict": "contradicts"})
        self.assertEqual(judged["judgment"]["status"], "contradicts")
        silent = f"反应式 {equation}。乙酸乙酯 0.020 mol/L，氢氧化钠 0.010 mol/L。"
        other = Job.closed()
        _report(other, silent)
        dispatch(
            other,
            "extract_claims",
            {
                "claims": [
                    {
                        "id": "s1",
                        "kind": "calculation",
                        "quote": silent,
                        "expression": "stoichiometry",
                        "equation": equation,
                        "reported": "0.020",
                    }
                ]
            },
        )
        skipped = dispatch(other, "judge_claim", {"claim_id": "s1", "verdict": "contradicts"})
        self.assertEqual(skipped["judgment"]["status"], "not_enough")
        review = dispatch(other, "finish_review", {})
        self.assertFalse(review["review"]["confirmed_errors"])
        self.assertEqual(review["review"]["insufficient"][0]["status"], "not_enough")

    def test_metering_error_and_value_error_produce_causal_notes(self):
        equation = "CH3COOC2H5 + NaOH → CH3COONa + C2H5OH"
        report = (
            f"反应式 {equation}。取 10.0 mL 的 0.100 mol/L 母液，定容至 100 mL，得到工作浓度 0.050 mol/L。"
            "在 0.050 mol/L、25摄氏度、电导法下测得速率常数为 0.020 L/(mol·s)。"
        )
        evidence = "在 0.050 mol/L、25摄氏度、电导法下皂化反应速率常数为 0.100 L/(mol·s)。"
        job = Job.closed()
        _report(job, report, "乙酸乙酯皂化")
        dilution_quote = "取 10.0 mL 的 0.100 mol/L 母液，定容至 100 mL，得到工作浓度 0.050 mol/L。"
        value_quote = "在 0.050 mol/L、25摄氏度、电导法下测得速率常数为 0.020 L/(mol·s)。"
        extracted = dispatch(
            job,
            "extract_claims",
            {
                "claims": [
                    {"id": "d1", "kind": "calculation", "quote": dilution_quote, "expression": "dilution", "reported": "0.050"},
                    {
                        "id": "v1",
                        "kind": "value",
                        "quote": value_quote,
                        "quantity": "速率常数",
                        "dosage": "0.050 mol/L",
                        "temperature": "25摄氏度",
                        "method": "电导法",
                    },
                ]
            },
        )
        self.assertTrue(extracted["ok"], extracted)
        dispatch(job, "judge_claim", {"claim_id": "d1", "verdict": "contradicts", "improvement": "工作浓度应为 0.010 mol/L。"})
        _open_page(job, "https://example.test/k", "皂化", evidence, "v1", "皂化 速率常数")
        selected = dispatch(job, "select_evidence", {"claim_id": "v1", "url": "https://example.test/k"})
        dispatch(
            job,
            "judge_claim",
            {
                "claim_id": "v1",
                "verdict": "contradicts",
                "url": "https://example.test/k",
                "sentence_id": selected["sentences"][0]["id"],
                "explanation": "速率常数相对文献偏差过大。",
            },
        )
        review = dispatch(job, "finish_review", {"summary": "计量与速率常数都有问题。"})
        self.assertEqual({item["claim_id"] for item in review["review"]["confirmed_errors"]}, {"d1", "v1"})
        self.assertEqual(review["review"]["causal_notes"][0]["kind"], "metering_may_cause_value_error")
        self.assertIn("d1", review["review"]["causal_notes"][0]["metering_claim_ids"])
        self.assertIn("v1", review["review"]["causal_notes"][0]["value_claim_ids"])
        self.assertIn("应得工作浓度", review["review"]["causal_notes"][0]["statement"])
        self.assertIn("0.01", review["review"]["causal_notes"][0]["statement"])

    def test_disagreeing_literature_values_are_not_report_errors(self):
        report = "在 0.10 mol/L、25摄氏度、电导法下测得活化能为 30 kJ/mol。"
        job = Job.closed()
        _report(job, report)
        dispatch(job, "extract_claims", {"claims": [_kinetic(report)]})
        pages = {
            "https://example.test/low": "0.10 mol/L、25摄氏度、电导法下活化能为 48.5 kJ/mol。",
            "https://example.test/high": "0.10 mol/L、25摄氏度、电导法下活化能为 80 kJ/mol。",
        }
        hits = [{"title": url, "url": url, "excerpt": text} for url, text in pages.items()]
        with patch("kinetics_audit.tools.search_web", return_value=hits), patch("kinetics_audit.tools.fetch_page", side_effect=lambda url: pages[url]):
            dispatch(job, "search_references", {"query": "皂化 活化能", "claim_id": "v1"})
            for url in pages:
                dispatch(job, "read_reference", {"url": url})
                selected = dispatch(job, "select_evidence", {"claim_id": "v1", "url": url})
                dispatch(
                    job,
                    "judge_claim",
                    {"claim_id": "v1", "verdict": "contradicts", "url": url, "sentence_id": selected["sentences"][0]["id"]},
                )
        review = dispatch(job, "finish_review", {})
        self.assertFalse(review["review"]["confirmed_errors"])
        self.assertEqual(review["review"]["insufficient"][0]["status"], "literature_inconsistent")

    def test_calculation_uses_only_numbers_from_the_report(self):
        job = Job.closed()
        report = "2 与 3 相加得到 6。"
        _report(job, report)
        rejected = dispatch(
            job,
            "extract_claims",
            {"claims": [{"id": "c1", "kind": "calculation", "quote": report, "expression": "2+9", "reported": "6"}]},
        )
        self.assertEqual(rejected["rejected"][0]["error"], "number_not_in_quote")
        extracted = dispatch(
            job,
            "extract_claims",
            {"claims": [{"id": "c1", "kind": "calculation", "quote": report, "expression": "2+3", "reported": "6"}]},
        )
        self.assertTrue(extracted["ok"])
        blocked = dispatch(job, "select_evidence", {"claim_id": "c1", "url": "https://example.test/calc"})
        self.assertEqual(blocked["error"], "calculation_skips_search")
        judged = dispatch(job, "judge_claim", {"claim_id": "c1", "verdict": "supports"})
        self.assertEqual(judged["judgment"]["status"], "contradicts")
        self.assertAlmostEqual(judged["judgment"]["computed"], 5.0)
        review = dispatch(job, "finish_review", {})
        self.assertEqual(review["review"]["confirmed_errors"][0]["kind"], "calculation")

    def test_solution_database_record_keeps_measured_fields(self):
        page = (Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "nist_solution_detail.html").read_text(encoding="utf-8")
        text = solution_record(page)
        self.assertIn("3.2E10", text)
        self.assertIn("Pulse radiolysis", text)
        self.assertIn("H2O", text)
        self.assertIn("Baxendale", text)
        links = solution_links('<a href="Detail?id=1965BAX/FIE207-216B:1">x</a>')
        self.assertEqual(links, ["https://kinetics.nist.gov/solution/Detail?id=1965BAX/FIE207-216B:1"])

    def test_enzyme_database_record_keeps_temperature_and_kcat(self):
        record = enzyme_record(
            {
                "id": 4505,
                "reaction": {"equation": "NAD+ + Ethanol = NADH + Acetaldehyde + H+"},
                "enzyme_description": {"enzyme_name": "alcohol dehydrogenase"},
                "general": {"organism": {"name": "Kluyveromyces lactis"}},
                "experimental_conditions": {
                    "buffer": "50 mM Tris-HCl",
                    "envvar_ph": {"start_value": 8},
                    "envvar_temperature": {"start_value": 25, "unit": "°C"},
                },
                "kineticlaw": {
                    "parameter": [
                        {
                            "name": "kcat",
                            "role": "Constant",
                            "parameter_type": {"name": "kcat"},
                            "start_value": 24500,
                            "unit": {"name": "min^(-1)"},
                        }
                    ]
                },
                "publication": {"author": "Brisdelli F", "journal": "Biochimie", "year": 2004, "title": "Kinetic properties"},
            }
        )
        self.assertIn("kcat 24500 min^(-1)", record["text"])
        self.assertIn("温度 25 °C", record["text"])
        self.assertIn("4505", record["url"])

    def test_database_record_enters_the_same_judgment(self):
        report = "在 0.10 mol/L、25摄氏度、电导法下测得速率常数为 0.020 s^-1。"
        evidence = "在 0.10 mol/L、25摄氏度、电导法下速率常数为 0.001 s^-1。"
        job = Job.closed()
        _report(job, report)
        claim = _kinetic(report)
        claim["quantity"] = "速率常数"
        dispatch(job, "extract_claims", {"claims": [claim]})
        with patch(
            "kinetics_audit.tools.search_solution",
            return_value=[{"title": "OH", "url": "https://kinetics.nist.gov/solution/Detail?id=test", "text": evidence}],
        ):
            found = dispatch(job, "search_solution_kinetics", {"claim_id": "v1", "reactant": "OH", "solvent": "water"})
        self.assertTrue(found["ok"])
        selected = dispatch(job, "select_evidence", {"claim_id": "v1", "url": found["results"][0]["url"]})
        judged = dispatch(
            job,
            "judge_claim",
            {
                "claim_id": "v1",
                "verdict": "supports",
                "url": found["results"][0]["url"],
                "sentence_id": selected["sentences"][0]["id"],
            },
        )
        self.assertEqual(judged["judgment"]["status"], "contradicts")
        blocked = dispatch(job, "search_solution_kinetics", {"claim_id": "v1", "reactant": "<script>"})
        self.assertEqual(blocked["error"], "query_required")

    def test_retry_searches_the_missing_conditions_once(self):
        report = "在 0.10 mol/L、25摄氏度、电导法下测得速率常数为 0.020 s^-1。"
        weak = "皂化反应速率常数约为 0.001 s^-1。"
        strong = "在 0.10 mol/L、25摄氏度、电导法下速率常数为 0.001 s^-1。"
        job = Job.closed()
        _report(job, report)
        claim = _kinetic(report)
        claim["quantity"] = "速率常数"
        dispatch(job, "extract_claims", {"claims": [claim]})
        _open_page(job, "https://example.test/weak", "速率", weak, "v1", "速率常数")
        selected = dispatch(job, "select_evidence", {"claim_id": "v1", "url": "https://example.test/weak"})
        self.assertTrue(selected["abstain"])
        self.assertEqual(job.judgments[-1]["status"], "not_comparable")
        limited = dispatch(job, "search_references", {"query": "速率常数 0.10 mol/L", "claim_id": "v1"})
        self.assertEqual(limited["error"], "search_limit")
        hit = {"title": "条件一致", "url": "https://example.test/strong", "excerpt": strong}
        with patch("kinetics_audit.tools.search_web", return_value=[hit]), patch("kinetics_audit.tools.fetch_page", return_value=strong):
            retried = dispatch(job, "retry_claim", {"claim_id": "v1"})
            self.assertTrue(retried["ok"])
            self.assertIn("0.10 mol/L", retried["query"])
            self.assertIn("25摄氏度", retried["query"])
            self.assertIn("电导法", retried["query"])
            dispatch(job, "read_reference", {"url": "https://example.test/strong"})
        picked = dispatch(job, "select_evidence", {"claim_id": "v1", "url": "https://example.test/strong"})
        second = dispatch(
            job,
            "judge_claim",
            {
                "claim_id": "v1",
                "verdict": "supports",
                "url": "https://example.test/strong",
                "sentence_id": picked["sentences"][0]["id"],
            },
        )
        self.assertEqual(second["judgment"]["status"], "contradicts")
        self.assertEqual(dispatch(job, "retry_claim", {"claim_id": "v1"})["error"], "retry_exhausted")
        review = dispatch(job, "finish_review", {})
        self.assertEqual(review["review"]["confirmed_errors"][0]["claim_id"], "v1")

    def test_retry_does_not_run_after_a_decisive_judgment(self):
        job = Job.closed()
        report = "2 与 3 相加得到 6。"
        _report(job, report)
        dispatch(
            job,
            "extract_claims",
            {"claims": [{"id": "c1", "kind": "calculation", "quote": report, "expression": "2+3", "reported": "6"}]},
        )
        dispatch(job, "judge_claim", {"claim_id": "c1", "verdict": "supports"})
        self.assertEqual(dispatch(job, "retry_claim", {"claim_id": "c1"})["error"], "calculation_skips_search")

    def test_number_token_does_not_match_inside_longer_number(self):
        found = measurements("测得活化能为 300 kJ/mol。")
        self.assertEqual([item["number"] for item in found], ["300"])

    def test_pdf_tables_become_claim_sentences(self):
        table = [
            ["c0(mol/L)", "T", "k(L/mol/min)"],
            ["0.0101", "25℃", "5.193"],
            ["0.0100", "35℃", "5.113"],
        ]
        sentences = _table_to_sentences(table)
        self.assertTrue(any("5.193" in line and "0.0101" in line for line in sentences), sentences)
        # 整页误识别：超长单格应丢弃
        self.assertEqual(_table_to_sentences([["x" * 200, "y"], ["a", "b"]]), [])
        flat = (
            "数据处理 c(mol/L)=0.010125C 时间 电导率 "
            "a=-0.118 b=0.0525 k(L/mol/min)=5.193 t/min "
            "文献报道25 ℃ 速率6.4254（L/mol/min）"
        )
        synthesized = _kinetics_sentences_from_text(flat)
        self.assertTrue(
            any("5.193" in line and "0.0101" in line and "25摄氏度" in line for line in synthesized),
            synthesized,
        )
        self.assertTrue(any("6.4254" in line for line in synthesized), synthesized)
        job = Job.closed()
        report = flat + "\n" + "\n".join(synthesized)
        _report(job, report, "乙酸乙酯皂化")
        prop = dispatch(job, "propose_candidates", {})
        hit = next(c for c in prop["candidates"] if "5.193" in c["quote"] and "速率常数" in c["quote"])
        extracted = dispatch(
            job,
            "extract_claims",
            {
                "claims": [
                    {
                        "id": "v1",
                        "kind": "value",
                        "quote": hit["quote"],
                        "candidate_id": hit["id"],
                        "quantity": "速率常数",
                        "dosage": "0.0101 mol/L",
                        "temperature": "25摄氏度",
                        "method": "电导法",
                    }
                ]
            },
        )
        self.assertTrue(extracted["ok"], extracted)

    def test_report_documents_are_read_and_photos_are_not(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            document = root / "report.docx"
            paragraph = "拟合时把摄氏温度换算成开尔文。"
            xml = (
                "<?xml version='1.0' encoding='UTF-8'?>"
                "<w:document xmlns:w='http://schemas.openxmlformats.org/wordprocessingml/2006/main'>"
                f"<w:p><w:r><w:t>{escape(paragraph)}</w:t></w:r></w:p></w:document>"
            )
            with zipfile.ZipFile(document, "w") as archive:
                archive.writestr("word/document.xml", xml)
            self.assertIn("开尔文", extract_report(document))
            photo = root / "page.png"
            photo.write_bytes(b"\x89PNG\r\n")
            with self.assertRaises(ValueError) as raised:
                extract_report(photo)
            self.assertEqual(str(raised.exception), "image")
            secret = root.parent / "secret.txt"
            secret.write_text("hidden", encoding="utf-8")
            try:
                with self.assertRaises(ValueError):
                    locate_report(secret, root)
            finally:
                secret.unlink()
        project_photo = Path(__file__).resolve().parents[1] / "page.png"
        project_photo.write_bytes(b"\x89PNG\r\n")
        try:
            seen = dispatch(Job.closed(), "read_report", {"experiment": "皂化反应", "path": "page.png"})
        finally:
            project_photo.unlink()
        self.assertEqual(seen["error"], "image_use_session_image")

    def test_guard_blocks_import(self):
        with self.assertRaises(GuardError):
            check_source("import os\ndef run(data_path, out_dir):\n    pass\n")

    def test_sandbox_blocks_parent_read(self):
        source = "def run(data_path, out_dir):\n    open('../outside.txt', encoding='utf-8').read()\n"
        result = execute(source, [{"run_id": 1, "value": 1}])
        self.assertNotEqual(result["exit_code"], 0)

    def test_spectrophotometry_is_comparable_only_with_the_same_method(self):
        report = "乙酸乙酯皂化。在 0.050 mol/L、25摄氏度、分光光度法下测得速率常数为 0.020 L/(mol·s)。"
        evidence = offline_page("https://example.test/offline/saponification-spectrophotometry")
        job = Job.closed()
        _report(job, report, "乙酸乙酯皂化")
        claim = {
            "id": "v1",
            "kind": "value",
            "quote": "在 0.050 mol/L、25摄氏度、分光光度法下测得速率常数为 0.020 L/(mol·s)。",
            "quantity": "速率常数",
            "dosage": "0.050 mol/L",
            "temperature": "25摄氏度",
            "method": "分光光度法",
        }
        dispatch(job, "extract_claims", {"claims": [claim]})
        _open_page(job, "https://example.test/offline/saponification-spectrophotometry", "分光", evidence, "v1", "皂化 分光")
        selected = dispatch(job, "select_evidence", {"claim_id": "v1", "url": "https://example.test/offline/saponification-spectrophotometry"})
        judged = dispatch(
            job,
            "judge_claim",
            {
                "claim_id": "v1",
                "verdict": "supports",
                "url": "https://example.test/offline/saponification-spectrophotometry",
                "sentence_id": selected["sentences"][0]["id"],
            },
        )
        self.assertEqual(judged["judgment"]["status"], "contradicts")
        conductivity = offline_page("https://example.test/offline/saponification-conductivity")
        other = Job.closed()
        _report(other, report, "乙酸乙酯皂化")
        dispatch(other, "extract_claims", {"claims": [claim]})
        _open_page(other, "https://example.test/offline/saponification-conductivity", "电导", conductivity, "v1", "皂化 电导")
        picked = dispatch(other, "select_evidence", {"claim_id": "v1", "url": "https://example.test/offline/saponification-conductivity"})
        self.assertTrue(picked["abstain"])
        self.assertFalse(picked["sentences"])
        self.assertEqual(other.judgments[-1]["status"], "not_comparable")
        self.assertEqual(other.judgments[-1]["reason"], "conditions")

    def test_stopped_flow_offline_page_is_a_distinct_method(self):
        report = "在 0.010 mol/L、25摄氏度、停流法下测得速率常数为 0.020 L/(mol·s)。"
        evidence = offline_page("https://example.test/offline/saponification-stopped-flow")
        job = Job.closed()
        _report(job, report, "乙酸乙酯皂化")
        claim = {
            "id": "v1",
            "kind": "value",
            "quote": report,
            "quantity": "速率常数",
            "dosage": "0.010 mol/L",
            "temperature": "25摄氏度",
            "method": "停流法",
        }
        dispatch(job, "extract_claims", {"claims": [claim]})
        _open_page(job, "https://example.test/offline/saponification-stopped-flow", "停流", evidence, "v1", "皂化 停流")
        selected = dispatch(job, "select_evidence", {"claim_id": "v1", "url": "https://example.test/offline/saponification-stopped-flow"})
        judged = dispatch(
            job,
            "judge_claim",
            {
                "claim_id": "v1",
                "verdict": "supports",
                "url": "https://example.test/offline/saponification-stopped-flow",
                "sentence_id": selected["sentences"][0]["id"],
            },
        )
        self.assertEqual(judged["judgment"]["status"], "contradicts")

    def test_arrhenius_missing_data_returns_a_hint(self):
        report = "活化能为 10 kJ/mol。"
        job = Job.closed()
        _report(job, report)
        extracted = dispatch(
            job,
            "extract_claims",
            {"claims": [{"id": "c1", "kind": "calculation", "quote": report, "expression": "arrhenius", "reported": "10"}]},
        )
        self.assertFalse(extracted["ok"])
        self.assertEqual(extracted["rejected"][0]["error"], "arrhenius_data_required")
        self.assertIn("两组温度", extracted["rejected"][0]["hint"])

    def test_propose_candidates_gates_extract_claims(self):
        report = "在 0.10 mol/L、25摄氏度、电导法下测得活化能为 30 kJ/mol。"
        job = Job.closed()
        _report(job, report)
        proposed = dispatch(job, "propose_candidates", {})
        self.assertTrue(proposed["ok"])
        self.assertGreaterEqual(proposed["count"], 1)
        self.assertIn("value", proposed["candidates"][0]["kinds"])
        ok = dispatch(
            job,
            "extract_claims",
            {
                "claims": [
                    {
                        **_kinetic(report),
                        "candidate_id": proposed["candidates"][0]["id"],
                    }
                ]
            },
        )
        self.assertTrue(ok["ok"], ok)
        forged = Job.closed()
        _report(forged, report)
        dispatch(forged, "propose_candidates", {})
        bad = dispatch(
            forged,
            "extract_claims",
            {
                "claims": [
                    {
                        "id": "v1",
                        "kind": "value",
                        "quote": "文献里随便写的活化能为 30 kJ/mol。",
                        "quantity": "活化能",
                        "dosage": "0.10 mol/L",
                        "temperature": "25摄氏度",
                        "method": "电导法",
                    }
                ]
            },
        )
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["rejected"][0]["error"], "quote_not_in_report")

    def test_table_k_labels_extract_as_rate_claims(self):
        report = (
            "乙酸乙酯皂化用电导法测定。\n"
            "c0(mol/L)= 0.0101 25℃\n"
            "k(L/mol/min)= 5.193\n"
            "c0(mol/L)= 0.0100 35℃\n"
            "k(L/mol/min)= 5.113\n"
        )
        spaced = (
            "conductivity method. "
            "c 0 (mol/L)= 0.0101 25 C "
            "k(L/mol/min)= 5.193 "
            "k(L/mol/min)= 5.113"
        )
        spaced_job = Job.closed()
        _report(spaced_job, spaced)
        spaced_prop = dispatch(spaced_job, "propose_candidates", {})
        spaced_hits = [
            item
            for item in spaced_prop["candidates"]
            if "5.193" in item["quote"] and "0.0101" in item["quote"] and len(item["quote"]) < 300
        ]
        self.assertTrue(spaced_hits, spaced_prop["candidates"])
        spaced_ok = dispatch(
            spaced_job,
            "extract_claims",
            {
                "claims": [
                    {
                        "id": "v1",
                        "kind": "value",
                        "quote": spaced_hits[0]["quote"],
                        "candidate_id": spaced_hits[0]["id"],
                        "quantity": "k",
                        "dosage": "0.0101",
                        "temperature": "25℃",
                        "method": "电导法",
                    }
                ]
            },
        )
        self.assertTrue(spaced_ok["ok"], spaced_ok)
        self.assertTrue(any(item["number"] == "5.193" for item in measurements(report)))
        job = Job.closed()
        _report(job, report)
        proposed = dispatch(job, "propose_candidates", {})
        self.assertTrue(proposed["ok"])
        value_rows = [
            item
            for item in proposed["candidates"]
            if "value" in item["kinds"] and "5.193" in item["quote"] and "0.0101" in item["quote"] and "25℃" in item["quote"]
        ]
        self.assertTrue(value_rows, proposed["candidates"])
        quote = value_rows[0]["quote"]
        extracted = dispatch(
            job,
            "extract_claims",
            {
                "claims": [
                    {
                        "id": "v1",
                        "kind": "value",
                        "quote": quote,
                        "candidate_id": value_rows[0]["id"],
                        "quantity": "速率常数",
                        "dosage": "0.0101",
                        "temperature": "25℃",
                        "method": "电导法",
                    },
                    {
                        "id": "v2",
                        "kind": "value",
                        "quote": quote,
                        "candidate_id": value_rows[0]["id"],
                        "quantity": "k",
                        "dosage": "0.0101",
                        "temperature": "25℃",
                        "method": "电导法",
                    },
                ]
            },
        )
        self.assertTrue(extracted["ok"], extracted)
        self.assertEqual(extracted["claims"][0]["quantity"], "速率常数")
        self.assertEqual(extracted["claims"][1]["quantity"], "速率常数")


if __name__ == "__main__":
    unittest.main()
