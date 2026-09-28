# ORAC-Voice: User Manual

A quick-reference guide to operating ORAC... every voice command, keyboard shortcut, and control mode. For installation and setup, see [`README.md`](README.md).

---

## 1. Talking to ORAC

ORAC listens continuously once online, there's no push-to-talk button. Just speak naturally. Just after start-up, the status line shows "LOADING LANGUAGE MODEL" (the LCD: "LOADING MODEL...") while the model loads; a question asked then is answered once it's ready. He will respond in character: pedantic, sardonic, and reluctant to waste words on trivial questions.

To interrupt him mid-response, press **Esc** (barge-in), or pull the activator key, (if you’re using it.) He will halt immediately and register the override.

---

## 2. Voice & Text Commands

These work identically whether spoken or typed — every command below can be typed directly into the terminal input line as well as said aloud.

Say a command on its own. You can add "ORAC", "please" or "now" *(e.g. "ORAC, clear history please")*, but a sentence that only mentions a command, such as "What would happen if I said activate system shutdown?", is treated as an ordinary question.

### System Control

| Say / Type | What happens |
|---|---|
| "Exit interface" | Ends the ORAC-Voice program. Prompts to save the session transcript first *(in Headless Mode it is saved automatically)*, then exits cleanly. Does **not** power off the Mac itself. |
| "Activate System Shutdown" | Triggers a genuine macOS shutdown via `sudo`. Requires the sudoers rule from the README's optional Step 6. |
| "Activate System Reboot" | Genuine macOS restart, same sudo requirement as above. |
| "Clear memory" / "Clear history" / "New subject" | Wipes the active conversation context and starts fresh, in character. *(The session is added to the daily archive first.)* |

### Subspace Transceiver (Wi-Fi Control)

| Say / Type | What happens |
|---|---|
| "Enable networking" | Turns the Mac's Wi-Fi on. |
| "Disable networking" | Turns the Mac's Wi-Fi off. |

### Getting a Straight Answer ("Very Well" Protocol)

If ORAC is being characteristically evasive or long-winded, any of the following will force a direct, no-snark, fact-only answer beginning with "Very well.":

- "Answer the question"
- "Just answer"
- "More detail" / "Give me more detail"
- "Just do it"
- "Straight answer"

This is also useful for debugging or double-checking a fact without the usual runaround.

### Memory & Recall

| Say / Type | What happens |
|---|---|
| "What did we talk about" / "What were we talking about" / "What have we discussed" / "Summarise our conversation" / "Recap what we discussed" / "Remind me what we…" | Recaps the current conversation from active context. *(Early in a session, before you've asked three questions, ORAC checks the most recent archive instead.)* |
| Any of the above **combined with** a time reference — "yesterday," "last session," "earlier today," "days ago," "last Monday" | Searches the archived conversation log instead of just the live context. |
| "Check the archive" / "Search the archives" | Searches the archived conversation log. |

A time reference on its own, such as "the last time Travis saw Blake" or "Avon's past record", is treated as a lore question, not an archive search.

### Timers & Alarms

| Say / Type | What happens |
|---|---|
| "Set a timer for [number] seconds / minutes / hours" (e.g. "set a timer for five minutes", "set a timer for half an hour") | Starts an internal countdown; ORAC will alert you when it elapses. |
| "Set an alarm for [hour]:[minute] am/pm" (e.g. "set an alarm for 7:30 am"; 24-hour times such as 19:30 work too) | Schedules a one-off alarm for that clock time. |
| "Cancel timer" / "Cancel alarm" | Cancels whichever is currently active. |

Only one timer or alarm runs at a time: setting a new one replaces it. If ORAC is talking, or the activator key is out, when it's due, the alert waits until he has finished.

### Menial Tasks (In-Character Roleplay)

Saying any of the following will make ORAC grudgingly "comply" in character — this is a personality feature, not a real ship system:

- "Set a course" / "Lay in a course"
- "Set us down"
- "Operate the teleport" / "Engage the teleport"

---

## 3. Keyboard Shortcuts

Available whenever the terminal UI is active. In Headless Mode, **Ctrl+C** still works from an attached keyboard.

| Key | Action |
|---|---|
| **Enter** | Submit typed text |
| **Esc** | Interrupt ORAC mid-response (barge-in), or clear the current unsent input |
| **Backspace / Delete** | Delete last character |
| **Ctrl+U** | Clear the entire input line |
| **Ctrl+W** | Delete the last word typed |
| **Ctrl+C** | Gracefully triggers the same shutdown sequence as saying "Exit interface". Works in every state, even with the activator key removed. |
| **Option+M** | Toggle microphone mute on/off |
| **Option+T** | Toggle Text Selection Mode — lets you select and copy terminal text; suspends scroll-wheel history navigation while active |
| **Option+D** | Toggle Debug Mode — shows extra timing and diagnostic info in the UI, and logs timings, what ORAC heard and what he said to `ollama_debug.log` |
| **Mouse scroll / ↑ / ↓ / Page Up / Page Down** | Scroll back through conversation history |

---

## 4. Hardware Activator Key

If your ORAC unit has the physical Raspberry Pi Pico activator key installed:

- **Removing the key** locks the system… any reply stops, the microphone is muted, the display shows "SYSTEM LOCKED," and an accurate power-down sound effect plays.
- **Reinserting the key** restores normal operation immediately.
- **If the Pico isn't connected** when ORAC starts, he starts locked, to be safe. Without the key hardware, set `USE_ACTIVATOR = False` in `orac_chat.py`.

---

## 5. Operating Modes

These are set at the top of `orac_chat.py`.

- **Headless Mode** (`HEADLESS_MODE = True`): Disables the on-screen terminal UI entirely, for running ORAC inside a sealed chassis without a monitor attached. Voice commands and physical controls (activator key, LCD) continue to work normally. On exit, the transcript is saved automatically, with no prompt.
- **Text-Only Mode** (`TEXT_ONLY_MODE = True`): Disables the microphone; ORAC only responds to typed input. ORAC also offers this mode at start-up if the Whisper speech model is missing.
- **Waffle Mode** (`WAFFLE_MODE = True`): Lets ORAC talk at greater length when you raise one of his favourite topics, such as Star One, The System, Ensor, tarial cells or artificial intelligence.

---

## 6. Known Limitations

- **Flat first sentence**: sometimes the first sentence of a reply sounds flat while the rest sound as they should, with `gemma4:12b` as well as `gemma4:12b-mlx`. `extras/tts_probe.py` helps track it down: `--from-log` measures and replays what ORAC said, and `--live-check` tests whether the voice carries anything over from one sentence to the next.

---

*ORAC-Voice — built with equal parts Blake's 7 devotion and Apple Silicon. Enjoy! Caroline xo*
