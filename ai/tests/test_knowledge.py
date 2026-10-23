"""작성: rootkit · 2026-10-23. Run: python -m unittest discover -s tests -v."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from pydantic import ValidationError

from app.errors import DomainError
from app.knowledge import approved_knowledge, read_jsonl, retrieve, validate_knowledge
from app.models import Document, KnowledgeProposal
from tests.helpers import documents, knowledge


class KnowledgeTests(unittest.TestCase):
    def validate(self, proposal=None, sources=None):
        return validate_knowledge(KnowledgeProposal.model_validate(proposal or knowledge()), sources or documents())

    def test_normalization_preserves_whole_email_paragraph_order(self):
        document = documents()[0].model_dump()
        original = document["body"]
        document["body"] = original.replace("\n", "\r\n")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.jsonl"
            path.write_text("\ufeff" + json.dumps(document, ensure_ascii=False) + "\n\n", encoding="utf-8")
            result = read_jsonl(path)
        self.assertEqual(result[0].body, original)
        self.assertEqual(retrieve([result[0].model_dump()], [result[0].id])[0]["body"], original)

    def test_jsonl_reports_missing_metadata_and_line_number(self):
        row = documents()[0].model_dump()
        del row["recipient_group"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.jsonl"
            path.write_text(json.dumps(documents()[1].model_dump()) + "\n" + json.dumps(row))
            with self.assertRaisesRegex(DomainError, "line 2"):
                read_jsonl(path)

    def test_unsupported_formats_empty_input_and_duplicate_ids_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.csv"
            path.write_text("id,body\na,hello")
            with self.assertRaisesRegex(DomainError, "jsonl"):
                read_jsonl(path)
            path = Path(directory) / "input.jsonl"
            path.write_text("\n")
            with self.assertRaisesRegex(DomainError, "at least one"):
                read_jsonl(path)
            row = json.dumps(documents()[0].model_dump())
            path.write_text(row + "\n" + row)
            with self.assertRaisesRegex(DomainError, "Duplicate"):
                read_jsonl(path)

    def test_recipient_is_explicit_metadata_not_customer_keyword(self):
        result = self.validate()
        self.assertIn("고객", documents()[0].body)
        self.assertEqual(result["patterns"][0]["recipient_group"], "general")
        missing = documents()[0].model_dump()
        del missing["recipient_group"]
        with self.assertRaises(ValidationError):
            Document.model_validate(missing)

    def test_candidate_term_is_not_an_enforced_term(self):
        result = self.validate()
        self.assertEqual(len(result["terms"]), 1)
        self.assertFalse(result["terms"][0]["approved"])
        self.assertEqual(approved_knowledge(result)["terms"], [])
        self.assertEqual(len(approved_knowledge(result)["patterns"]), 1)

    def test_term_with_unknown_or_fabricated_evidence_is_withheld(self):
        for evidence in [{"source_id": "b-mail-1", "quote": "출고 준비표"},
                         {"source_id": "a-mail-1", "quote": "발명한 회사 규정"}]:
            with self.subTest(evidence=evidence):
                proposal = knowledge()
                proposal["terms"][0]["evidence"] = [evidence]
                result = self.validate(proposal)
                self.assertEqual(result["terms"], [])
                self.assertTrue(result["withheld"][0]["reasons"])

    def test_two_independent_emails_are_insufficient(self):
        proposal = knowledge()
        proposal["patterns"][0]["observations"].pop()
        result = self.validate(proposal)
        self.assertEqual(result["patterns"], [])
        self.assertTrue(any("3 independent" in reason for item in result["withheld"] for reason in item["reasons"]))

    def test_repeated_case_or_copied_body_cannot_count_as_independent(self):
        for attribute in ("case_id", "body"):
            with self.subTest(attribute=attribute):
                sources = documents()
                sources[2] = sources[2].model_copy(update={attribute: getattr(sources[1], attribute)})
                proposal = knowledge()
                if attribute == "body":
                    proposal["patterns"][0]["observations"][2]["sections"] = deepcopy(proposal["patterns"][0]["observations"][1]["sections"])
                self.assertEqual(self.validate(proposal, sources)["patterns"], [])

    def test_report_and_mismatched_group_language_or_situation_are_not_pattern_evidence(self):
        for changes in [{"kind": "report"}, {"recipient_group": "customer"}, {"language": "en"}, {"situation": "welcome"}]:
            with self.subTest(changes=changes):
                sources = documents()
                sources[2] = sources[2].model_copy(update=changes)
                result = self.validate(sources=sources)
                self.assertEqual(result["patterns"], [])
                self.assertTrue(result["withheld"])

    def test_source_paragraph_order_is_checked(self):
        proposal = knowledge()
        proposal["patterns"][0]["observations"][1]["sections"].reverse()
        result = self.validate(proposal)
        self.assertEqual(result["patterns"], [])
        self.assertTrue(any("order" in reason for item in result["withheld"] for reason in item["reasons"]))

    def test_conflicting_supported_patterns_are_both_withheld(self):
        sources = documents()
        proposal = knowledge()
        alternative = deepcopy(proposal["patterns"][0])
        alternative["id"] = "a-pattern-alternative"
        alternative["sequence"] = ["status", "purpose", "request"]
        for index, observation in enumerate(alternative["observations"]):
            source = sources[index]
            paragraphs = source.body.split("\n\n")
            paragraphs[1], paragraphs[2] = paragraphs[2], paragraphs[1]
            new_id = f"a-conflict-{index}"
            sources.append(source.model_copy(update={"id": new_id, "case_id": new_id, "body": "\n\n".join(paragraphs)}))
            observation["source_id"] = new_id
            observation["sections"][0], observation["sections"][1] = observation["sections"][1], observation["sections"][0]
        proposal["patterns"].append(alternative)
        result = self.validate(proposal, sources)
        self.assertEqual(result["patterns"], [])
        self.assertEqual({item["id"] for item in result["withheld"]}, {"a-pattern", "a-pattern-alternative"})


if __name__ == "__main__":
    unittest.main()
