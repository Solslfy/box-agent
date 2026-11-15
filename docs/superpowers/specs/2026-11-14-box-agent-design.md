# Box Agent — Design Spec

Date: 2026-11-14
Repo: https://github.com/Solslfy/box-agent (public)

## 1. Goal

A Windows desktop app. You press a hotkey, drag a box over **anything on screen**
(any app, game, browser, document), optionally type a task, and an AI model:

- sees what is inside the box,
- works out the problem (answer a question, solve a puzzle, fill a form, etc.),
- **acts on its own** inside the box — clicks, double-clicks, types, presses keys,
  scrolls — repeating until the task is done,
- reports what it did and any final answer.

The app updates itself from GitHub Releases.

### Decisions made with the user
| Topic | Decision |
|---|---|
| Scope | Any app on the PC (not browser-only) |
| Autonomy | Fully automatic — no per-action approval |
| AI provider | OpenRouter API key (user picks the model) |
| Stack | Python 3.13 + PySide6, packaged as a single `.exe` with PyInstaller |
| Updates | Auto-update from GitHub Releases of a public repo |

### Non-goals (v1)
- macOS / Linux.
- Acting outside the drawn box.
- Multiple boxes at once, scheduled/recurring runs, voice input.
- Code signing of the `.exe` (Windows SmartScreen may warn on first run).

## 2. User flow

1. App runs in the system tray. First launch opens **Settings** to enter the
   OpenRouter API key.
2. `Ctrl+Shift+Space` → a full-screen dimmed overlay appears on all monitors.
   Drag a rectangle; `Esc` cancels.
3. A small **prompt bar** appears under the box: type a task, or press `Enter`
   with it empty to mean *"Look at this and do whatever it obviously needs
   (solve it / answer it / complete it)."*
4. The overlay disappears, leaving a thin **click-through colored outline**
   around the box (so the user sees the agent's area without it blocking clicks).
5. The **side panel** (docked beside the box, never inside it) streams each step:
   thought → action → result. When the model calls `done`, the panel shows the
   final answer with a Copy button.
6. Run ends on `done`, on hitting the step limit (default 25), on error, or when
   the user presses the **panic hotkey `Ctrl+Shift+X`** (also: slamming the mouse
   into any screen corner, via the failsafe).

## 3. Architecture

Package `box_agent/`, one responsibility per module:

| Module | Responsibility | Depends on |
|---|---|---|
| `app.py` | Entry point: Qt app, tray icon, hotkey registration, wires modules | all |
| `overlay.py` | Box-selection overlay, prompt bar, click-through outline window | PySide6 |
| `capture.py` | `grab(box) -> PNG bytes + scale` using `mss`; DPI-aware, multi-monitor | mss, Pillow |
| `geometry.py` | `Box` dataclass; image↔screen coordinate mapping; bounds checks (pure, no I/O) | — |
| `actions.py` | Execute a validated action with `pynput` (mouse + Unicode keyboard) | pynput, geometry |
| `llm.py` | OpenRouter chat-completions client (OpenAI-compatible, tools + images) | httpx |
| `agent.py` | The loop: capture → LLM → validate tool call → act → repeat; emits events | capture, llm, actions |
| `panel.py` | Live step log + final answer + "Update ready" banner | PySide6 |
| `settings.py` | Load/save settings JSON; API key in Windows Credential Manager | keyring |
| `updater.py` | Check latest GitHub release, download, swap exe, restart | httpx |
| `version.py` | `__version__ = "x.y.z"` (CI writes it from the git tag) | — |

The agent loop runs on a worker `QThread`; it communicates with the UI only
through Qt signals (`step`, `finished`, `failed`). A shared `threading.Event`
is the stop flag set by the panic hotkey and checked before every action.

Process is set **per-monitor DPI aware** at startup (`SetProcessDpiAwareness(2)`)
so screen coordinates, `mss` pixels and `pynput` coordinates all agree.

## 4. The agent loop

```
messages = [system_prompt, user(task + first screenshot)]
for step in 1..max_steps:
    if stop_flag: end("Stopped by user")
    reply = llm.chat(messages, tools=TOOLS)          # one tool call expected
    call  = parse_and_validate(reply)                 # see 4.2
    if invalid: append error tool-result; continue    # counts as a step
    if call is done: end(answer)
    actions.run(call, box)
    sleep(settle_delay)                               # default 0.6 s
    append tool-result + new screenshot of the box
end("Step limit reached")
```

### 4.1 Screenshots and coordinates
- Each screenshot is the box only. If its long edge exceeds **1280 px** it is
  downscaled (keeping aspect ratio); the scale factor is remembered.
- The model is told the image size and that `(0,0)` is the top-left of the image.
- `geometry.to_screen(x, y, box, scale)` maps image coords → absolute screen coords.
- Any coordinate outside `[0,w) × [0,h)` is **rejected** (not clamped) and the
  model is told so.
- To limit tokens, only the **latest 3 screenshots** stay in the history; older
  ones are replaced with the text `"[earlier screenshot removed]"`.

### 4.2 Tools (OpenAI function-calling format)
| Tool | Args | Effect |
|---|---|---|
| `click` | `x, y, button?=left` | single click |
| `double_click` | `x, y` | double click |
| `drag` | `x1, y1, x2, y2` | press-move-release, both points inside box |
| `type` | `text` | types Unicode text at current focus |
| `key` | `combo` e.g. `"enter"`, `"ctrl+a"` | key press/combination (allow-listed key names) |
| `scroll` | `x, y, dy` | wheel scroll at a point (`dy` ±1..10 notches) |
| `wait` | `seconds` (0.2–5) | pause for loading |
| `done` | `answer` | finish; `answer` shown in panel |

Every reply must contain exactly one tool call. A reply with plain text and no
tool call is treated as invalid and the model is reminded to call a tool.
A reply with several tool calls executes only the first.

Blocked key combos (to keep the agent inside its box): `win`, `alt+tab`,
`alt+f4`, `ctrl+alt+del`, `ctrl+w`, `ctrl+shift+esc`. Rejected with a message.

### 4.3 System prompt (summary)
"You control the mouse and keyboard, restricted to the screenshot you see.
Achieve the user's task. Click a field before typing into it. After each action
you get a new screenshot — verify the result before moving on. When finished,
or if the task is impossible, call `done` with a short answer/explanation.
If the task is only a question, answer it via `done` without acting."

## 5. OpenRouter client
- `POST https://openrouter.ai/api/v1/chat/completions`, headers
  `Authorization: Bearer <key>`, `X-Title: Box Agent`.
- Images sent as `{"type":"image_url","image_url":{"url":"data:image/png;base64,..."}}`.
- `tools` + `tool_choice: "required"`.
- Default model is a setting; ships with a vision + tool-calling capable model
  (exact OpenRouter model id chosen and verified against OpenRouter's model list
  during implementation). Settings shows a free-text model id field.
- Timeout 60 s. On network error or HTTP 5xx/429: retry once after 2 s, then fail
  the run with the error shown in the panel. HTTP 401 → open Settings.

## 6. Settings
`%APPDATA%\BoxAgent\settings.json`:
```json
{ "model": "...", "max_steps": 25, "settle_delay": 0.6,
  "hotkey_select": "ctrl+shift+space", "hotkey_stop": "ctrl+shift+x",
  "dry_run": false, "check_updates": true }
```
API key stored with `keyring` (Windows Credential Manager), never in the JSON.

**Dry run**: actions are logged to the panel and drawn as markers on the
outline but not executed. Used for safe testing.

## 7. Auto-update
- **Release pipeline** (`.github/workflows/release.yml`): on push of tag `v*`,
  a `windows-latest` runner writes the version into `version.py`, runs tests,
  builds `BoxAgent.exe` with PyInstaller (`--onefile --windowed`), and creates a
  GitHub Release with the exe attached.
- **Check**: on startup (if `check_updates`) and every 6 h, GET
  `https://api.github.com/repos/Solslfy/box-agent/releases/latest`; compare tag
  to `__version__` (semantic versioning). If newer, the panel/tray shows
  "Update to vX.Y.Z".
- **Apply** (on user click, never mid-run): download the `BoxAgent.exe` asset to
  `%TEMP%`, write a small `.cmd` that waits for the current PID to exit, replaces
  the running exe, and relaunches it; then the app quits.
- Running from source (not frozen) → update checks still show availability but
  "apply" just opens the release page.
- Any update failure is shown once and ignored; it never blocks the app.

## 8. Error handling summary
| Situation | Behaviour |
|---|---|
| No / bad API key | Open Settings with message |
| LLM network / 5xx / 429 | Retry once, then stop run with error |
| Invalid / out-of-box tool call | Error returned to model; counts as a step |
| Panic hotkey / corner failsafe | Stop before next action; release held keys/buttons |
| Box spans monitors with different DPI | Allowed; mapping uses absolute virtual-desktop coords |
| Update failure | Notify once, continue running |

## 9. Testing
- **Unit (pytest)**: `geometry` mapping/scaling/bounds; tool-call parsing and
  validation (good, malformed, out-of-box, blocked keys, multiple calls);
  history pruning to 3 screenshots; semver comparison and release JSON parsing
  in `updater`; settings load/save defaults.
- **Agent loop** with a fake LLM and fake actions (scripted tool calls) to test
  stop flag, step limit, retry, `done`.
- **Manual checklist**: Notepad (type a sentence), a browser form, a calculator
  (solve "12×34" by clicking), panic hotkey mid-run, multi-monitor box, an
  update from v0.1.0 → v0.1.1 via a real tagged release.

## 10. Repo layout
```
box-agent/
  box_agent/  (modules above)
  tests/
  assets/icon.ico
  .github/workflows/release.yml
  pyproject.toml   (deps: PySide6, mss, Pillow, pynput, httpx, keyring; dev: pytest, pyinstaller)
  README.md
  docs/superpowers/specs/2026-11-14-box-agent-design.md
```

## 11. Risks
- **Fully automatic control of a real PC**: mitigated by box confinement, blocked
  combos, step limit, panic hotkey, corner failsafe, dry-run mode.
- **Model click accuracy** varies by OpenRouter model; the model setting lets
  the user switch. Screenshot downscaling trades accuracy for cost.
- **Some games/apps ignore synthetic input** or run elevated (input to admin
  windows from a non-admin app is blocked by Windows). Documented in README.
- **Unsigned exe** may trigger SmartScreen; documented.
