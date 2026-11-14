#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NOVA for Windows 7 — desktop twin of the NOVA Android app.

Pure Python standard library only (tkinter, urllib, json, os, threading).
No third-party packages, so it builds cleanly with PyInstaller and runs on
32-bit Windows 7 Starter under Python 3.8.

Behaviour mirrors app/src/main/java/com/nova/assistant/MainActivity.kt:
  * Chat with an OpenAI-compatible /chat/completions endpoint.
  * Settings: base URL, model (default gpt-4o-mini), API key (default empty).
  * Non-streaming request, 60 s timeout, last 12 messages of history.
  * System prompt includes user-approved memories when relevant.
  * "remember: ..." saves a fact locally; "forget all memories" erases them.
  * Offline-mode toggle (local model not installed yet, same as Android).
  * Voice input and spoken replies are NOT included in this version.
    They need Android's speech recogniser / text-to-speech; on Windows 7
    that would need SAPI/COM, which this build deliberately avoids.

Run:  python nova_windows.py        (Python 3.8 or newer)
EXE:  built by the GitHub Actions "build-windows" job with PyInstaller.
"""

import json
import os
import sys
import threading
import urllib.error
import urllib.request

try:
    import tkinter as tk
except ImportError:  # tkinter ships with standard Python; keep logic testable
    tk = None

# ---------------------------------------------------------------------------
# Constants (mirror the Android app)
# ---------------------------------------------------------------------------

APP_NAME = "NOVA"
SETTINGS_FILENAME = "nova_settings.json"
DEFAULT_MODEL = "gpt-4o-mini"
REQUEST_TIMEOUT = 60  # seconds, same as OkHttp callTimeout(60) on Android
HISTORY_LIMIT = 12    # messages.takeLast(12) on Android

SYSTEM_PROMPT_BASE = (
    "You are NOVA, the user's personal assistant. Be helpful, honest, "
    "capable, and clear about limitations. Use the following user-approved "
    "memories only when relevant. Do not claim to learn or remember anything "
    "unless it is saved by the app. "
)

GREETING_LINES = [
    "Hello. I'm NOVA, your personal AI assistant.",
    "My interface and voice features are ready. Connect an AI provider in "
    "Settings to enable online answers.",
]

NOT_CONFIGURED_REPLY = (
    "Please configure an OpenAI-compatible API endpoint and model in "
    "Settings. Until then, NOVA can store local notes but cannot generate "
    "cloud AI responses."
)
OFFLINE_REPLY = (
    "Offline mode is selected, but a local language model is not installed "
    "yet. Saved memories remain available on this device; offline reasoning "
    "is the next integration milestone."
)
MEMORY_SAVED_REPLY = (
    "Saved to NOVA's private on-device memory. You can review or erase it "
    "in Settings."
)
MEMORY_CLEARED_REPLY = "All saved NOVA memories have been cleared from this app."

# Colours (same palette as the Android app)
NIGHT = "#070B16"
PANEL = "#111A2B"
CYAN = "#54E6FF"
VIOLET = "#9B7CFF"
USER_BG = "#173C55"
TEXT = "#FFFFFF"
MUTED = "#9EACC4"
PLACEHOLDER = "#71819C"
DIVIDER = "#33435C"
DANGER = "#FF8A9A"
CORE_BG = "#132B45"


# ---------------------------------------------------------------------------
# Settings (persisted as JSON; Android uses SharedPreferences "nova_settings")
# ---------------------------------------------------------------------------

def settings_path():
    """Where settings live. %APPDATA%\\NOVA on Windows; overridable for tests."""
    override = os.environ.get("NOVA_SETTINGS_DIR")
    if override:
        return os.path.join(override, SETTINGS_FILENAME)
    appdata = os.environ.get("APPDATA")
    if appdata:
        return os.path.join(appdata, "NOVA", SETTINGS_FILENAME)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(
        os.path.expanduser("~"), ".config"
    )
    return os.path.join(base, "NOVA", SETTINGS_FILENAME)


def load_settings():
    try:
        with open(settings_path(), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    return {
        "endpoint": data.get("endpoint", "") or "",
        "api_key": data.get("api_key", "") or "",
        # Android only defaults the model when no value was ever stored;
        # a stored empty string stays empty so the "not configured" check fires.
        "model": data["model"] if "model" in data else DEFAULT_MODEL,
        "memories": list(data.get("memories", []) or []),
    }


def save_settings(settings):
    path = settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(
            {
                "endpoint": settings.get("endpoint", ""),
                "api_key": settings.get("api_key", ""),
                "model": settings.get("model", DEFAULT_MODEL),
                "memories": list(settings.get("memories", [])),
            },
            handle,
            indent=2,
        )
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# Pure chat logic (no GUI dependency — unit-testable)
# ---------------------------------------------------------------------------

def build_system_prompt(memories):
    """System prompt; memories are appended exactly like the Android app."""
    prompt = SYSTEM_PROMPT_BASE
    if memories:
        memory_text = "\n".join("- " + item for item in memories)
        prompt += "\nUser-approved memory:\n" + memory_text
    return prompt


def build_request_payload(model, history, memories):
    """history is a list of (text, from_user); only the last 12 are sent."""
    messages = [{"role": "system", "content": build_system_prompt(memories)}]
    for text, from_user in history[-HISTORY_LIMIT:]:
        messages.append(
            {"role": "user" if from_user else "assistant", "content": text}
        )
    return {"model": model, "messages": messages}


def local_command(prompt, memories, offline_mode):
    """Handle commands that never reach the provider.

    Returns (handled, reply, status). reply is None when the command is
    handled silently (a blank "remember:" — same as Android).
    """
    lowered = prompt.lower()
    if lowered.startswith("remember:"):
        fact = prompt.split(":", 1)[1].strip()
        if fact:
            memories.append(fact)
            return True, MEMORY_SAVED_REPLY, "Memory updated locally"
        return True, None, None
    if lowered == "forget all memories":
        memories.clear()
        return True, MEMORY_CLEARED_REPLY, "Local memory cleared"
    if offline_mode:
        return True, OFFLINE_REPLY, "Offline \u2022 local model not connected"
    return False, None, None


def send_chat(endpoint, api_key, model, history, memories, timeout=REQUEST_TIMEOUT):
    """One non-streaming /chat/completions call. Returns the assistant reply,
    or a "Connection error: ..." string, exactly like the Android app."""
    url = endpoint.rstrip("/") + "/chat/completions"
    payload = build_request_payload(model, history, memories)
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        try:
            raw = err.read().decode("utf-8", "replace")
        except Exception:
            raw = ""
        return "Connection error: Provider returned HTTP %s: %s" % (
            err.code,
            raw[:300],
        )
    except Exception as err:  # URLError, timeout, etc. — same as OkHttp throwing
        return "Connection error: %s" % (err,)
    try:
        parsed = json.loads(raw)
        return parsed["choices"][0]["message"]["content"]
    except Exception as err:
        return "Connection error: %s" % (err,)


# ---------------------------------------------------------------------------
# GUI (tkinter; only constructed from main(), so the logic above stays
# importable and testable on a headless machine)
# ---------------------------------------------------------------------------

class NovaApp(object):
    def __init__(self, root, settings):
        self.root = root
        self.settings = settings
        self.messages = []  # list of (text, from_user)
        self.busy = False
        self.offline = tk.BooleanVar(value=False)

        root.title("NOVA \u2014 Personal Intelligence")
        root.geometry("480x720")
        root.minsize(360, 520)
        root.configure(bg=NIGHT)

        # Header
        header = tk.Frame(root, bg=NIGHT)
        header.pack(fill="x", padx=14, pady=(10, 4))
        title = tk.Label(header, text="N O V A", fg=CYAN, bg=NIGHT,
                         font=("Segoe UI", 20, "bold"))
        title.pack(side="left")
        tk.Label(header, text="PERSONAL INTELLIGENCE", fg=MUTED, bg=NIGHT,
                 font=("Segoe UI", 8)).pack(side="left", padx=(10, 0), pady=(10, 0))
        tk.Button(header, text="Settings", fg=CYAN, bg=PANEL,
                  activeforeground=CYAN, activebackground=PANEL,
                  relief="flat", font=("Segoe UI", 10, "bold"),
                  command=self.open_settings).pack(side="right")

        # Core panel: mode + status, mirroring the Android "NOVA CORE" card
        core = tk.Frame(root, bg=CORE_BG, padx=18, pady=12)
        core.pack(fill="x", padx=14, pady=(4, 8))
        self.mode_label = tk.Label(core, text="NOVA CORE", fg=CYAN, bg=CORE_BG,
                                   font=("Segoe UI", 11, "bold"))
        self.mode_label.pack()
        self.status_var = tk.StringVar(value="Ready \u2022 Local interface")
        tk.Label(core, textvariable=self.status_var, fg=MUTED, bg=CORE_BG,
                 font=("Segoe UI", 10)).pack()

        # Conversation header row + offline toggle
        conv_head = tk.Frame(root, bg=NIGHT)
        conv_head.pack(fill="x", padx=14)
        tk.Label(conv_head, text="CONVERSATION", fg=MUTED, bg=NIGHT,
                 font=("Segoe UI", 9, "bold")).pack(side="left")
        tk.Checkbutton(conv_head, text="Offline mode", variable=self.offline,
                       fg=MUTED, bg=NIGHT, selectcolor=PANEL,
                       activeforeground=CYAN, activebackground=NIGHT,
                       font=("Segoe UI", 9),
                       command=self._on_offline_toggle).pack(side="right")

        # Chat log
        chat_frame = tk.Frame(root, bg=NIGHT)
        chat_frame.pack(fill="both", expand=True, padx=14, pady=(6, 8))
        scrollbar = tk.Scrollbar(chat_frame)
        scrollbar.pack(side="right", fill="y")
        self.chat = tk.Text(chat_frame, bg=NIGHT, fg=TEXT, wrap="word",
                            state="disabled", relief="flat", padx=6, pady=6,
                            font=("Segoe UI", 11), yscrollcommand=scrollbar.set,
                            spacing1=6, spacing3=6)
        self.chat.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.chat.yview)
        self.chat.tag_config("user", justify="right", background=USER_BG,
                             foreground=TEXT, lmargin1=60, lmargin2=60,
                             rmargin=4, spacing1=8, spacing3=8)
        self.chat.tag_config("nova", justify="left", background=PANEL,
                             foreground=TEXT, lmargin1=4, lmargin2=4,
                             rmargin=60, spacing1=8, spacing3=8)

        # Input row
        input_row = tk.Frame(root, bg=PANEL, padx=8, pady=6)
        input_row.pack(fill="x", padx=14, pady=(0, 12))
        self.input_var = tk.StringVar()
        self.entry = tk.Entry(input_row, textvariable=self.input_var,
                              bg=PANEL, fg=TEXT, insertbackground=CYAN,
                              relief="flat", font=("Segoe UI", 11))
        self.entry.pack(side="left", fill="x", expand=True, padx=(4, 8))
        self.entry.bind("<Return>", lambda _event: self.send())
        self.entry.focus_set()
        self.send_btn = tk.Button(input_row, text="Send", fg=CYAN, bg=PANEL,
                                  activeforeground=CYAN,
                                  activebackground=PANEL, relief="flat",
                                  font=("Segoe UI", 11, "bold"),
                                  command=self.send)
        self.send_btn.pack(side="right")

        for line in GREETING_LINES:
            self._append("nova", line)

    # -- chat helpers -------------------------------------------------------
    def _append(self, who, text):
        self.messages.append((text, who == "user"))
        self.chat.configure(state="normal")
        self.chat.insert("end", text + "\n", who)
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def _set_status(self, text):
        self.status_var.set(text)

    def _on_offline_toggle(self):
        self.mode_label.config(
            text="LOCAL MODE" if self.offline.get() else "NOVA CORE")

    # -- sending ------------------------------------------------------------
    def send(self):
        prompt = self.input_var.get().strip()
        if not prompt or self.busy:
            return
        self.input_var.set("")
        self._append("user", prompt)

        handled, reply, status = local_command(
            prompt, self.settings["memories"], self.offline.get()
        )
        if handled:
            if reply is not None:
                self._append("nova", reply)
            if status:
                self._set_status(status)
            save_settings(self.settings)  # remember:/forget persist immediately
            return

        if not self.settings["endpoint"].strip() or not self.settings["model"].strip():
            self._append("nova", NOT_CONFIGURED_REPLY)
            self._set_status("Online provider not configured")
            return

        self.busy = True
        self.send_btn.config(state="disabled")
        self._set_status("Connecting to your AI provider\u2026")
        history = list(self.messages)
        thread = threading.Thread(target=self._do_request, args=(history,),
                                  daemon=True)
        thread.start()

    def _do_request(self, history):
        reply = send_chat(
            self.settings["endpoint"], self.settings["api_key"],
            self.settings["model"], history, self.settings["memories"],
        )
        self.root.after(0, self._on_reply, reply)

    def _on_reply(self, reply):
        self._append("nova", reply)
        if reply.startswith("Connection error:"):
            self._set_status("Provider connection failed")
        else:
            self._set_status("Online \u2022 response received")
        self.busy = False
        self.send_btn.config(state="normal")

    # -- settings dialog ------------------------------------------------------
    def open_settings(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("NOVA \u2022 Provider settings")
        dialog.configure(bg=PANEL)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)

        body = tk.Frame(dialog, bg=PANEL, padx=18, pady=14)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="OpenAI-compatible endpoint", fg=MUTED, bg=PANEL,
                 font=("Segoe UI", 9)).pack(anchor="w")
        endpoint_var = tk.StringVar(value=self.settings["endpoint"])
        tk.Entry(body, textvariable=endpoint_var, width=52, bg=NIGHT, fg=TEXT,
                 insertbackground=CYAN, font=("Segoe UI", 10)).pack(
                     anchor="w", pady=(2, 8))
        tk.Label(body, text="Model name", fg=MUTED, bg=PANEL,
                 font=("Segoe UI", 9)).pack(anchor="w")
        model_var = tk.StringVar(value=self.settings["model"])
        tk.Entry(body, textvariable=model_var, width=52, bg=NIGHT, fg=TEXT,
                 insertbackground=CYAN, font=("Segoe UI", 10)).pack(
                     anchor="w", pady=(2, 8))
        tk.Label(body, text="API key (stored on this computer)", fg=MUTED,
                 bg=PANEL, font=("Segoe UI", 9)).pack(anchor="w")
        key_var = tk.StringVar(value=self.settings["api_key"])
        key_entry = tk.Entry(body, textvariable=key_var, width=52, bg=NIGHT,
                             fg=TEXT, insertbackground=CYAN, show="\u2022",
                             font=("Segoe UI", 10))
        key_entry.pack(anchor="w", pady=(2, 2))
        show_key = tk.BooleanVar(value=False)

        def _toggle_show():
            key_entry.config(show="" if show_key.get() else "\u2022")

        tk.Checkbutton(body, text="Show API key", variable=show_key,
                       fg=MUTED, bg=PANEL, selectcolor=NIGHT,
                       activeforeground=CYAN, activebackground=PANEL,
                       font=("Segoe UI", 9),
                       command=_toggle_show).pack(anchor="w", pady=(0, 8))

        tk.Label(body, text="LEARNING & MEMORY", fg=CYAN, bg=PANEL,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(4, 4))
        memories = self.settings["memories"]
        tk.Label(body, text="Saved memories (%d)" % len(memories), fg=TEXT,
                 bg=PANEL, font=("Segoe UI", 10)).pack(anchor="w")
        if not memories:
            tk.Label(body, text="No saved memories yet. In chat, type: "
                     "remember: your preference or fact",
                     fg=MUTED, bg=PANEL, font=("Segoe UI", 9),
                     wraplength=380, justify="left").pack(anchor="w")
        else:
            for item in memories[-5:]:
                tk.Label(body, text="\u2022 " + item, fg=MUTED, bg=PANEL,
                         font=("Segoe UI", 9), wraplength=380,
                         justify="left").pack(anchor="w")

        def _clear_memories():
            self.settings["memories"] = []
            save_settings(self.settings)
            dialog.destroy()
            self.open_settings()

        tk.Button(body, text="CLEAR ALL SAVED MEMORIES", fg=DANGER, bg=PANEL,
                  activeforeground=DANGER, activebackground=PANEL,
                  relief="flat", font=("Segoe UI", 9, "bold"),
                  command=_clear_memories).pack(anchor="w", pady=(6, 4))

        tk.Label(body, text="Voice input is not available in this Windows "
                 "version.", fg=MUTED, bg=PANEL, font=("Segoe UI", 9),
                 wraplength=380, justify="left").pack(anchor="w")
        tk.Label(body, text="NOVA learns through user-approved saved "
                 "memories and conversation context. It does not retrain its "
                 "AI model or silently collect personal data. Memory stays "
                 "on this computer and is included in online prompts when "
                 "relevant.", fg=MUTED, bg=PANEL, font=("Segoe UI", 9),
                 wraplength=380, justify="left").pack(anchor="w", pady=(4, 0))
        tk.Label(body, text="Use a trusted provider. API credentials are "
                 "stored in plain text in your user profile; do not share a "
                 "copy of this app containing your key.", fg=MUTED, bg=PANEL,
                 font=("Segoe UI", 9), wraplength=380,
                 justify="left").pack(anchor="w", pady=(4, 0))

        buttons = tk.Frame(body, bg=PANEL)
        buttons.pack(fill="x", pady=(12, 0))

        def _save():
            self.settings["endpoint"] = endpoint_var.get().strip()
            self.settings["model"] = model_var.get().strip()
            self.settings["api_key"] = key_var.get().strip()
            save_settings(self.settings)
            self._set_status("Provider settings saved locally")
            dialog.destroy()

        tk.Button(buttons, text="SAVE", fg=CYAN, bg=PANEL,
                  activeforeground=CYAN, activebackground=PANEL,
                  relief="flat", font=("Segoe UI", 10, "bold"),
                  command=_save).pack(side="right", padx=(8, 0))
        tk.Button(buttons, text="CANCEL", fg=MUTED, bg=PANEL,
                  activeforeground=MUTED, activebackground=PANEL,
                  relief="flat", font=("Segoe UI", 10),
                  command=dialog.destroy).pack(side="right")


def main(argv=None):
    if tk is None:
        sys.stderr.write("NOVA for Windows needs tkinter (standard with "
                         "Python on Windows).\n")
        return 1
    root = tk.Tk()
    app = NovaApp(root, load_settings())
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
