# Box Agent

Drag a box over **anything** on your Windows PC. An AI looks at what's inside the box, works out what to do, and then **clicks, types, presses keys and scrolls inside that box on its own** until the task is done.

Powered by any vision + tool-calling model on [OpenRouter](https://openrouter.ai) (default: `anthropic/claude-haiku-5.5`). Updates itself from this repo's GitHub Releases.

## Install

1. Download `BoxAgent.exe` from the [latest release](https://github.com/Solslfy/box-agent/releases/latest).
2. Run it. Windows SmartScreen may warn because the exe isn't code-signed: choose **More info → Run anyway**.
3. Paste your OpenRouter API key into the settings window. It's stored in Windows Credential Manager, not in a file.

The app lives in the system tray. After its first run it adds itself to the Start Menu, so you can
open it again by typing **Box Agent** in Windows search. Put the exe somewhere permanent before
running it (if you move it, run it once from the new place and the shortcut follows).

## Use

| Action | How |
|---|---|
| Select a box | `Ctrl+Shift+Space`, then drag. `Esc` cancels. |
| Give a task | Type it in the bar under the box and press Enter. Leave it empty and press Enter to mean "figure out what this needs and do it". |
| Stop immediately | `Ctrl+Shift+X`, the **Stop** button, or slam the mouse into any screen corner. |
| See progress / answer | The side panel next to the box shows every step and the final answer (with a Copy button). |

## Safety

The AI runs **fully automatically**, so it's fenced in:

- It can only click, drag and scroll **inside the box you drew**. Anything outside the box is refused.
- Window-escaping keys are blocked: `Win`, `Alt+Tab`, `Alt+F4`, `Alt+Esc`, `Alt+Space`, `Ctrl+Esc`, `Ctrl+W`, `Ctrl+F4`, `Ctrl+Q`, `Ctrl+Alt+Del`, `Ctrl+Shift+Esc`.
- It stops after 25 steps by default, which you can change in Settings.
- **Dry run** (Settings) shows what it would do, with red crosshairs, without touching anything.

## Limits

- Some games ignore simulated mouse/keyboard input.
- Windows doesn't let a normal app control windows running **as Administrator**.
- Click accuracy depends on the model. If Haiku misses, try `anthropic/claude-sonnet-5.5` in Settings.
- Each step sends a screenshot of the box to OpenRouter, so the cost per task depends on the model and the number of steps.

Settings live in `%APPDATA%\BoxAgent\settings.json` and the log in `%APPDATA%\BoxAgent\log.txt`.

## Develop

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e .[dev]
.venv\Scripts\python -m pytest
.venv\Scripts\python -m box_agent
```

## Release

Bump nothing by hand. Just tag:

```powershell
git tag v0.1.1
git push origin v0.1.1
```

GitHub Actions stamps the version, runs the tests, builds `BoxAgent.exe` plus a SHA-256 checksum, and publishes the release. Running copies see "Update to v0.1.1" in the panel. One click downloads it, verifies the checksum, swaps the exe and restarts.
