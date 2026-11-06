"""Chinese-adjacent English references remain identities, not experimental measurements."""

import json
import socket
from dataclasses import replace
from pathlib import Path

import pytest
from test_publication_composition import candidates
from test_review_targets import SchemaReviewer

from research_radar.analysis.localization import (
    _preserve_quantities,
    localization_failed,
    localize_report_content,
)
from research_radar.analysis.providers import ModelResponse
from research_radar.analysis.review import review_publication_facts
from research_radar.models import Artifact, SourceCandidate, SourceType
from research_radar.security.secrets import KeychainSecretBackend

DATA = json.loads((Path(__file__).parent / "fixtures/mixed_script_reference.json").read_text())


@pytest.fixture(autouse=True)
def offline_only(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args, **_kwargs) -> None:
        raise AssertionError("No services or credentials in reference regression")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(KeychainSecretBackend, "get_secret", forbidden)


@pytest.mark.parametrize(("original", "translated"), [
    (DATA["original_text"], DATA["translated_text"]),
    ("The value is 0.8435 in Table 3.", "数值在Table 3中为0.8435。"),
    ("Figure 2 reports 70%.", "见Figure 2，结果为70%。"),
    ("Fig. 2 reports 70%.", "见Fig. 2，结果为70%。"),
    ("Section 4.6 reports 70%.", "见Section 4.6，结果为70%。"),
    ("Equation 4 reports 70%.", "见Equation 4，结果为70%。"),
])
def test_unchanged_reference_and_values_pass_without_editing_text(
    original: str, translated: str,
) -> None:
    findings = []
    assert _preserve_quantities(original, translated,
                               findings=findings, field="claims") == translated
    assert not findings


@pytest.mark.parametrize("translated", [
    DATA["translated_text"].replace("Table 6", "Table 7"),
    DATA["translated_text"].replace("Table 6", "Figure 6"),
    DATA["translated_text"].replace("Table 6", "StableTable 6"),
    DATA["translated_text"].replace("Table 6", "Data_Table 6"),
    DATA["translated_text"].replace("Table 6", "3Table 6"),
    DATA["translated_text"].replace("5.09", "5.10"),
    DATA["translated_text"].replace("5.09", "5.05").replace("正文给出5.05", "正文给出5.09"),
    DATA["translated_text"].replace("5.09", "5.09 ms"),
])
def test_reference_and_measurement_changes_are_still_rejected(translated: str) -> None:
    findings = []
    assert _preserve_quantities(DATA["original_text"], translated,
        findings=findings, field="claims") == DATA["original_text"]
    assert findings


def test_verified_composition_accepts_literal_saved_reply_without_new_approval() -> None:
    reading, claim = candidates()
    reading = replace(reading, source_url=DATA["source_url"])
    claim = replace(claim, text=DATA["original_text"],
        evidence=[replace(claim.evidence[0], source_url=reading.source_url,
                          quote=DATA["original_text"])],
        metadata={"paper_reading": {"claim_id": "c42", "section": "experiment"}})
    artifact = Artifact(SourceCandidate("Offline", reading.source_url, SourceType.PAPER,
                                       "fixture"), DATA["original_text"])
    facts = review_publication_facts([claim], SchemaReviewer(), model="offline",
                                    readings=[reading], artifacts=[artifact])

    class SavedReply:
        name = "offline-saved-composition"
        calls = 0
        reader_contexts = SchemaReviewer.reader_contexts

        def complete(self, _messages, *, model: str) -> ModelResponse:
            self.calls += 1
            assert self.calls == 1
            return ModelResponse(json.dumps({"reader_explanation": {
                "experiment_interpretation": [DATA["paragraph"]]},
                "claims": [{"claim_id": "c42", "text": DATA["translated_text"]}]},
                ensure_ascii=False), model)

    provider = SavedReply()
    result = localize_report_content(readings=facts.readings, claims=facts.claims,
        sources=[artifact.source], provider=provider, model="offline", language="zh",
        verified_facts=True)
    assert not localization_failed(result)
    assert provider.calls == 1
    assert result.claims[0].text == DATA["translated_text"]
    assert result.claims[0].evidence == facts.claims[0].evidence
    assert result.readings[0].reader_explanation.experiment_interpretation[0].review is None
