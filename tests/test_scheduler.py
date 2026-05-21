from research_radar.scheduler.local import launchd_label


def test_launchd_label_uses_research_radar_name() -> None:
    label = launchd_label("Agent Memory", "daily_monitor")

    assert label == "ai.research-radar.daily-monitor.agent-memory"
    assert "researchpress" not in label
