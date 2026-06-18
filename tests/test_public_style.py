from research_radar.analysis.public_style import audit_public_writing_text


def test_public_style_audit_flags_template_and_machine_metadata() -> None:
    findings = audit_public_writing_text(
        "综上所述，这不仅仅是一个系统，更是一个抓手。"
        " role=primary_paper status=new score=0.8",
        target="wechat.html",
        language="zh",
    )

    patterns = {finding.metadata["pattern"] for finding in findings}

    assert "empty_summary" in patterns
    assert "false_depth" in patterns
    assert "business_jargon" in patterns
    assert "machine_metadata" in patterns
    assert all(finding.severity == "warning" for finding in findings)
    assert all(
        finding.metadata["kind"] == "public_writing_style" for finding in findings
    )


def test_public_style_audit_flags_english_ai_phrases() -> None:
    findings = audit_public_writing_text(
        "In conclusion, this pivotal system showcases a vibrant ecosystem.",
        target="daily.md",
        language="en",
    )

    assert [finding.metadata["pattern"] for finding in findings] == [
        "english_ai_phrase"
    ]


def test_public_style_audit_leaves_protected_technical_text_alone() -> None:
    text = (
        "LOCOMO and LongMemEval report TTFT=70.4%, and the retention function "
        "is R(t)=e^{-t/S(m)}."
    )

    findings = audit_public_writing_text(text, target="wechat.html", language="zh")

    assert findings == []
