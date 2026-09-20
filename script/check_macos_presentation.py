#!/usr/bin/env python3
"""Test-only native presentation/resource driver; never builds or runs the engine.

Run ONLY after integration/staging has finished, with no concurrent Swift build:
  python script/check_macos_presentation.py --integration-ready
Optional internal settings snapshots require an existing -enable-testing build:
  --swift-build .build/swift-scratch/arm64-apple-macosx/debug --internal-settings
The accessory test app attaches a real status item to the production popover.
Screenshots pair an owned-popover image with a narrow status-button crop, never
a full desktop capture. All primary screenshots use the production RootView.
Settings snapshots, when enabled, host the production internal view directly
and are labelled separately.
Use --outcome-snapshots for isolated no-new-content/incomplete/partial-ready
RootView/TodayView fixtures only, not staged production or engine acceptance.
Artifacts are retained under .build/task3a-visual/<uuid>; cleanup uses Trash only.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import plistlib
import shutil
import signal
import struct
import subprocess
import time
import zlib
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], timeout: float = 120) -> str:
    """Run a bounded command and retain failures rather than fake success."""
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(
            f"{command[0]} exited {result.returncode}: {result.stderr or result.stdout}"
        )
    return result.stdout.strip()


def write_json(path: Path, value: Any) -> None:
    """Publish a complete JSON document atomically."""
    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def fingerprint(paths: list[Path]) -> dict[str, str]:
    """Record exact link inputs, including modules, for reproducibility."""
    return {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths}


def existing_objects(build: Path, allow_stale: bool) -> tuple[list[Path], list[str]]:
    """Use current output maps, not stale objects left by renamed source files."""
    objects: list[Path] = []
    stale: list[str] = []
    for module in ("ResearchRadarCore", "ResearchRadarAppFeature"):
        mapping = json.loads((build / f"{module}.build/output-file-map.json").read_text())
        for source, outputs in mapping.items():
            if not source or "object" not in outputs:
                continue
            obj = Path(outputs["object"]).resolve(strict=True)
            if Path(source).stat().st_mtime_ns > obj.stat().st_mtime_ns:
                stale.append(source)
                if not allow_stale:
                    raise RuntimeError(
                        f"Stale object for {source}; parent must finish staging first"
                    )
            objects.append(obj)
    if not objects:
        raise RuntimeError("No existing production module objects found")
    return objects, stale


def fixture(root: Path) -> dict[str, str]:
    """Create local-only HTML using the existing frozen reader's actual content."""
    source = ROOT / "tests/fixtures/offline_frozen/reader.json"
    reading = json.loads(source.read_text())["deep_readings"]
    run_root = root / "workspace/run"
    run_root.mkdir(parents=True)
    # A deterministic PNG chart, generated without external image dependencies.
    width, height = 480, 160
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            bar = 30 <= x <= 200 and 70 <= y <= 130 or 250 <= x <= 420 and 30 <= y <= 130
            rows.extend((45, 125, 185) if bar else (245, 247, 249))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
        )

    png = b"\x89PNG\r\n\x1a\n" + chunk(
        b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    )
    png += chunk(b"IDAT", zlib.compress(bytes(rows))) + chunk(b"IEND", b"")
    (run_root / "evidence.png").write_bytes(png)
    body = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="color-scheme" content="light dark"><meta name="viewport" content="width=device-width">
<style>body{{font:17px -apple-system;line-height:1.6;margin:24px;max-width:760px}}
img{{max-width:100%;height:auto}}a{{color:#2679b9}}pre{{white-space:pre-wrap}}</style></head>
<body><h1>Grounded memory evaluation / 记忆证据评估</h1>
<p>Offline acceptance fixture, not a scientific measurement.</p>
<nav><a href="#evidence">Evidence / 证据</a> · <a href="#formula">Formula / 公式</a></nav>
<h2 id="evidence">Evidence / 证据</h2><p>{html.escape(reading["essence"])}</p>
<p>{html.escape(reading["plain_language_example"])}</p>
<img src="evidence.png" width="480" height="160"
alt="Illustrative local fixture bars, not measured results">
<h2 id="formula">Static formula / 静态公式</h2><p>score = supported answers / total answers</p>
<p>{html.escape(reading["limitations"]["explicit_limitations"][0])}</p>
<p><a href="#evidence">Back to evidence / 返回证据</a></p></body></html>"""
    (run_root / "report.html").write_text(body, encoding="utf-8")
    write_json(run_root / "article.json", reading)
    return {
        "source": str(source),
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "kind": "local acceptance HTML derived from frozen reader JSON; not engine-rendered output",
    }


def frozen_report(root: Path, source: Path | None) -> dict[str, Any]:
    """Copy an existing frozen renderer run without changing any HTML/resource bytes."""
    if source is None:
        candidates = sorted((ROOT / ".build/task2-staged-offline-2").glob("**/wechat.html"))
        if not candidates:
            candidates = sorted((ROOT / ".build/offline-frozen-verified-2").glob("**/wechat.html"))
        if not candidates:
            return {"status": "not_available", "reason": "No existing offline frozen wechat.html"}
        source = candidates[-1]
    source = source.resolve(strict=True)
    if source.name != "wechat.html":
        raise ValueError("--frozen-report must name the existing renderer's wechat.html")
    files = sorted(source.parent.rglob("*"))
    if any(path.is_symlink() for path in files):
        raise ValueError("Frozen run contains symlinks; refusing to copy external resources")
    files = [path for path in files if path.is_file()]
    before = fingerprint(files)
    destination = root / "workspace/rendered"
    shutil.copytree(source.parent, destination)
    copied = {str(path): str(destination / path.relative_to(source.parent)) for path in files}
    if any(
        hashlib.sha256(Path(copy).read_bytes()).hexdigest() != before[path]
        for path, copy in copied.items()
    ):
        raise RuntimeError("Frozen renderer copy does not match original artifacts")
    return {
        "status": "copied_byte_for_byte",
        "source": str(source),
        "source_sha256_before": before,
        "copied_paths": copied,
    }


def stage_harness(
    root: Path, app: Path, build: Path, internal: bool, allow_stale: bool
) -> dict[str, Any]:
    """Link existing modules, copy staged app and replace only its test-copy entrypoint."""
    objects, stale = existing_objects(build, allow_stale)
    modules = list((build / "Modules").glob("ResearchRadar*.swiftmodule"))
    source = ROOT / "tests/fixtures/task3a_visual_app.swift"
    inputs = objects + modules + [source, app / "Contents/Info.plist"]
    before = fingerprint(inputs)
    target = root / "Task3AVisual.app"
    run(["/usr/bin/ditto", str(app), str(target)])
    info_path = target / "Contents/Info.plist"
    with info_path.open("rb") as stream:
        info = plistlib.load(stream)
    executable = target / "Contents/MacOS" / info["CFBundleExecutable"]
    info["CFBundleIdentifier"] = f"ai.research-radar.task3a.{uuid4().hex}"
    info["CFBundleName"] = "ResearchRadar Task3A Test"
    info["LSUIElement"] = True
    with info_path.open("wb") as stream:
        plistlib.dump(info, stream)
    # Use the project's existing cache only after integration/builds have stopped.
    module_cache = ROOT / ".build/swift-module-cache"
    module_cache.mkdir(parents=True, exist_ok=True)
    command = [
        "/usr/bin/xcrun",
        "swiftc",
        "-parse-as-library",
        "-swift-version",
        "6",
        "-target",
        "arm64-apple-macosx26.0",
        "-I",
        str(build / "Modules"),
        "-module-cache-path",
        str(module_cache),
    ]
    if internal:
        command += ["-D", "TASK3A_INTERNAL_SETTINGS"]
    command += [str(source), *map(str, objects), "-o", str(root / "test-executable")]
    run(command, timeout=180)
    run(["/usr/bin/ditto", str(root / "test-executable"), str(executable)])
    # Nested code is unchanged from the staged app; preserve its existing signatures.
    for signing_target in (executable, target):
        run(
            [
                "/usr/bin/codesign",
                "--force",
                "--sign",
                "-",
                "--timestamp=none",
                str(signing_target),
            ]
        )
    run(["/usr/bin/codesign", "--verify", "--deep", "--strict", str(target)])
    if before != fingerprint(inputs):
        raise RuntimeError(
            "Build inputs changed while linking; move this run to Trash and retry after integration"
        )
    return {
        "app": str(target),
        "swift_build": str(build),
        "module_cache": str(module_cache),
        "signing_scope": "replacement executable then outer app; nested signatures unchanged",
        "link_command": command,
        "input_sha256": before,
        "sources_newer_than_objects": stale,
    }


class Driver:
    """Exchange bounded commands with this one app instance, without system AX changes."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.pid: int | None = None

    def command(self, action: str, **values: Any) -> dict[str, Any]:
        """Send a command and wait for the matching atomic response."""
        if action == "configure":
            deadline = time.monotonic() + 15
            while True:
                anchor = self.command("inspect")
                if anchor["status_anchor_visible"]:
                    break
                if time.monotonic() >= deadline:
                    write_json(self.root / "status-anchor-unavailable.json", anchor)
                    raise RuntimeError("Status item backing window not visible after 15 seconds")
                time.sleep(0.2)
        request = dict(
            id=uuid4().hex,
            action=action,
            mode="compact",
            state="idle",
            language="en",
            appearance="light",
            artifact="fixture",
            target="",
        )
        request.update(values)
        write_json(self.root / "command.json", request)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            path = self.root / "response.json"
            if path.exists():
                response = json.loads(path.read_text())
                if response["id"] == request["id"]:
                    self.pid = response["pid"]
                    if "error" in response:
                        write_json(self.root / "command-error.json", response)
                        raise RuntimeError(response["error"])
                    return response
            time.sleep(0.1)
        raise TimeoutError(f"No response to {action}; see {self.root}")

    def settled(
        self, reader: bool = False, released: bool = False, shown: bool = True
    ) -> dict[str, Any]:
        """Observe popover visibility and WebKit lifetime without refocusing the app."""
        time.sleep(0.5)
        deadline = time.monotonic() + 20
        ready_since: float | None = None
        while time.monotonic() < deadline:
            state = self.command("inspect")
            visible = any(
                window.get("kCGWindowNumber") == state["window_id"]
                for window in state["cg_windows"]
            )
            if (
                state["popover_shown"] != shown
                or state["presentation_visible"] != shown
                or (shown and not visible)
            ):
                ready_since = None
                time.sleep(0.25)
                continue
            ready = False
            if reader:
                if state["webview_count"] == 1 and all(
                    not web["loading"] and web["url"].startswith("radar-report://")
                    for web in state["webviews"]
                ):
                    ready = True
            elif not released or state["webview_count"] == 0 and state["retired_alive"] == 0:
                ready = True
            if ready:
                if ready_since is None:
                    ready_since = time.monotonic()
                elif time.monotonic() - ready_since >= 0.75:
                    return state
            else:
                ready_since = None
            time.sleep(0.25)
        requirement = (
            "reader load" if reader else "reader release" if released else "popover visibility"
        )
        raise TimeoutError(f"Readiness requirement ({requirement}) not observed: {state}")


def check_popover_size(state: dict[str, Any]) -> None:
    """Check base dimensions and production screen-clamped sizing."""
    base = (400, 480) if state["window_mode"] == "compact" else (900, 660)
    for axis, requested in zip(("width", "height"), base, strict=True):
        observed = state[axis]
        expected = state[f"expected_{axis}"]
        if abs(observed - expected) > 1 or not 0 < observed <= requested + 1:
            raise RuntimeError(f"Popover {axis} differs from screen-clamped size: {state}")
        margin = 24 if axis == "width" else 32
        if state[f"available_{axis}"] >= requested + margin and abs(observed - requested) > 1:
            raise RuntimeError(f"Popover {axis} does not match its preferred size: {state}")


def capture_popover(driver: Driver, state: dict[str, Any], path: Path) -> dict[str, str]:
    """Capture only the owned popover and a separate, tightly scoped menu-bar button."""
    if not state["popover_shown"] or not any(
        window.get("kCGWindowNumber") == state["window_id"] for window in state["cg_windows"]
    ):
        raise RuntimeError("Shown popover not found in owned on-screen window inventory")
    check_popover_size(state)
    rect = state.get("status_capture_rect")
    if not rect or len(rect) != 4 or not 0 < rect[2] <= 100 or not 0 < rect[3] <= 100:
        raise RuntimeError("Missing or unsafe status-button capture region")
    status_path = path.with_name(f"{path.stem}-status-item.png")
    run(["/usr/sbin/screencapture", "-x", "-o", "-l", str(state["window_id"]), str(path)])
    region = ",".join(str(round(value)) for value in rect)
    run(["/usr/sbin/screencapture", "-x", f"-R{region}", str(status_path)])
    for image in (path, status_path):
        if not image.exists() or image.stat().st_size == 0:
            raise RuntimeError(f"No screenshot produced: {image}")
    return {"popover": str(path), "menu_bar_context": str(status_path)}


def require_native_controls(driver: Driver, report: dict[str, Any]) -> None:
    """Require actual status-item and mode-control actions, not just AX labels."""
    report["mandatory_controls"] = []
    for mode, label_index in (("compact", 0), ("full", 1)):
        driver.command("configure", mode=mode, state="complete")
        driver.settled()
        snapshot = driver.command("snapshot")
        label = snapshot["control_labels"][label_index]
        available = any(
            node["role"] == "AXButton" and label in node["labels"]
            for node in snapshot["accessibility"]
        )
        path = driver.root / f"required-controls-{mode}.png"
        captures = capture_popover(driver, snapshot, path)
        report["mandatory_controls"].append(
            {
                "mode": mode,
                "expected_button": label,
                "available": available,
                "snapshot": snapshot,
                "screenshots": captures,
            }
        )
        write_json(driver.root / "acceptance.json", report)
        if not available:
            raise RuntimeError(f"Mandatory native {mode} control absent: {label}")
        target = "action.full_workspace" if mode == "compact" else "action.compact"
        pressed = driver.command("press", target=target)
        changed = driver.settled()
        expected_mode = "full" if mode == "compact" else "compact"
        if changed["window_mode"] != expected_mode:
            raise RuntimeError(f"Mode control press did not switch to {expected_mode}")
        check_popover_size(changed)
        driver.command("clickStatusItem")
        closed = driver.settled(released=True, shown=False)
        driver.command("clickStatusItem")
        reopened = driver.settled()
        if not reopened["status_item_present"] or reopened["window_mode"] != expected_mode:
            raise RuntimeError("Status-item reopen lost the selected mode")
        if not reopened["is_key_window"] or not reopened["app_active"]:
            raise RuntimeError("Reopened popover did not acquire input focus")
        driver.command("pressEscape")
        escaped = driver.settled(released=True, shown=False)
        driver.command("clickStatusItem")
        driver.settled()
        driver.command("prepareOutsideTarget")
        outside_ready = driver.settled()
        driver.command("clickOutsideTarget")
        outside_closed = driver.settled(released=True, shown=False)
        if outside_closed["outside_click_count"] <= outside_ready["outside_click_count"]:
            raise RuntimeError("Outside click was not received by the controlled target")
        driver.command("removeOutsideTarget")
        driver.command("clickStatusItem")
        driver.settled()
        report["mandatory_controls"][-1].update(
            press=pressed, changed=changed, closed=closed, reopened=reopened,
            escaped=escaped, outside_ready=outside_ready, outside_closed=outside_closed,
        )
        write_json(driver.root / "acceptance.json", report)


def diagnostic_snapshots(
    driver: Driver, report: dict[str, Any], *, failure_only: bool = False,
    onboarding_only: bool = False, outcome_only: bool = False,
) -> None:
    """Capture compact/full controls without claiming final visual/resource acceptance."""
    report["diagnostic_snapshots"] = []
    cases = (
        ("compact", "complete"),
        ("full", "complete"),
        ("compact", "failed"),
        ("full", "failed"),
        ("compact", "idle"),
        ("compact", "running"),
        ("compact", "missingConfig"),
        ("compact", "missingKey"),
    )
    if failure_only:
        cases = (("compact", "failed"), ("full", "failed"))
    if onboarding_only:
        cases = tuple(("full", state) for state in (
            "setupAppearance", "setupServices", "setupTopic", "setupReady",
        ))
    outcome_cases = {
        "no_new_content": ("no_new_content", ["no_eligible_papers"], 0, 0),
        "incomplete": ("incomplete", ["full_text_unavailable"], 0, 0),
        "partial_ready": ("ready", ["reading_failed"], 1, 2),
    }
    if outcome_only:
        cases = tuple((mode, state) for mode in ("compact", "full") for state in outcome_cases)
    for language, appearance, mode, state in (
        (language, appearance, mode, state)
        for language in ("zh-Hans", "en")
        for appearance in ("light", "dark")
        for mode, state in cases
    ):
        driver.command(
            "configure", mode=mode, state=state, language=language, appearance=appearance
        )
        driver.settled()
        snapshot = driver.command("snapshot")
        if outcome_only:
            status, reasons, deep_count, claim_count = outcome_cases[state]
            observed = snapshot.get("outcome_fixture", {})
            expected_outcome = {
                "status": status, "reasons": reasons,
                "deep_read_count": deep_count, "publishable_claim_count": claim_count,
            }
            if any(observed.get(key) != value for key, value in expected_outcome.items()):
                raise RuntimeError(f"Outcome fixture mismatch for {state}: {observed}")
        path = driver.root / f"diagnostic-{language}-{appearance}-{mode}-{state}.png"
        captures = capture_popover(driver, snapshot, path)
        labels = [label for node in snapshot["accessibility"] for label in node["labels"]]
        expected = snapshot["control_labels"][0 if mode == "compact" else 1]
        report["diagnostic_snapshots"].append(
            {
                "mode": mode,
                "state": state,
                "language": language,
                "appearance": appearance,
                "snapshot": snapshot,
                "screenshots": captures,
                "expected_control": expected,
                "control_in_ax_tree": expected in labels,
            }
        )
        print(path, flush=True)
        write_json(driver.root / "acceptance.json", report)


def native_navigation(driver: Driver, report: dict[str, Any]) -> None:
    """Press actual Root controls using in-process AX, without setting view selection."""
    report["native_navigation"] = []
    for language in ("en", "zh-Hans"):
        driver.command("configure", language=language, mode="compact", state="complete")
        driver.settled()
        for target in ("action.full_workspace", "nav.settings", "nav.topics", "nav.reports"):
            record: dict[str, Any] = {
                "language": language,
                "target": target,
                "before": driver.command("snapshot"),
            }
            report["native_navigation"].append(record)
            pressed = driver.command("press", target=target)
            record["press"] = pressed
            label = pressed["last_action"]["label"]
            deadline = time.monotonic() + 5
            while True:
                time.sleep(0.2)
                after = driver.command("snapshot")
                record["after"] = after
                selected = [label for row in after["selected_rows"] for label in row]
                matched = (
                    after["window_mode"] == "full"
                    and abs(after["width"] - after["expected_width"]) <= 1
                    if target == "action.full_workspace"
                    else label in selected
                )
                if matched or time.monotonic() >= deadline:
                    break
            screenshot = driver.root / f"navigation-{language}-{target}.png"
            record["screenshots"] = capture_popover(driver, after, screenshot)
            record["selection_observed"] = matched
            write_json(driver.root / "acceptance.json", report)
            if not matched:
                raise RuntimeError(f"Native press did not produce observable selection: {target}")
        driver.command("press", target="action.open_report")
        opened = driver.settled(reader=True)
        driver.command("press", target="action.compact")
        compact_reader = driver.settled(released=True)
        if compact_reader["window_mode"] != "compact":
            raise RuntimeError("Reader compact action did not change mode")
        driver.command("press", target="action.full_workspace")
        restored_reader = driver.settled(reader=True)
        report.setdefault("reader_mode_transitions", []).append(
            dict(language=language, opened=opened, compact=compact_reader, restored=restored_reader)
        )
        for attempt in range(2):
            before = driver.settled(reader=True)
            report_id = before["selected_report_id"]
            if not report_id:
                raise RuntimeError("Same-report regression requires an existing selection")
            driver.command("press", target="nav.settings")
            driver.settled(released=True)
            settings = driver.command("snapshot")
            selected = [label for row in settings["selected_rows"] for label in row]
            if settings["settings_label"] not in selected:
                raise RuntimeError("Same-report regression did not reach Settings")
            driver.command("press", target="action.compact")
            compact = driver.settled(released=True)
            if compact["window_mode"] != "compact":
                raise RuntimeError("Settings did not switch to compact")
            pressed = driver.command("press", target="action.open_report")
            reopened = driver.settled(reader=True)
            if reopened["window_mode"] != "full" or any(
                state["selected_report_id"] != report_id
                for state in (settings, compact, reopened)
            ):
                raise RuntimeError("Reopening the same report lost mode or selection")
            if reopened["webviews"][0]["url"] != before["webviews"][0]["url"]:
                raise RuntimeError("Same-report action loaded a different artifact")
            report.setdefault("same_report_reopen", []).append(
                dict(
                    language=language, attempt=attempt + 1, before=before,
                    settings=settings, compact=compact, press=pressed, reopened=reopened,
                )
            )
            write_json(driver.root / "acceptance.json", report)
        driver.command("press", target="nav.topics")
        driver.settled(released=True)
        edit = driver.command("editTopicName")
        smoke: dict[str, Any] = {"language": language, "edit": edit}
        report.setdefault("draft_preservation", []).append(smoke)
        if not edit["last_action"]["accepted"]:
            raise RuntimeError("Cannot verify draft preservation: topic field rejected edit")
        driver.command("press", target="action.compact")
        driver.settled()
        compact = driver.command("snapshot")
        smoke["compact"] = compact
        if compact["window_mode"] != "compact":
            raise RuntimeError("Edit page did not switch directly to compact")
        driver.command("press", target="action.full_workspace")
        driver.settled()
        expanded = driver.command("snapshot")
        smoke["expanded"] = expanded
        assert_topic_draft(expanded, edit)
        driver.command("clickStatusItem")
        smoke["closed"] = driver.settled(released=True, shown=False)
        driver.command("clickStatusItem")
        driver.settled()
        reopened = driver.command("snapshot")
        smoke["reopened"] = reopened
        assert_topic_draft(reopened, edit)
        path = driver.root / f"preserved-draft-{language}.png"
        smoke["screenshots"] = capture_popover(driver, reopened, path)
        write_json(driver.root / "acceptance.json", report)
        for state, expected_error in (
            ("missingConfig", "codex_not_configured"),
            ("missingKey", "credentials_missing"),
        ):
            driver.command("configure", language=language, mode="compact", state=state)
            before = driver.settled()
            if before["configuration_error"] != expected_error:
                raise RuntimeError(f"Setup fixture has wrong validation state: {state}")
            press = driver.command("press", target="action.configure")
            driver.settled()
            after = driver.command("snapshot")
            selected = [label for row in after["selected_rows"] for label in row]
            if after["window_mode"] != "full" or after["settings_label"] not in selected:
                raise RuntimeError(f"Setup action did not open native Settings: {state}")
            report.setdefault("setup_navigation", []).append(
                dict(language=language, state=state, before=before, press=press, after=after)
            )
            write_json(driver.root / "acceptance.json", report)
    report["settings_navigation"] = "Root sidebar selection observed; screenshot review pending"


def assert_topic_draft(snapshot: dict[str, Any], edit: dict[str, Any]) -> None:
    """Require the mounted edit field to retain its draft without persisting it."""
    fields = [node for node in snapshot["accessibility"] if node["role"] == "AXTextField"]
    if snapshot["window_mode"] != "full" or not any(
        "Task3A unsaved draft" in field["labels"] for field in fields
    ):
        raise RuntimeError("Unsaved topic draft was lost after compact/reopen")
    if snapshot["saved_topic_name"] != edit["last_action"]["original"]:
        raise RuntimeError("Unsaved draft unexpectedly persisted to AppStore")


def process_sample(pid: int) -> dict[str, Any]:
    """Measure app RSS/CPU and inventory descendants plus unattributed WebKit processes."""
    rows = []
    for line in run(["/bin/ps", "-axo", "pid=,ppid=,rss=,%cpu=,comm="]).splitlines():
        parts = line.split(None, 4)
        if len(parts) == 5:
            rows.append(
                dict(
                    pid=int(parts[0]),
                    ppid=int(parts[1]),
                    rss_bytes=int(parts[2]) * 1024,
                    cpu_percent=float(parts[3]),
                    command=parts[4],
                )
            )
    own = next((row for row in rows if row["pid"] == pid), None)
    if own is None:
        raise RuntimeError(f"Harness app exited: {pid}")
    descendants: set[int] = set()
    while True:
        found = {row["pid"] for row in rows if row["ppid"] in descendants | {pid}}
        if found <= descendants:
            break
        descendants |= found
    return {
        "app": own,
        "descendants": [row for row in rows if row["pid"] in descendants],
        "webkit_candidates_unattributed": [row for row in rows if "WebKit" in row["command"]],
    }


def main() -> int:
    """Run the explicitly authorized post-integration acceptance pass."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--integration-ready", action="store_true", help="Confirm staging/builds have finished"
    )
    parser.add_argument("--app", type=Path, default=ROOT / "dist/ResearchRadar.app")
    parser.add_argument(
        "--swift-build", type=Path, default=ROOT / ".build/swift-release/arm64-apple-macosx/release"
    )
    parser.add_argument("--internal-settings", action="store_true")
    parser.add_argument(
        "--failure-snapshots", action="store_true",
        help="Only diagnostic compact/full failure snapshots; not interaction acceptance",
    )
    parser.add_argument(
        "--onboarding-snapshots", action="store_true",
        help="Only first-run page snapshots using isolated saved state; not interaction acceptance",
    )
    parser.add_argument(
        "--outcome-snapshots", action="store_true",
        help="Only isolated no-new-content/incomplete/partial-ready compact/full snapshots; "
        "not staged production acceptance",
    )
    parser.add_argument(
        "--resources-only",
        action="store_true",
        help="Run mandatory controls and reader/idle measurements, not the matrix",
    )
    parser.add_argument(
        "--native-navigation",
        action="store_true",
        help="Compatibility flag; native navigation and draft preservation are now mandatory",
    )
    parser.add_argument(
        "--navigation-only",
        action="store_true",
        help="Only press Root expand/sidebar controls and capture AX/screenshots",
    )
    parser.add_argument(
        "--diagnostic-only",
        action="store_true",
        help="Scoped compact/full popover snapshots; explicitly not final acceptance",
    )
    parser.add_argument(
        "--diagnostic-resources",
        action="store_true",
        help="Diagnostic snapshots plus fixture-seeded reader/idle metrics; not acceptance",
    )
    parser.add_argument(
        "--frozen-report",
        type=Path,
        help="Existing frozen renderer wechat.html; auto-detect known offline runs",
    )
    parser.add_argument(
        "--allow-stale-build",
        action="store_true",
        help="Explicitly test an older built snapshot; record stale source paths",
    )
    parser.add_argument("--cycles", type=int, default=20)
    parser.add_argument("--idle-seconds", type=float, default=300)
    args = parser.parse_args()
    if args.outcome_snapshots and any((
        args.failure_snapshots, args.onboarding_snapshots, args.diagnostic_resources,
        args.internal_settings,
    )):
        parser.error("outcome-snapshots cannot be combined with other snapshot/resource modes")
    if (
        args.diagnostic_resources or args.failure_snapshots or args.onboarding_snapshots
        or args.outcome_snapshots
    ):
        args.diagnostic_only = True
    if not args.integration_ready:
        parser.error(
            "Wait for parent integration/staging, then explicitly pass --integration-ready"
        )
    if args.cycles < 1 or args.idle_seconds < 0:
        parser.error("cycles must be positive and idle-seconds nonnegative")
    if args.navigation_only and args.diagnostic_only:
        parser.error("Choose either navigation-only or diagnostic-only")
    if args.resources_only and (args.navigation_only or args.diagnostic_only):
        parser.error("resources-only cannot be combined with diagnostic/navigation-only")
    root = ROOT / ".build/task3a-visual" / uuid4().hex
    root.mkdir(parents=True, mode=0o700)
    driver = Driver(root)
    report: dict[str, Any] = {
        "schema_version": 1,
        "status": "started",
        "root": str(root),
        "scope": "test entrypoint; production views/offline AppStore; not production startup",
        "screenshots": [],
        "cycles": [],
        "reader_cycle_method": (
            "status-item click hides/reopens popover; weak reader release/remount"
        ),
        "capture_scope": (
            "owned popover without shadow plus separate status-button crop; "
            "no full desktop capture"
        ),
        "matrix_requested": not args.resources_only,
        "idle_samples": [],
        "visual_review": "pending external screenshot inspection",
        "leak_assertion": "not made; weak WKWebView release and RSS are separate observations",
        "network_evidence": (
            "engineURL=nil; no scheduler/bootstrap; fake key presence only; /usr/bin/true is "
            "validated but never launched; production reader policy; no packet capture"
        ),
        "settings": "direct internal view, not Root navigation"
        if args.internal_settings
        else "not covered: no public Root settings route",
        "accessibility": "in-process AX control gate/navigation; no OS preferences changed",
        "input_fidelity": (
            "Status clicks/Escape use CG events only with existing permission, otherwise local "
            "NSEvents; each response records mechanism. No performClick status shortcut. "
            "Other controls use AX press with local event fallback."
        ),
        "external_interaction_limit": (
            "Outside clicks target a harness-owned secondary window, never a user's app. "
            "Cross-application focus and hardware interaction remain unverified."
        ),
        "running_fixture_limit": (
            "JobRecord running snapshot only; no active execution gate or engine runner. "
            "Run Now/cancel enablement is not evidence of live-job behavior."
        ),
    }
    if args.diagnostic_only:
        report["interaction_gate"] = "blocked: SwiftUI AX labels unavailable; not passed"
        report["settings"] = "not covered by diagnostic snapshots"
    if args.outcome_snapshots:
        report["interaction_gate"] = "not run: outcome fixture snapshots only"
        report["outcome_snapshots"] = {
            "states": ["no_new_content", "incomplete", "partial_ready"],
            "expected_screenshot_count": 24,
            "scope": "production RootView/TodayView with isolated synthetic report/job state",
            "acceptance_limit": "Not staged production startup, engine execution, or delivery "
            "acceptance; screenshots still require visual inspection",
        }
    if args.diagnostic_resources:
        report["reader_setup"] = (
            "Fixture-seeded report selection, not a successful control press; subsequent "
            "close/reopen uses status-item NSEvents, with fidelity recorded per response"
        )
    try:
        report["fixture"] = fixture(root)
        report["frozen_renderer"] = frozen_report(root, args.frozen_report)
        report["build"] = stage_harness(
            root,
            args.app.resolve(strict=True),
            args.swift_build.resolve(strict=True),
            args.internal_settings,
            args.allow_stale_build,
        )
        # LaunchServices launches a real .app; all overrides are scoped to this launch.
        run(
            [
                "/usr/bin/open",
                "-n",
                "-a",
                report["build"]["app"],
                "--env",
                f"TASK3A_ROOT={root}",
                "--env",
                f"RESEARCH_RADAR_DEV_ROOT={root / 'unused-bootstrap'}",
            ]
        )
        if not args.diagnostic_only:
            require_native_controls(driver, report)
        modes = (
            ("compact", "full", "reader", "settings")
            if args.internal_settings
            else ("compact", "full", "reader")
        )
        if report["frozen_renderer"]["status"] == "copied_byte_for_byte":
            modes += ("rendered",)
        if not args.diagnostic_only:
            native_navigation(driver, report)
            report["settings"] = report["settings_navigation"]
        if args.navigation_only:
            modes = ()
        if args.diagnostic_only:
            diagnostic_snapshots(driver, report, failure_only=args.failure_snapshots,
                                 onboarding_only=args.onboarding_snapshots,
                                 outcome_only=args.outcome_snapshots)
            modes = ()
        if args.resources_only:
            modes = ()
        for language in ("en", "zh-Hans"):
            for appearance in ("light", "dark"):
                for mode in modes:
                    states = (
                        (
                            "idle", "running", "complete", "failed", "unknown",
                            "missingConfig", "missingKey",
                        )
                        if mode in ("compact", "full")
                        else ("complete",)
                    )
                    for state in states:
                        case = dict(
                            language=language, appearance=appearance, mode=mode, state=state
                        )
                        launch_case = dict(case)
                        if mode == "rendered":
                            launch_case.update(mode="reader", artifact="rendered")
                        driver.command("configure", **launch_case)
                        driver.settled()
                        if mode in ("reader", "rendered"):
                            driver.command("openReader")
                        observed = driver.settled(reader=mode in ("reader", "rendered"))
                        path = root / ("-".join(map(str, case.values())) + ".png")
                        captures = capture_popover(driver, observed, path)
                        report["screenshots"].append(dict(case=case, observed=observed, **captures))
                        print(f"Captured {path.name}", flush=True)
                        write_json(root / "acceptance.json", report)
        if args.diagnostic_resources or not (args.navigation_only or args.diagnostic_only):
            driver.command(
                "configure", mode="reader", state="complete",
                target="diagnostic-reader" if args.diagnostic_resources else "",
            )
            driver.settled()
            if not args.diagnostic_resources:
                driver.command("openReader")
            driver.settled(reader=True)
            for index in range(args.cycles):
                opened = driver.settled(reader=True)
                driver.command("closeReader")
                closed = driver.settled(released=True, shown=False)
                report["cycles"].append(
                    dict(
                        index=index + 1,
                        opened=opened,
                        closed=closed,
                        resources=process_sample(driver.pid),
                    )
                )
                print(f"Reader lifecycle cycle {index + 1}/{args.cycles}", flush=True)
                write_json(root / "acceptance.json", report)
                if index + 1 < args.cycles:
                    driver.command("openReader")
            driver.command("configure", mode="compact", state="idle")
            native = driver.settled(released=True)
            driver.command("idle")  # Disable command polling during native-only idle sampling.
            started = time.monotonic()
            while True:
                elapsed = time.monotonic() - started
                report["idle_samples"].append(
                    dict(elapsed_seconds=elapsed, **process_sample(driver.pid))
                )
                write_json(root / "acceptance.json", report)
                if elapsed >= args.idle_seconds:
                    break
                time.sleep(min(5, args.idle_seconds - elapsed))
            report["idle_duration_seconds"] = time.monotonic() - started
            report["native_idle_view"] = native
            report["requested"] = dict(cycles=args.cycles, idle_seconds=args.idle_seconds)
            report["standard_resource_duration_met"] = (
                args.cycles >= 20 and report["idle_duration_seconds"] >= 300
            )
        else:
            report["resource_measurement"] = "not requested: diagnostic/navigation-only run"
            if args.navigation_only:
                report["settings"] = report["settings_navigation"]
        report["status"] = (
            "diagnostic_complete_not_final_acceptance"
            if args.diagnostic_only
            else "measurements_complete_visual_review_pending"
        )
    except KeyboardInterrupt:
        report["status"] = "interrupted"
        report["error"] = "Acceptance interrupted; partial observations retained"
    except (OSError, RuntimeError, TimeoutError, ValueError, subprocess.SubprocessError) as error:
        report["status"] = "failed"
        report["error"] = str(error)
    finally:
        if driver.pid is None and (root / "app.pid").exists():
            driver.pid = int((root / "app.pid").read_text())
        if driver.pid is not None:
            try:
                os.kill(driver.pid, signal.SIGTERM)
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    try:
                        os.kill(driver.pid, 0)
                    except ProcessLookupError:
                        report["app_termination_confirmed"] = True
                        break
                    time.sleep(0.1)
                else:
                    report["app_termination_confirmed"] = False
                    report["status"] = "failed_app_did_not_terminate"
            except ProcessLookupError:
                report["app_already_exited"] = True
        frozen = report.get("frozen_renderer", {})
        if frozen.get("status") == "copied_byte_for_byte":
            try:
                after = fingerprint([Path(path) for path in frozen["source_sha256_before"]])
                frozen["source_sha256_after"] = after
                frozen["original_artifacts_unchanged"] = after == frozen["source_sha256_before"]
                frozen["copied_artifacts_unchanged"] = all(
                    hashlib.sha256(Path(copy).read_bytes()).hexdigest() == after[source]
                    for source, copy in frozen["copied_paths"].items()
                )
                if not all(
                    frozen[key]
                    for key in ("original_artifacts_unchanged", "copied_artifacts_unchanged")
                ):
                    report["status"] = "failed_artifact_integrity"
            except OSError as error:
                frozen["integrity_error"] = str(error)
                report["status"] = "failed_artifact_integrity"
        write_json(root / "acceptance.json", report)
        print(root / "acceptance.json", flush=True)
    return (
        0
        if report["status"]
        in (
            "measurements_complete_visual_review_pending",
            "diagnostic_complete_not_final_acceptance",
        )
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
