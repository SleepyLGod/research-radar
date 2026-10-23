"""npm Codex startup under an App-like PATH without invoking Codex or Node."""

import json
import shlex
import shutil
import sys
from pathlib import Path

import pytest

from research_radar.analysis.cli_providers import CodexCliProvider
from research_radar.analysis.providers import Message
from research_radar.exceptions import AnalysisError


@pytest.mark.parametrize("resolved_path", [False, True])
def test_npm_codex_uses_its_installation_node_with_sanitized_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    resolved_path: bool,
) -> None:
    prefix = tmp_path / "Research Tools" / "node-installation"
    script = prefix / "lib/node_modules/@openai/codex/bin/codex.js"
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env node\n// Offline npm launcher fixture\n")
    script.chmod(0o700)
    node = prefix / "bin/node"
    node.parent.mkdir()
    node.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\nfrom pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "output = Path(args[args.index('--output-last-message') + 1])\n"
        "output.write_text(json.dumps({'launcher': args[0], 'args': args[1:], "
        "'path': os.environ['PATH']}))\n"
    )
    node.chmod(0o700)
    link = prefix / "bin/codex"
    link.symlink_to(script)
    selected = script if resolved_path else link
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    provider = CodexCliProvider(
        name="codex",
        reasoning_effort="xhigh",
        command=f"{shlex.quote(str(selected))} --profile 'offline research'",
    )
    provider.health_check()
    response = provider.complete(
        [Message(role="user", content="offline only")],
        model="offline-model",
    )
    value = json.loads(response.content)
    assert Path(value["launcher"]).resolve() == script.resolve()
    assert value["args"][:3] == ["--profile", "offline research", "exec"]
    assert value["args"][value["args"].index("-m") + 1] == "offline-model"
    assert 'model_reasoning_effort="xhigh"' in value["args"]
    assert value["path"] == "/usr/bin:/bin"


@pytest.mark.parametrize("operation", ["health_check", "complete"])
def test_npm_codex_reports_missing_node_before_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    script = tmp_path / "codex.js"
    script.write_text("#!/usr/bin/env node\n// Offline fixture\n")
    script.chmod(0o700)
    monkeypatch.setattr(
        "research_radar.analysis.cli_providers.shutil.which",
        lambda *args, **kwargs: None,
    )
    provider = CodexCliProvider(name="codex", command=str(script))
    with pytest.raises(AnalysisError, match="Node.js"):
        if operation == "health_check":
            provider.health_check()
        else:
            provider.complete([Message(role="user", content="offline")], model="offline")


def test_npm_runtime_search_does_not_include_arbitrary_ancestor_bin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = tmp_path / "project/tools/codex.js"
    script.parent.mkdir(parents=True)
    script.write_text("#!/usr/bin/env node\n// Offline fixture\n")
    script.chmod(0o700)
    unrelated_node = tmp_path / "bin/node"
    unrelated_node.parent.mkdir()
    unrelated_node.write_text("#!/bin/sh\nexit 0\n")
    unrelated_node.chmod(0o700)
    original_which = shutil.which

    def local_search(command: str, *, path: str | None = None) -> str | None:
        if path is None:
            return None
        directories = [part for part in path.split(":") if part.startswith(str(tmp_path))]
        return original_which(command, path=":".join(directories))

    monkeypatch.setattr("research_radar.analysis.cli_providers.shutil.which", local_search)
    with pytest.raises(AnalysisError, match="Node.js"):
        CodexCliProvider(name="codex", command=str(script)).health_check()
