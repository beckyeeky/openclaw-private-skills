import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from verify_redaction import main, verify


def types(text, aliases=()):
    return {item["type"] for item in verify(text, aliases)}


class ReviewTests(unittest.TestCase):
    def test_email_normal_and_fullwidth(self):
        for text in ("alice@example.com", "ａｌｉｃｅ＠ｅｘａｍｐｌｅ．ｃｏｍ"):
            with self.subTest(text=text):
                self.assertTrue({"email_candidate", "at_candidate"} <= types(text))

    def test_phone(self):
        for text in ("+86 138-0013-8000", "(010) 1234 5678", "１３８００１３８０００"):
            self.assertIn("phone_candidate", types(text))

    def test_alias_case_width_and_expansion(self):
        for text, alias in (("ａｃＭｅ", "AcME"), ("Straße", "STRASSE"),
                            ("张先生", "张先生"), ("甲公司", "甲公司")):
            self.assertIn("alias_unresolved_leak", types(text, [alias]))

    def test_alias_overlap_and_multiline(self):
        hits = [h for h in verify("aaaa\n私人\n实体", ["aaa", "私人\n实体"])
                if h["type"] == "alias_unresolved_leak"]
        self.assertEqual([(h["line"], h["column"]) for h in hits], [(1, 1), (1, 2), (2, 1)])

    def test_cas_and_keywords(self):
        self.assertIn("cas_candidate", types("CAS 64-17-5"))
        for keyword in ("PO", "合同", "批号", "批准文号", "信用代码"):
            self.assertIn("identifier_keyword_candidate", types(keyword))

    def test_titles_and_company(self):
        for text in ("张先生", "李女士", "王经理", "赵总"):
            self.assertIn("cjk_title_candidate", types(text))
        self.assertIn("company_suffix_candidate", types("某某有限公司"))

    def test_multilingual_titles_and_identifiers(self):
        self.assertIn("cjk_title_candidate", types("李工"))
        self.assertIn("korean_title_candidate", types("김민수님"))
        self.assertIn("company_suffix_candidate", types("주식회사"))
        for text in ("微信", "注册证号", "LOT", "batch", "contract", "approval", "WeChat"):
            self.assertIn("identifier_keyword_candidate", types(text))

    def test_multipart_labels_remain_review_candidates(self):
        hits = verify("A1 → B1、C1，批次1与批次2。")
        self.assertTrue(hits)
        self.assertNotIn("alias_unresolved_leak", {h["type"] for h in hits})

    def test_url_and_capitalization(self):
        self.assertIn("url_candidate", types("https://example.com/a"))
        self.assertIn("capitalized_word_candidate", types("Alice approved"))

    def test_retained_numbers_are_only_candidates(self):
        text = "交期2026-10-09，金额1000.50元，数量20。"
        hits = verify(text)
        self.assertTrue(hits)
        self.assertTrue(all(h["type"].endswith("_candidate") for h in hits))
        self.assertEqual(text, "交期2026-10-09，金额1000.50元，数量20。")

    def test_clean_labels(self):
        self.assertEqual(verify("A → B\n甲公司、乙公司、该公司\n终端客户，检测机构。"), [])

    def test_normalized_coordinates(self):
        hits = verify("说明\nß ａｃｍｅ", ["ACME"])
        self.assertIn({"type": "alias_unresolved_leak", "line": 2, "column": 4}, hits)

    def invoke(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(argv)
        self.assertEqual(err.getvalue(), "")
        return code, out.getvalue()

    def test_cli_codes_and_no_disclosure_or_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output, aliases = root / "output.txt", root / "private.json"
            secret = "PrivatePerson"
            content = secret + " private@example.com"
            output.write_text(content, encoding="utf-8")
            aliases.write_text(json.dumps([secret]), encoding="utf-8")
            code, raw = self.invoke([str(output), "--aliases", str(aliases)])
            self.assertEqual(code, 1)
            for value in (secret, "private@example.com", str(root)):
                self.assertNotIn(value, raw)
            for hit in json.loads(raw):
                self.assertEqual(set(hit), {"type", "line", "column"})
            self.assertEqual(output.read_text(encoding="utf-8"), content)
            self.assertEqual(json.loads(aliases.read_text(encoding="utf-8")), [secret])
            output.write_text("A → B", encoding="utf-8")
            code, raw = self.invoke([str(output)])
            self.assertEqual((code, json.loads(raw)), (0, []))

    def test_bad_arguments_and_input(self):
        for argv in ([], ["--private-unknown-secret"], ["/no/such/private-file"]):
            code, raw = self.invoke(argv)
            self.assertEqual(code, 2)
            self.assertEqual(json.loads(raw), [{"type": "input_error", "line": 0, "column": 0}])
        with tempfile.TemporaryDirectory() as directory:
            output, aliases = Path(directory) / "out", Path(directory) / "aliases"
            output.write_text("正常正文", encoding="utf-8")
            for invalid in ('{', '{}', 'null', '[1]', '[""]', '["   "]'):
                aliases.write_text(invalid, encoding="utf-8")
                self.assertEqual(self.invoke([str(output), "--aliases", str(aliases)])[0], 2)
            output.write_bytes(b"\xff")
            self.assertEqual(self.invoke([str(output)])[0], 2)
            output.unlink()
            output.mkdir()
            self.assertEqual(self.invoke([str(output)])[0], 2)


if __name__ == "__main__":
    unittest.main()
