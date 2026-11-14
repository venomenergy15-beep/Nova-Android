# NOVA for Windows 7

A Windows desktop twin of the NOVA Android app — the same personal AI
assistant, built to keep old hardware useful.

## What it is

NOVA for Windows is a small chat app (Python, standard library only) that
talks to the same OpenAI-compatible `/chat/completions` endpoint as the
Android app. It runs on 32-bit Windows 7 Starter: no modern frameworks, no
bundled web view, no third-party packages.

## What it does (same as Android)

- Chat with your AI provider. Enter an OpenAI-compatible base URL, model
  name, and API key in **Settings** (model defaults to `gpt-4o-mini`).
  NOVA appends `/chat/completions` to the base URL.
- Non-streaming replies, 60-second timeout, last 12 messages of history.
- System prompt includes your saved memories when relevant.
- `remember: ...` in chat saves a fact to on-device memory.
  `forget all memories` erases it. Memories are listed in Settings.
- Offline-mode toggle (same placeholder as Android: no local model is
  bundled yet).
- Settings and memories are stored in `%APPDATA%\NOVA\nova_settings.json`
  on your computer. Your API key is stored there in plain text — do not
  share a copy of the app containing your key.

## What it does NOT do

- **No voice input.** The Android app uses Android's speech recogniser.
  On Windows 7 that would need SAPI/COM; this build leaves it out.
- **No spoken replies.** Android reads replies aloud with its
  text-to-speech engine; this build does not.
- No bundled offline model, web search, or file/image tools — same as the
  Android starter.

## Run it without building

Needs Python 3.8 or newer (3.8 is the last version that runs on Windows 7).
No packages to install — the app uses only the standard library.

```
python nova_windows.py
```

## Build the .exe

The GitHub Actions job `build-windows` in `.github/workflows/build-apk.yml`
does this in the cloud; no Windows PC is needed:

1. Sets up Python 3.8 (32-bit) on a Windows runner.
2. Installs PyInstaller 5.13.2 — the last PyInstaller whose bootloader
   runs on Windows 7 (PyInstaller 6 dropped Windows 7).
3. Builds a single-file, windowed exe:
   `pyinstaller --onefile --windowed --name NOVA-Windows-7 windows/nova_windows.py`
4. Uploads the exe as the artifact `NOVA-windows-exe`
   (`dist/NOVA-Windows-7.exe`, kept 14 days).

Download the artifact, extract it, and run `NOVA-Windows-7.exe` on the
Windows 7 machine. No install step: first run creates
`%APPDATA%\NOVA\nova_settings.json`. Open Settings in the app and enter
your provider base URL, model, and API key.

## First run on Windows 7 Starter

- The machine needs internet access to reach your AI provider.
- Windows may show a SmartScreen prompt for an unsigned exe from the
  internet; choose "Run anyway" if you trust the file you built.
- If the app does not start, check that the exe is the 32-bit build
  (`NOVA-Windows-7.exe` from the `NOVA-windows-exe` artifact).
