# Changelog

Changes from `main` (v1.5.8) to `wip`, newest first. Versions 1.6.6 to 1.9.2 were developed locally
and never pushed, so they are included under 1.9.3.

---

## v1.9.4.1 (2026-09-28)

Tools for tracking down the flat first sentence, and a few tweaks.

### Voice diagnostics
- **What ORAC said, in `ollama_debug.log`** (debug mode): a "Said" line for each utterance, with how
  long it took and how long the voice had been quiet before it. Typed questions are logged too.
- **`tts_probe.py --from-log`** renders each sentence ORAC said again, with the model idle, and measures
  its pitch, pitch range and speaking rate. It then compares the first sentence of each reply with the
  rest, to show whether a flat opening is in its words. `--say` replays the replies.
- **`tts_probe.py --live-check`** speaks the same sentence live after silence, straight after another
  sentence, and straight after a silent warm-up line, to show whether the live voice carries anything
  over from one sentence to the next. Every earlier check compared renders, which can't show that. It
  compares when each word started (the voice's own timings) and records each take through the
  microphone for pitch; `--list-mics` and `--mic N` pick another input if the default can't hear the
  voice. It only claims what it could measure. The takes come in shuffled order, and silence and the
  silent line sound the same until the sentence starts, so they can be rated blind.
- **`--from-log`** compares first sentences with the rest only within replies of two sentences or more.
- **What they found** (in the manual's known limitations): the voice speaks the same words the same way
  every time, live as well as rendered, whatever came just before (pitch within 3 Hz, word timing within
  11 ms). How lively a sentence sounds comes from its words and punctuation.

### Tweaks
- While the model loads, the status line reads "ACCESSING TARIAL MATRIX..." (LCD: "ACCESSING...").
- The silent start-up warm-up line is now "I find your discourse, tedious."
- The reboot announcement is spoken in two parts.
- Reply temperature 0.90 (was 0.85).
- The voice test settings (`MIN_FIRST_UTTERANCE_WORDS`, `SENTENCES_PER_UTTERANCE`,
  `SPEAK_AFTER_GENERATION`, `VOICE_WARMUP`) have their own section; `MIN_FIRST_UTTERANCE_WORDS` is 0
  (off).

---

## v1.9.4 (2026-09-28)

A performance, reliability and tidy-up release. You don't need to change any settings.

### Speed and model loading
- **Background preload at boot.** The model is loaded and the system prompt is prefilled while the
  boot sequence runs, so the first reply doesn't wait for a cold load. In testing, the first reply
  went from about 30 s to about 15 s.
- **No more forced unloads.** Context pruning and "clear history" no longer unload the model. Each
  unload used to cost a cold reload plus a full prefill of the system prompt.
- **Consistent request settings.** Compaction requests now use the same runner options (`num_ctx`,
  `num_batch`, `num_keep`), `keep_alive` and `think=False` as normal replies. Different options
  made Ollama reload the model, and leaving out `keep_alive` reset it to Ollama's 5-minute default.
- **New `OLLAMA_KEEP_ALIVE` setting** (default 4 hours).
- **New `UNLOAD_ON_EXIT` setting** (default on, as before). ORAC unloads the model when it closes, to
  free the memory, so every restart pays the model load and the full prompt read again (about 30 s).
  Set it to `False` to keep the model loaded for `OLLAMA_KEEP_ALIVE` after ORAC closes, for quick
  restarts.
- **"LOADING LANGUAGE MODEL" status.** Shown on screen and on the LCD ("LOADING MODEL...") until the
  boot preload has finished. A question asked before then waits for it, which is where a slow first
  reply comes from after switching models (about 15 s with `gemma4:12b`, 30 s with the MLX model).
- **Model timings in `ollama_debug.log`** (in debug mode). For the preload and for every reply: time
  to first token (and how much of it was spent waiting for the model), load time, prompt reading
  time and generation. Replies that are stopped early are logged too. Errors are logged either way.
- **Fixed:** with `DEBUG_START = True`, the header's stats line started dimmed, as if debug were off.
- **What Whisper heard, in `ollama_debug.log`** (debug mode): each transcription with Whisper's
  confidence (no-speech probability, log-probability), including those dropped as likely
  hallucinations.
- **A real "Thank you" gets an answer.** A short "Thank you" was always dropped as a Whisper
  hallucination, even when said to ORAC. It's now dropped only when Whisper wasn't sure it heard
  speech (no-speech probability 0.1 or more; real speech logs 0.00). "Thanks for watching",
  "Thank you for watching" and a lone "you" or "um" are still always dropped.
- **Whisper warm-up at start-up.** Whisper loaded its model on the first thing said (3.7 s instead of
  under a second); one second of silence is now transcribed while ORAC boots.
- **Gemma 3 stop strings removed.** Gemma 4 uses different turn markers. A stop list sent with the
  request also replaced the model's own.

### Voice
- **New `MIN_FIRST_UTTERANCE_WORDS` setting** (default 4; 0 turns it off). A very short opening
  sentence such as "Irrelevant." is joined to the next sentence, so the voice has a full phrase to
  shape.
- **New `SPEAK_AFTER_GENERATION` setting** (default off). It holds speech until the reply has
  finished generating, to test the flat voice with `gemma4:12b-mlx`.
- **`SSML_EMPHASIS = ""`** now leaves out the `<emphasis>` tag.
- **App Nap turned off.** macOS no longer puts ORAC into App Nap or coalesces its timers between
  turns.
- **New `SENTENCES_PER_UTTERANCE` setting** (default 1). After the first sentence, ORAC used to wait
  for two complete sentences before speaking again, which left up to 2 s of silence after a short
  opening sentence. The model writes about three times faster than ORAC speaks, so sending each
  sentence as soon as it's written keeps the voice fed. 2 restores the pairs.
- **Fixed:** "I'm" and "I'd" were spoken as "I, m" and "I, d" because of the pause added after
  "I".
- **Voice warm-up at start-up (`VOICE_WARMUP`, on by default).** One line is spoken silently while
  ORAC boots (silent through SSML: a Personal Voice still speaks aloud with the utterance volume at 0). In `tts_probe`, the voice's first live sentence took 7.9 to 8.1 s instead of 6.6 s (and
  lost its first word with MLX), with either model; that start-up cost now happens during boot
  instead of in the first reply. The probe's `--warm-up` option measures the difference.
- **Exact voice name wins.** With several Personal Voices, `VOICE = "ORAC Personal Voice"` could
  pick "ORAC Personal Voice 2" if macOS listed that one first, and no `VOICE` value could avoid it.
  A voice with exactly the `VOICE` name is now chosen first.
- **New `extras/tts_probe.py`.** It times the voice cold and warm, spoken live and rendered to a
  file, with or without an LLM reply streaming. Use it to track down the flat voice.
  - It tests ORAC's own voice and settings, read from `orac_chat.py`. Choose another voice with
    `VOICE` at the top of the probe, `--voice "name"` or `--menu`.
  - After each round it asks how the speech sounded, and saves the settings and results table to
    a text file next to the script.
  - `--voice-check` (or `--ssml-check`) renders the sentence once per setting (SSML rate, pitch,
    volume, emphasis and break, and the utterance's rate and pitch multiplier), each against the
    unchanged sentence rendered just before it, and reports which ones change the audio. It also
    tests whether a phrase said first (the old warm-up line) or a sentence at another speed changes
    the next sentence, whether two sentences in one utterance sound different from each on its own,
    and compares the voice's very first render with a later one.
  - `--say --text "..."` speaks one sentence with ORAC's settings, to try wording by ear.
- **Measured with the probe:** a Personal Voice ignores SSML pitch, SSML emphasis and the pitch
  multiplier (the renders are byte-identical), and obeys rate, volume and pauses. The settings'
  comments now say so.

### Commands and archive
- **Whole-utterance commands.** Power-off, reboot, networking and "clear history" now only run
  when the command is the whole thing you said. Filler words ("ORAC", "please", "now") are
  ignored. Before this, "what if I said activate system shutdown?" powered the Mac off.
- **"clear memory" works**, as the README describes.
- **Fixed:** cancelling "exit interface" with **C** no longer sends the phrase to ORAC as a
  question.
- **Fewer false archive lookups.** Lore questions no longer trigger the archive: "What is Avon's
  past record?" and "the last time Travis saw Blake" used to. A lookup now needs one of these:
  - a reference to your own conversation;
  - a memory phrase;
  - an explicit "check the archive".

  "last Monday" (or any weekday) now counts. Early in a session, "what did we talk about?" reaches
  the latest archive.

### Reliability (race conditions)
- **Barge-in during context compaction.** Interrupting while old turns were being summarised
  could lose the second answer and leave two user turns in a row. A reply that has been replaced
  now stands down, and missing replies are filled in so turns always alternate.
- **Stray hum.** The delayed hum could still start after it had been stopped.
- **Status flashes.** An older flash could cut a newer one short.
- **Alarms.** An alarm waits until ORAC is idle and unlocked. It used to talk over replies and
  speak while the key was out.
- **Typed input.** Typed lines go through a queue. Two quick entries could lose one.
- **Key removed mid-reply.** Pulling the key during a reply still marks it as interrupted and
  clears the typing state.

### Ctrl+C
- **Ctrl+C closes ORAC in every state**, including with the activator key out, while listening,
  and in headless mode. It stops any reply and runs the normal shutdown: the save prompt, or an
  automatic transcript save when headless. Pressing **C** at the prompt carries on.
- **No warning on exit.** The "resource_tracker: … leaked semaphore" message is gone.

### Tidy-up
- **Duplicate code merged:**
  - header drawing;
  - the idle status line;
  - debug output;
  - typed and spoken input;
  - token counting.

  Dead code was removed.
- **`TRANSCRIPT_DIR = ''`** now means the project folder. It used to mean the folder ORAC was
  started from.
- **New section headers.** The sections are regrouped under new letter-spaced headers
  (`# H A R D W A R E  S E T T I N G S #` style), with settings first. Title boxes in every file
  now use spaces instead of tabs, so they line up in any editor and on GitHub.

### Documentation
- **README** updated for the `AVSpeechSynthesizer` voice, the current settings and commands, and
  the model the code uses by default (`gemma4:12b`).
- **New `ORAC-VOICE_User_Manual.md`:** every voice command, keyboard shortcut and mode.

---

## v1.9.3 (2026-09-27)

Local development since v1.6.5, first pushed with v1.9.4.

### Voice
- **New speech engine.** Speech now uses `AVSpeechSynthesizer` instead of
  `NSSpeechSynthesizer`, with SSML control of rate, pitch, volume and emphasis (`SSML_RATE`,
  `SSML_PITCH`, `SSML_VOLUME`, `SSML_EMPHASIS`).
- **Voice chosen by name.** The Apple Personal Voice is selected by name (`USE_PERSONAL_VOICE`,
  `VOICE`). Synth voices still use `voice_pitch` and `S_RATE`.
- **Numbers read naturally.** Dates, years and numbers with commas (e.g. "1,250") are read as
  words.
- **`[USER]` tags** in replies become "you" and "your", even when a tag is split across streamed
  chunks.

### Hardware
- **Activator key** on the Pico (GPIO 15, `USE_ACTIVATOR`):
  - Removing the key locks ORAC: the mic is muted, speech stops and the shutdown sound plays.
  - Inserting it wakes ORAC.
  - If the Pico can't be reached, ORAC starts locked.
- **Pico link recovers after a re-plug.** The serial link reopens if the Pico is unplugged and
  plugged back in, then asks for the key state again.
- **LCD status text** comes from a rules table (`LCD_STATUS_RULES`), with short timer labels.
  The Pico is told when the context is over 85% full.
- **New voice commands:**
  - "activate system reboot";
  - "enable networking" and "disable networking", which switch Wi-Fi on `NIC` on or off.

  Power-off and reboot use `sudo -n`, so they fail at once if the sudoers entry is missing
  instead of waiting for a password.

### Commands
- **"Exit interface"** now ends the session. "Shut down" and "deactivate" did before, and a stray
  "deactivate" could end it by accident.
- **"Re set" removed** from the memory purge commands ("clear history" and "new subject" remain).
- **Memory recall phrases** must now be about the conversation, e.g. "summarise our conversation".
  Bare "summarise", "recap" and "remind me" turned lore questions into recaps.

### Modes
- **`HEADLESS_MODE`** runs ORAC without a monitor: no terminal UI, and exiting (by voice or
  Ctrl+C) saves the transcript automatically, since the save prompt can't be seen.
- **`TEXT_ONLY_MODE`** (typed input only) is now a user setting. ORAC still offers it at startup
  if the Whisper model is missing.
- **`WAFFLE_MODE`** lets ORAC talk at length about his favourite topics.

### Conversation and memory
- **Trigger phrases in their own file.** Trigger and filler phrases moved to the new
  `orac_trigger_phrases.py`.
- **Barge-in during prompt evaluation.** You can interrupt ORAC before the first word of a reply
  arrives.
- **Ollama client timeout.** The client has a 120 s timeout (`OLLAMA_TIMEOUT`), and every call
  uses one `num_batch` (`OLLAMA_NUM_BATCH`).
- **Safer saving.** Archive files are written atomically, under a lock. Transcripts are saved by
  one function.
- **Clean shutdown on signals.** SIGTERM and SIGHUP shut ORAC down cleanly.
- **Error log.** Errors are logged to `ollama_debug.log`.

### Personality, lore and pronunciation
- **`orac_personality.py` v1.3.0 → v1.4.4:**
  - Criticism targeting, variation rules and topics of genuine interest (v1.4.2).
  - Self-reference anchor for "I was created by Ensor" (v1.4.2).
  - Tone changed to mildly pedantic and unsparing (v1.4.3).
  - Behaviour revamped towards an irritable, impatient tone (v1.4.4).
- **`orac_data_core.py` v1.1.8 (lore corrections):**
  - Micro Power Cells, not Tarial Cells, at Cephlon and Aristo.
  - Radiation sickness at Aristo.
  - ORAC exclusively in Ensor's laboratory before its acquisition.
  - The System not associated with the Federation.
- **`orac_phonetics.py` v1.0.4 → v1.0.6:**
  - Longest match first, so "self-exiled" and "neural-implant" get their own pronunciations.
  - Title-case fix: "Star One" becomes "Star-One", not "Star-one".
  - New entries, including 100, 2000 and "systems"; a few removed.
- **New `orac_trigger_phrases.py` v1.0.1.**

---

## v1.6.5 (2026-09-07)

### Added
- **LCD support.** A 1602 I2C LCD is driven by a Raspberry Pi Pico over USB serial (`USE_LCD`,
  `LCD_PORT`, `LCD_BAUD`):
  - Line 1 shows token and memory use.
  - Line 2 shows the status.
  - The status LED shows speaking, processing, muted, alert and idle.
  - The backlight turns off after 60 s idle.
  - "SYSTEM HALTED" is shown on exit.
- **Daily archive (RAG memory).** Each session's questions are added to a daily JSON file in
  `memory_core/` (`ARCHIVE_DIR`). Asking "what did we talk about yesterday?" loads that day's
  archive into the prompt; the model works out the date.
- **Timestamps** in the transcript and the message log.
- **Timings kept for display.** Speech-to-text and time-to-first-token timings are kept for the
  LCD and debug display.

### Changed
- **Gentler pruning.** Pruning keeps about 65% of the context, instead of cutting back to the
  system prompt plus 1,200 tokens.
- **Longer keep-alive.** The model stays loaded for 4 hours between requests (was 2).
