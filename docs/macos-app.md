# macOS App Guide

[简体中文](macos-app.zh-CN.md) · [Project README](../README.md)

ResearchRadar lives in your Mac's menu bar. It finds papers, reads full texts, checks evidence,
and lets you read the report without using the terminal.
For your first run, **make one local report. Set up delivery and scheduling later.**

This is a development-only local beta for **macOS 26 on Apple Silicon (arm64)**.
A local test DMG has passed read-only packaging checks, not installation or launch acceptance.
The latest test image fixes the Python build-metadata path but retains development-data behavior;
see the [roadmap](todo.md). Existing installed/development Apps are not automatically replaced.
There is no notarized or approved public installer.
Final resource, keyboard, VoiceOver, and multi-display acceptance is still incomplete.
See the [roadmap](todo.md) for the remaining checks.

## 1. Open the App

If a maintainer has given you a built `ResearchRadar.app`, double-click it.
The App includes its Python engine; you do not need to install Python, `uv`, or Homebrew to run it.
Codex is separate: choosing it for verification requires an available executable and an existing
sign-in. The App does not bundle Codex.

If you are developing from source, switch to the branch containing the App and run these commands
from the repository root:

```bash
./script/stage_macos_app.sh
open dist/ResearchRadar.app
```

Building requires `uv`, Python 3.12+, Swift 6.3+, and the macOS 26 SDK.
The first build downloads dependencies and creates build files. Ordinary users do not run this
each time they open the App. The script runs Swift tests, packaging, and local checks; it does not
complete every Python, offline-workflow, or manual acceptance check.
If macOS blocks a development build, check its source and ask the maintainer to inspect signing.
Do not disable system security protections.

Look for the icon in the menu bar at the top of your screen:

- Left-click to open or close the panel below the icon.
- Right-click for the native menu, including running the selected topic, pausing schedules, and quitting.
- Use the upper-right control to switch between compact and expanded views.
  The expanded view includes Topics, Reports, Settings, and Diagnostics.
- Click outside the panel or press Escape to close it without cancelling research.
  If a confirmation dialog is open, deal with that first.

The App has its own settings. It does not automatically read the CLI's `config.yaml`.
Even if you already use the CLI, check the topic, providers, recipient, and schedule saved in the App.

## 2. Set Up Your First Topic

Setup has four steps, and you can go back to change your choices.
Closing the panel does not quit the App. Saved settings survive a restart; unsaved API keys are
not stored as form drafts.

### Step 1: Appearance and language

Choose System, Light, or Dark, and choose the interface language:
Follow System, Simplified Chinese, or English. You can change these later in **Settings > General**.

**Interface language and report language are separate.** Switching the interface to English does
not change an existing Chinese topic. A new topic starts with the report language matching the
current interface; you can choose Chinese or English independently before saving it.

### Step 2: Research services

| Service | What it does | What you need |
|---|---|---|
| DeepSeek | Drafts topics, summarizes sources, reads papers, and translates reports | A DeepSeek API key |
| Tavily | Searches the web to supplement paper discovery | A Tavily API key |
| Codex, the default verifier | Checks proposed public claims against their evidence | An executable, existing sign-in, and access to the selected model |

An API key is a credential issued for software to use. **It is not your account password.**
Each service uses its own account and allowance. Topic generation, connection checks, and research
may use credits or incur charges; check the relevant account. Keep keys out of chats, screenshots,
and Git.

1. Open the official key link in the DeepSeek section, obtain a key, paste it, and click
   **Save DeepSeek key**.
2. Do the same for Tavily with **Save Tavily key**. The default App setup needs both services.
3. Check that each says **Saved in Keychain**. An empty input after saving is normal;
   you do not need to enter the key for every report.
4. If Codex is detected, click **Use detected Codex installation**.
   An already valid saved path does not need to be selected again.
5. Otherwise, use **Advanced: executable file** to select the Codex executable.
   This means a program file, not a paper, project folder, or API key.
   The App does not install or sign in to Codex for you.

The default reader is DeepSeek `deepseek-flash`, with thinking explicitly enabled and
`reasoning_effort: high`. The default verifier is Codex `gpt-5.6-luna` with `xhigh` effort.
The App offers `high` and `xhigh`. These settings do not change your global Codex configuration
or guarantee that your account can use a particular model.

If Codex is unavailable, you can explicitly choose DeepSeek verification and confirm the warning.
The App does not switch automatically. That choice uses DeepSeek for both reading and verification,
rather than checking across two services.
Custom providers and advanced model routing remain available through the [CLI configuration](providers.md),
not through this version of the App.

Keep these states separate:

- **Saved:** the credential exists locally; the requesting program may still need permission to read it.
- **Program found / configuration complete:** local requirements are met; connectivity is not proven.
- **Connection check passed:** the listed checks succeeded at that time.
  This does not guarantee research quality, future connectivity, or delivery.

### Step 3: Create and review a topic

Describe what you want to follow. For example:

> Follow long-term memory for LLM agents, especially updates, forgetting, conflict handling, and
> evaluation. Exclude traditional hardware storage.

Choose the report language, then click **Generate topic draft**.
**This calls a model**; it is not an entirely local form action.
Review the name, research focus, and search scope. Expand the advanced section to edit queries,
concept groups, and exclusions. Read any quality warnings before saving.

The default full-text read limit is 2 papers. The final setup page shows the count;
this version has no UI control to edit it, and two useful reads are not guaranteed.
Later, use **Topics** to add, select, edit, or pause topics.
Changing the interface language does not rewrite saved topics.

### Step 4: Check and start

1. Review the topic, report language, full-text read count, and actual model routes.
2. Click **Test connections**. This sends model requests and one small search, which may use credits.
   It does not check WeChat or SMTP.
3. Resolve failures for the service shown. After changing a key, model, or effort, run the checks again.
4. Leave delivery and daily scheduling disabled for now, then click **Start first research**.

You can also choose **Finish without running** and use **Run Now** later.
Research needs network access. Time varies with discovery, full-text retrieval, models, and paper count.
Some settings are locked while work is active or queued; wait or cancel the task before changing them.

## 3. Read the Report

The overview separates the latest attempt from the last useful report.
Open **Reports**, select a report, and open its body.
Source, full-text read, and verified-claim counts belong to that report, not to a newer failed attempt.

| Result | What it means |
|---|---|
| A report with public deep-reading content | Ready to read and eligible for delivery |
| No eligible new candidates | This run found no eligible new papers to read; it does not mean Codex rejected every claim |
| Incomplete research or insufficient evidence | Open Diagnostics to distinguish search, retrieval, reading, and verification problems |

The read limit is not an output promise. Insufficient evidence does not lower the publication threshold,
and empty results are not automatically delivered.
If there is already a useful report today, **Run Now** selects it.
Use **Run Again** and confirm to start a new attempt. This is not a resume operation and may incur new charges.

Research continues when the panel closes. Use the task's cancel action to stop it.
Use the menu-bar right-click menu to quit. Quitting cancels current work and stops App scheduling;
it does not leave a hidden scheduler running.

## 4. Optional: WeChat Drafts and Private Email

Settings has two switches: **Create a WeChat draft after research** and **Send email after research**.
**Once enabled and saved, future manual research runs automatically queue delivery of eligible reports.
There is no additional confirmation for each automatic delivery.**
WeChat and email run as separate jobs. Scheduled research uses the channels captured when you save its schedule.

To read before sending, leave both switches off during research. Once a report exists, configure
and enable the channel you want, then use the report's delivery button and confirm.
Saving delivery settings alone does not send old reports.
To stop future automatic delivery, turn the channel off. If you have a daily schedule,
save that schedule again and check its channels too.

### Create a WeChat draft

1. In **Settings > WeChat draft**, enter your Official Account's `AppID`, `AppSecret`, and author,
   then click **Save WeChat settings**. You can save credentials without enabling automatic delivery.
2. Click **Choose cover…** to preview a PNG or JPEG, limited to 2 MiB and 40 megapixels.
   **Choosing does not upload it.** **Upload cover** requires confirmation and uploads it to the
   account's permanent material library. You can also enter an existing cover media ID.
3. Check the enabled channel and saved cover, then use **Create draft** in the report's WeChat section
   and confirm.
4. Review text and images in the official WeChat draft box before deciding whether to publish.

ResearchRadar **creates drafts only. It does not publish or mass-send.**
Uploading a cover does not create a draft.
The account needs the relevant API permissions. If WeChat reports an IP allowlist error,
check the outbound public IP in the response rather than assuming the account identity is wrong.
If upload succeeded but saving settings failed, use **Save uploaded cover** to retry local saving only.
For an unknown result, inspect the material library or draft box before retrying;
another request may create a duplicate.

### Send private email

In **Settings > Private email**, enter the SMTP host, port, username, app password,
sender, and one recipient. Click **Save email settings**.
**The current App form saves implicit TLS; it has no STARTTLS selector.**
The CLI supports more SMTP options. Do not copy a STARTTLS/587 example into this App form.

For a first Gmail test, send to yourself:

| Field | Value |
|---|---|
| SMTP host | `smtp.gmail.com` |
| Port | `465` |
| Username and sender | Your full Gmail address |
| App password | A 16-character Gmail App Password, not your regular account password |
| Recipient | Your own address for the first check |

Gmail App Passwords require Google's two-step verification setup.
If your account does not offer that option, check the provider's supported SMTP authorization
instead of repeatedly entering your regular password.
For another provider, use its implicit-TLS SMTP settings.

Click **Send email** on the report, review the sender and recipient, and confirm.
This sends the existing report without running research again.
The message includes HTML and plain text. Safe PNG/JPEG figures are embedded with CID attachments;
they do not depend on an online Archive.
This is one-to-one private delivery, not a subscription, bulk-mail, or marketing service.

Each channel keeps its own status. A failed email does not undo a report or a successful WeChat draft.
Sending again after success or an unknown outcome requires extra confirmation.
**Unknown does not mean failed.** Check the inbox or draft box first.
The App does not automatically resend an unknown delivery.

## 5. Optional: Daily Scheduling

1. Select the topic in Settings and open **Daily schedule**.
2. Choose a time, select **Enable for selected topic**, check delivery choices, and click **Save schedule**.
3. Check that neither **Pause all schedules** nor the topic's pause switch is enabled.
   Saving a schedule does not clear a global pause.
4. If you want the App to start when you sign in to your Mac, explicitly enable **Start at Login**
   and confirm approval in System Settings. The App switch records your preference; it does not prove
   that macOS has approved the login item.

Daily times use the Mac's current calendar and time zone. The App must remain running;
closing its panel is fine. **Quitting stops scheduling.**
App scheduling does not install a persistent helper or launchd job.
This development version still has a report-date bug with non-Gregorian system calendars.
Check dates before relying on unattended scheduling with such a setting.
The CLI's launchd scheduler is separate. Resolve detected legacy conflicts first;
the App does not delete those jobs for you.

After sleep or a period when the App was not running, only today's unattempted task is considered.
Earlier days are skipped. If yesterday was missed and you open the App at 08:00 for a 09:00 schedule,
it waits for 09:00 today.
Failed or cancelled attempts do not loop automatically; fix the problem and retry manually.
If scheduling stopped after an error, use **Recheck and resume** in Settings.
Failed recovery validation keeps it stopped rather than bypassing damaged state.

## 6. Why Keychain May Ask Again

Entering an API key saves a credential. macOS **Allow / Always Allow** authorizes a particular
program to read a particular Keychain item.
The password requested is usually your local Keychain password, not the DeepSeek API key.

Different items or requesting programs may need separate approvals.
Several prompts during one run do not necessarily mean the same key is being saved repeatedly.
They also do not prove everything is normal: record the requesting program and item name if something
looks wrong, but never record the password.

You do not need to re-enter a saved API key for every report.
A cleared input and a saved indicator do not mean access has been authorized.
Use **Always Allow** only after confirming both the requester and the item belong to trusted ResearchRadar
components. Do not allow all applications, save keys in plaintext, or change Keychain ACLs to silence prompts.

**Local self-signing has not solved authorization across updates.**
A rebuilt development App may ask again even after Always Allow.
Do not expect every future build to retain permission.
See the [Keychain authorization notes](usage.md#macos-app-keychain-authorization).

## 7. Troubleshooting

In **Diagnostics**, click **Copy redacted diagnostics** and describe your action,
the visible error, and whether delivery actually arrived.
Copying uses existing state; it does not run checks, read key values, or resend.
Inspect screenshots before sharing them for email addresses, keys, private paths, or unpublished reports.

- **Missing configuration:** check saved credentials, the Codex executable, and the selected verifier.
  Finding a program does not prove it is signed in.
- **Selecting Codex:** choose the executable file itself, not a command with arguments.
  Paths containing spaces or Chinese characters are supported; do not add quotation marks yourself.
  CLI configuration still supports [commands with arguments](providers.md#cli-agent-providers).
- **Connection check failed:** check the named service's credentials, access, quota, and network.
  You do not need to re-enter every provider's key.
- **Research stopped:** use the latest attempt's time, stage, and reason, not statistics from an older report.
- **Zero reads or accepted claims:** distinguish no candidates, insufficient full text, reader failure,
  and actual verifier rejection before blaming Codex.
- **Unknown delivery:** inspect the inbox or WeChat account before clicking retry.
- **Disabled settings:** active or pending jobs block changes that affect behavior.
  Wait for completion or cancel the task.
- **Damaged saved state:** retain files and diagnostics and ask the maintainer for help.
  Do not delete the whole data directory to reset it.

Report completion and failure notifications are off by default.
Enable them in **Settings > General** to request macOS permission.
They cover newly completed useful reports and failed research, not empty results,
cancellations, or channel-only delivery. Clicking opens the report or Diagnostics.
A notification failure does not change the research result.

## 8. Local Data and Current Limits

The default development build stores data under `~/Library/Application Support/ResearchRadar-Dev/`:

- `config/app-config.json`: App settings, topics, and delivery configuration, without secret values.
- `state/`: queue, report index, schedules, and interface state.
- `workspace/runs/`: reports, images, and research artifacts.
- `workspace/cache/model_calls/`: rebuildable model cache.
- `jobs/`: job records and diagnostics.

This directory is not disposable cache. Do not reuse it as a CLI `--root`.
You can explicitly import source-history JSONL from an old CLI data folder in Settings;
reports, settings, cache, and secrets are not imported automatically.

Use **Settings > Storage** to inspect usage, set an optional model-cache limit, or confirm cache cleanup.
The limit is off by default. Automatic size checks currently run after new cache writes.
After lowering the limit, an all-cache-hit workload may remain above it.
Manual cleanup affects only the App's model cache, not reports or source history.
Reports and ordinary artifacts are local plaintext files. Protect them with system disk encryption
and account permissions; the App is not an encrypted document vault.

Archive/RSS and Zhihu export remain available through the [CLI guide](usage.md).
There are no App pages for those channels. A true multi-run weekly report is outside this version.
The local test DMG is not a notarized release, and final acceptance is still incomplete.
A development build is not a release.

To uninstall, quit first and move the chosen `.app` to Trash.
Reports, App data, and Keychain items remain by default.
Back them up and confirm each item before any separate cleanup; do not bulk-delete unfamiliar paths.
