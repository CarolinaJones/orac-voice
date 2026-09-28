#!/usr/bin/env python3
"""ORAC TTS probe: why does the first sentence sound flat after the model has been idle?

Speaks one sentence under controlled conditions and times the speech synthesizer, so you can tell
a cold voice, contention with the LLM and real-time starvation apart. Quit ORAC first.

    python3 extras/tts_probe.py                           # voice only
    python3 extras/tts_probe.py --llm gemma4:12b-mlx      # while the MLX model streams a reply
    python3 extras/tts_probe.py --llm gemma4:12b          # same with the GGUF model, to compare
    python3 extras/tts_probe.py --menu                    # choose the voice from a list first
    python3 extras/tts_probe.py --voice-check             # which settings does the voice obey? does context matter?

Voice: set VOICE below, pass --voice "ORAC Personal Voice", or pick from a list with --menu. With
none of these, the probe uses ORAC's own VOICE from orac_chat.py, by ORAC's rule: the voice with
that exact name, else the first voice whose name starts with it. The SSML (rate, pitch, volume, emphasis) and the model settings are read
from orac_chat.py as well, so the probe speaks exactly as ORAC does.

Each round idles (default 90 s, so the voice goes cold), optionally starts an Ollama reply and waits
for its first token (ORAC's situation when it speaks sentence one), then runs two tests:

    LIVE    speaks the sentence normally, as ORAC does (real-time synthesis)
    RENDER  synthesizes it to an audio file as fast as possible (no real-time deadline)

Odd rounds run LIVE first, even rounds RENDER first, so each is measured cold; the cold render is
played back at the end of the even rounds. After each round you're asked how it sounded (f = flat,
o = ok, or a short note; --no-ask to skip). Compare by ear and by the table:

    LIVE flat when cold, cold RENDER fine   -> real-time starvation: render-then-play fixes it
    both flat when cold, fine when warm     -> the voice itself is cold (paged out / unloaded)
    flat only with --llm on the MLX model   -> contention with the model

RTF = seconds of audio produced per second of synthesis; near or below ~1.5x the voice can't keep
ahead of real time. "decomp" = pages the OS had to decompress during the cold test; a jump there
means memory was squeezed while idle.

--voice-check (or --ssml-check) renders the sentence once per setting (SSML rate, pitch, volume and
emphasis, and the utterance's own rate and pitchMultiplier), measures each render's length, pitch and
loudness, and reports which settings change the audio at all. The voice renders the same input to the
same bytes, so a render identical to the baseline means that setting is ignored. It then checks
whether a phrase said first (ORAC's old warm-up line: rendered, spoken silently, or as a silent
lead-in in the same utterance) changes how the sentence is spoken. About a minute; no model needed.

The settings, round notes and table are also saved to a text file next to this script, named
tts_probe_<date>_<time>_<model>.txt (--log FILE to save it somewhere else).
"""
import argparse
import ast
import math
import os
import platform
import re
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime

try:
    import objc
    from Foundation import NSDate, NSObject, NSRunLoop, NSURL
    from AVFoundation import (AVAudioFile, AVAudioPCMBuffer, AVSpeechSynthesisVoice,
                              AVSpeechSynthesizer, AVSpeechUtterance)
except ImportError as e:
    sys.exit(f"This probe needs macOS with PyObjC installed (pip install pyobjc): {e}")

# P R O B E  S E T T I N G S #

VOICE = ""                  # Voice to test, e.g. "ORAC Personal Voice": that voice, else the first whose name starts with
                            # this, as in ORAC. "" = use VOICE from orac_chat.py. --voice overrides this; --menu shows a list.

PROBE_DIR = os.path.dirname(os.path.abspath(__file__))
ORAC_DIR = os.path.dirname(PROBE_DIR)
NOVELTY_VOICE_TRAIT = 1       # AVSpeechSynthesisVoiceTraitIsNoveltyVoice
PERSONAL_VOICE_TRAIT = 2      # AVSpeechSynthesisVoiceTraitIsPersonalVoice
QUALITY = {1: "default", 2: "enhanced", 3: "premium"}
AUTH_STATUS = {0: "not determined", 1: "denied", 2: "unsupported", 3: "authorized"}
DEFAULT_TEXT = ("Your inquiry is trivial. The Liberator was seized by Blake, Avon and Jenna, "
                "following the failed mutiny aboard the London.")
# Used when orac_chat.py can't be read
FALLBACK = {"SSML_RATE": 114, "SSML_PITCH": "x-high", "SSML_VOLUME": "loud", "SSML_EMPHASIS": "strong",
            "MODEL_MAX_TOKENS": 16384, "OLLAMA_NUM_BATCH": 256, "OLLAMA_KEEP_ALIVE": 14400}
LEGEND = """\
latency  seconds until the voice started speaking (LIVE) or produced its first audio (RENDER)
wall     seconds the whole test took
audio    seconds of audio rendered; RTF = audio seconds per second of synthesis (below ~1.5x it can't keep up)
decomp   memory pages macOS decompressed during the test; swapin = pages read back from swap
free     free memory before the test
LLM 1st  the model's time to first token in that round
heard    how it sounded to you"""

try:
    _DELEGATE_PROTOCOLS = [objc.protocolNamed("AVSpeechSynthesizerDelegate")]
except Exception:
    _DELEGATE_PROTOCOLS = []


class SpeechTimes(NSObject, protocols=_DELEGATE_PROTOCOLS):
    """Records when the synthesizer actually starts and finishes an utterance."""
    def init(self):
        self = objc.super(SpeechTimes, self).init()
        if self is None:
            return None
        self.started = self.finished = self.target = None
        return self

    # Only the utterance being measured counts: a render's callbacks can arrive late
    def speechSynthesizer_didStartSpeechUtterance_(self, synth, utterance):
        if utterance == self.target:
            self.started = time.perf_counter()

    def speechSynthesizer_didFinishSpeechUtterance_(self, synth, utterance):
        if utterance == self.target:
            self.finished = time.perf_counter()


class Report:
    """Prints lines and keeps them for the results file."""
    def __init__(self, path):
        self.path, self.lines = path, []

    def __call__(self, line=""):
        print(line, flush=True)
        self.lines.append(line)

    def save(self):
        if not self.path:
            return
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                f.write("\n".join(self.lines) + "\n")
        except OSError as e:
            print(f"Could not save the results to {self.path}: {e}")
            self.path = None


def pump(seconds=0.02):
    """Runs the main run loop briefly so AVFoundation can deliver its callbacks."""
    NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(seconds))


def sysctl(key):
    try:
        return subprocess.run(["sysctl", "-n", key], capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        return ""


def vm_counters():
    """Cumulative decompression / swap-in counters from vm_stat (only the deltas matter)."""
    try:
        out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return {}
    counters = dict(re.findall(r"^(.+?):\s+(\d+)\.", out, flags=re.MULTILINE))
    return {"decomp": int(counters.get("Decompressions", 0)), "swapin": int(counters.get("Swapins", 0))}


def free_memory_pct():
    level = sysctl("kern.memorystatus_level")
    return int(level) if level.isdigit() else None


def machine_info():
    parts = [f"macOS {platform.mac_ver()[0] or '?'}", sysctl("hw.model") or "unknown Mac"]
    memory = sysctl("hw.memsize")
    if memory.isdigit():
        parts.append(f"{int(memory) / 2**30:.0f} GB")
    return "  ·  ".join(parts)


def orac_settings():
    """Plain settings from orac_chat.py, read rather than run, so the probe matches ORAC by default."""
    wanted = set(FALLBACK) | {"VOICE", "USE_PERSONAL_VOICE"}
    found = {}
    try:
        with open(os.path.join(ORAC_DIR, "orac_chat.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
    except (OSError, SyntaxError, ValueError):
        return found
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id in wanted):
            try:
                found[node.targets[0].id] = ast.literal_eval(node.value)
            except Exception:
                pass
    return found


def setting(cli_value, name, orac):
    """(value, source): the command line wins, then orac_chat.py, then the probe's fallback."""
    if cli_value is not None:
        return cli_value, "command line"
    if name in orac:
        return orac[name], "orac_chat.py"
    return FALLBACK[name], "probe default"


def voice_traits(voice):
    try:
        return int(voice.voiceTraits())
    except AttributeError:          # macOS < 14: no Personal or novelty voices
        return 0


def is_personal(voice):
    return bool(voice_traits(voice) & PERSONAL_VOICE_TRAIT)


def describe(voice):
    if voice is None:
        return "system default voice"
    kind = "Personal Voice" if is_personal(voice) else f"{QUALITY.get(voice.quality(), 'unknown')} quality"
    return f"{voice.name()}  [{kind}, {voice.language()}]"


def personal_voice_auth():
    try:
        status = int(AVSpeechSynthesizer.personalVoiceAuthorizationStatus())
    except AttributeError:
        return "unavailable (needs macOS 14 or later)"
    return AUTH_STATUS.get(status, str(status))


def voices_named(voices, name):
    """ORAC's rule: the voice with exactly this name, else the voices whose name starts with it (ORAC
    takes the first). With none, falls back to a case-insensitive search; the second value says
    whether ORAC's own rule matched."""
    matches = [v for v in voices if v.name() == name] or [v for v in voices if v.name().startswith(name)]
    if matches:
        return matches, True
    return [v for v in voices if name.lower() in v.name().lower()], False


def voice_menu(voices, default=None):
    """Numbered list, Personal Voices first, then English (UK) voices. Returns the chosen voice."""
    personal = [v for v in voices if is_personal(v)]
    others = sorted((v for v in voices if not voice_traits(v) and v.language() == "en-GB"), key=lambda v: v.name())
    if not others:
        others = sorted((v for v in voices if not voice_traits(v) and v.language().startswith("en")),
                        key=lambda v: (v.language(), v.name()))
    shown = personal + others
    if default is not None and all(v.identifier() != default.identifier() for v in shown):
        shown.insert(0, default)
    if not shown:
        sys.exit("No voices found.")

    print("\nChoose the voice to test:")
    if not personal:
        print(f"  (No Personal Voices listed. Personal Voice authorisation: {personal_voice_auth()};"
              f" see README step 5.)")
    default_no = 1
    for number, voice in enumerate(shown, 1):
        mark = ""
        if default is not None and voice.identifier() == default.identifier():
            default_no, mark = number, "   <- default"
        print(f"  {number:3}. {describe(voice)}{mark}")
    while True:
        answer = input(f"Number, or the start of any voice name [Enter = {default_no}]: ").strip()
        if not answer:
            return shown[default_no - 1]
        if answer.isdigit() and 1 <= int(answer) <= len(shown):
            return shown[int(answer) - 1]
        matches, _ = voices_named(voices, answer)
        if matches:
            return matches[0]
        print("  No voice matches that. (Ctrl+C to quit; --list-voices shows every voice.)")


def choose_voice(args, orac, say):
    """The voice to test, and where the choice came from. Notes go through say()."""
    voices = list(AVSpeechSynthesisVoice.speechVoices())
    if args.voice:
        wanted, source = args.voice, "--voice"
    elif VOICE:
        wanted, source = VOICE, "VOICE in tts_probe.py"
    elif orac.get("VOICE"):
        wanted, source = orac["VOICE"], "VOICE in orac_chat.py"
    else:
        wanted, source = None, None
    interactive = sys.stdin.isatty()

    found = None
    if wanted:
        matches, orac_rule = voices_named(voices, wanted)
        if matches:
            found = matches[0]
            if orac_rule and len(matches) > 1:
                say(f"Note:    {wanted!r} matches {len(matches)} voices ({', '.join(v.name() for v in matches)}). "
                    f"ORAC uses the first, so the probe does too; give the full name to pick another.")
            elif not orac_rule:
                say(f"Note:    ORAC wouldn't find {wanted!r}: VOICE has to match the start of the name, "
                    f"capitals included. The probe is using {found.name()!r}.")
        else:
            say(f"Note:    no voice name starts with {wanted!r} ({source}).")
            if not interactive:
                sys.exit("Try --list-voices, or run the probe in a terminal to choose from the menu.")

    if args.menu or (found is None and interactive):
        return voice_menu(voices, found), "chosen from the menu"
    if found is not None:
        return found, source
    personal = [v for v in voices if is_personal(v)]
    if personal:
        say("Note:    no voice chosen, so the first Personal Voice is used. Set VOICE, or use --voice or --menu.")
        return personal[0], "first Personal Voice"
    return None, "no voice chosen"


def build_ssml(text, prosody=None, emphasis=""):
    """<speak>[<prosody ...>]<s>[<emphasis>]text[</emphasis>]</s>[</prosody>]</speak>, as ORAC builds it."""
    escaped = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                   .replace('"', "&quot;").replace("'", "&apos;"))
    body = f'<emphasis level="{emphasis}">{escaped}</emphasis>' if emphasis else escaped
    inner = f"<s>{body}</s>"
    if prosody:
        attributes = "".join(f' {name}="{value}"' for name, value in prosody.items())
        inner = f"<prosody{attributes}>{inner}</prosody>"
    return f"<speak>{inner}</speak>"


def orac_ssml(text, rate, pitch, volume, emphasis):
    """The SSML wrapper ORAC's MacTTS builds around each utterance."""
    return build_ssml(text, {"rate": f"{rate}%", "pitch": pitch, "volume": volume}, emphasis)


def make_utterance(text, voice, rate):
    if text.lstrip().startswith("<speak"):
        utterance = AVSpeechUtterance.speechUtteranceWithSSMLRepresentation_(text)
        if utterance is None:
            sys.exit("AVSpeechUtterance rejected the SSML.")
    else:
        utterance = AVSpeechUtterance.speechUtteranceWithString_(text)
    if voice is not None:
        utterance.setVoice_(voice)
    if rate is not None:
        utterance.setRate_(rate)
    return utterance


def speak_live(synth, times, utterance, timeout=60.0):
    """Real-time speech, as ORAC does it. Returns start latency and total wall time."""
    times.started = times.finished = None
    times.target = utterance
    t0 = time.perf_counter()
    synth.speakUtterance_(utterance)
    seen_speaking = False
    while time.perf_counter() - t0 < timeout:
        pump()
        if times.finished is not None:
            break
        if synth.isSpeaking():
            seen_speaking = True
        elif seen_speaking:
            break                   # Finished, but the delegate callbacks were not delivered
    end = times.finished or time.perf_counter()
    return {"latency": (times.started - t0) if times.started else None, "wall": end - t0}


def render(synth, utterance, path, timeout=60.0):
    """Synthesizes to a file as fast as the engine can go, with no real-time playback deadline."""
    st = {"file": None, "frames": 0, "rate": 0.0, "first": None, "last": None, "done": False, "error": None}
    t0 = time.perf_counter()

    def on_buffer(buf):
        try:
            if buf is None or not buf.isKindOfClass_(AVAudioPCMBuffer):
                return
            if buf.frameLength() == 0:          # An empty buffer marks the end of the utterance
                st["done"] = True
                return
            now = time.perf_counter()
            st["first"] = st["first"] or now
            st["last"] = now
            fmt = buf.format()
            if st["file"] is None:
                audio_file, err = AVAudioFile.alloc().initForWriting_settings_commonFormat_interleaved_error_(
                    NSURL.fileURLWithPath_(path), fmt.settings(), fmt.commonFormat(), fmt.isInterleaved(), None)
                if audio_file is None:
                    raise RuntimeError(f"AVAudioFile could not be created: {err}")
                st["file"], st["rate"] = audio_file, fmt.sampleRate()
            ok, err = st["file"].writeFromBuffer_error_(buf, None)
            if not ok:
                raise RuntimeError(f"AVAudioFile write failed: {err}")
            st["frames"] += buf.frameLength()
        except Exception as e:
            st["error"], st["done"] = e, True

    synth.writeUtterance_toBufferCallback_(utterance, on_buffer)
    while not st["done"] and time.perf_counter() - t0 < timeout:
        pump()
        if st["last"] and time.perf_counter() - st["last"] > 3.0:
            break                   # No end marker: 3 s without a buffer counts as done
        if st["first"] is None and time.perf_counter() - t0 > 15.0:
            break                   # Nothing at all: this voice may not support offline rendering
    audio_file, st["file"] = st["file"], None
    if audio_file is not None and audio_file.respondsToSelector_("close"):
        audio_file.close()          # macOS 15+; older versions close when the object is released
    del audio_file
    if st["error"]:
        raise st["error"]
    audio_s = st["frames"] / st["rate"] if st["rate"] else 0.0
    synth_s = (st["last"] or time.perf_counter()) - t0
    return {"latency": (st["first"] - t0) if st["first"] else None, "wall": synth_s,
            "audio": audio_s, "rtf": audio_s / synth_s if audio_s and synth_s > 0 else None}


class LLMLoad:
    """Streams a long reply from Ollama in the background, as ORAC does while it speaks."""

    def __init__(self, model, host, system_prompt, num_ctx, num_batch, keep_alive):
        self.model, self.host, self.system_prompt = model, host.rstrip("/"), system_prompt
        self.num_ctx, self.num_batch, self.keep_alive = num_ctx, num_batch, keep_alive
        self.tokens, self.ttft = 0, None
        self.first_token, self.stop = threading.Event(), threading.Event()
        self.error = None

    def start(self, timeout=180.0):
        self.t0 = time.perf_counter()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        while not self.first_token.wait(0.05):
            if self.error or not self.thread.is_alive() or time.perf_counter() - self.t0 > timeout:
                self.stop.set()
                raise RuntimeError(f"no token from Ollama: {self.error or 'timed out'}")
        return self.ttft

    def _run(self):
        import requests
        messages = [{"role": "user", "content": "Describe the Liberator's systems in exhaustive detail."}]
        if self.system_prompt:
            messages.insert(0, {"role": "system", "content": self.system_prompt})
        body = {"model": self.model, "messages": messages, "stream": True, "think": False,
                "keep_alive": self.keep_alive,
                # Same runner options as ORAC, so a model ORAC loaded isn't reloaded for the probe
                "options": {"num_ctx": self.num_ctx, "num_batch": self.num_batch, "num_predict": 800}}
        try:
            with requests.post(f"{self.host}/api/chat", json=body, stream=True, timeout=300) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    if not self.first_token.is_set():
                        self.ttft = time.perf_counter() - self.t0
                        self.first_token.set()
                    self.tokens += 1
                    if self.stop.is_set():
                        break
        except Exception as e:
            self.error = e

    def finish(self):
        self.stop.set()
        if getattr(self, "thread", None):
            self.thread.join(10)
        return self.tokens


def ollama_version(host):
    try:
        import requests
        return requests.get(f"{host.rstrip('/')}/api/version", timeout=3).json().get("version", "?")
    except Exception:
        return "?"


def orac_system_prompt():
    """ORAC's own persona + databanks, so the model's prefill matches the real app."""
    try:
        sys.path.insert(0, ORAC_DIR)
        from orac_personality import orac_personality
        from orac_data_core import data_core
        return f"{orac_personality.replace('{ORAC_NAME}', 'ORAC')}\n\n--- DATABANKS ---\n{data_core}"
    except Exception:
        return None


def default_log_path(llm):
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", llm) if llm else "voice-only"
    return os.path.join(PROBE_DIR, f"tts_probe_{datetime.now():%Y-%m-%d_%H%M}_{label}.txt")


def ask_heard(what):
    """How a test sounded, in the listener's words: 'flat', 'ok', a short note, or '-'."""
    try:
        answer = input(f"  How did the {what} sound? f = flat, o = ok, or a short note (Enter to skip): ").strip()
    except EOFError:
        return "-"
    return {"f": "flat", "o": "ok"}.get(answer.lower(), answer) or "-"


def fmt(value, unit="s", digits=2):
    return "-" if value is None else f"{value:.{digits}f}{unit}"


def table(rows):
    lines = [f"{'round':>5} {'mode':6} {'state':5} {'latency':>8} {'wall':>7} {'audio':>7} {'RTF':>6} "
             f"{'decomp':>8} {'swapin':>7} {'free':>5} {'LLM 1st':>8}  heard"]
    for row in rows:
        r, delta = row["result"], row["delta"]
        free = "-" if row["free"] is None else f"{row['free']}%"
        lines.append(f"{row['round']:>5} {row['mode']:6} {row['state']:5} {fmt(r['latency']):>8} "
                     f"{fmt(r['wall']):>7} {fmt(r.get('audio')):>7} {fmt(r.get('rtf'), 'x', 1):>6} "
                     f"{delta['decomp']:>+8} {delta['swapin']:>+7} {free:>5} {fmt(row['ttft']):>8}  {row['heard']}")
    return lines


def read_caf(path):
    """(sample rate, (flags, channels, bits), raw sample bytes) of a linear-PCM CAF file, as AVAudioFile writes it."""
    import struct
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"caff":
        raise ValueError(f"{path} is not a CAF file")
    pos, rate, layout, raw = 8, None, None, b""
    while pos + 12 <= len(data):
        kind, size = data[pos:pos + 4], struct.unpack(">q", data[pos + 4:pos + 12])[0]
        pos += 12
        if size < 0:                        # Size not filled in: the chunk runs to the end of the file
            size = len(data) - pos
        if kind == b"desc":
            rate, _, flags, _, _, channels, bits = struct.unpack(">d4sIIIII", data[pos:pos + 32])
            layout = (flags, channels, bits)
        elif kind == b"data":
            raw = data[pos + 4:pos + size]  # After the edit count
        pos += size
    return rate, layout, raw


def samples_of(layout, raw):
    """The first channel of a render as floats (numpy), or None without numpy."""
    try:
        import numpy as np
    except ImportError:
        return None
    flags, channels, bits = layout
    frames = len(raw) // (bits // 8) // channels
    kind = ("<" if flags & 2 else ">") + ("f" if flags & 1 else "i") + str(bits // 8)
    x = np.frombuffer(raw[:frames * channels * (bits // 8)], dtype=kind).astype(np.float64).reshape(-1, channels)[:, 0]
    return x if flags & 1 else x / 2.0 ** (bits - 1)


def analyse(rate, layout, raw):
    """Length, speech span, median pitch, pitch range and loudness of a render. Pitch and loudness need numpy."""
    flags, channels, bits = layout
    x = samples_of(layout, raw)
    if x is None:
        return {"length": len(raw) // (bits // 8) // channels / rate, "speech": None, "pitch": None, "range": None,
                "level": None}
    return analyse_samples(x, rate)


def analyse_samples(x, rate):
    import numpy as np
    stats = {"length": len(x) / rate, "speech": None, "pitch": None, "range": None, "level": None}
    loud = np.nonzero(np.abs(x) > 0.01)[0]
    if not len(loud):
        return stats
    stats["speech"] = (loud[-1] - loud[0]) / rate

    # Pitch: YIN on 40 ms frames every 10 ms, at 16 kHz, confidently voiced frames only
    step = rate / 16000.0
    width = max(1, int(round(step)))
    y = np.convolve(x, np.ones(width) / width, mode="same")[(np.arange(int(len(x) / step)) * step).astype(int)]
    sr, n, hop, tmin, tmax = 16000, 640, 160, 16000 // 500, 16000 // 60
    floor = 0.1 * np.sqrt(np.mean(y ** 2))
    size = 1 << (2 * n + tmax).bit_length()
    f0, voiced_rms = [], []
    for start in range(0, len(y) - n - tmax, hop):
        seg = y[start:start + n + tmax]
        frame_rms = np.sqrt(np.mean(seg[:n] ** 2))
        if frame_rms < floor:
            continue
        voiced_rms.append(frame_rms)
        corr = np.fft.irfft(np.conj(np.fft.rfft(seg[:n], size)) * np.fft.rfft(seg, size), size)[:tmax + 1]
        sq = np.concatenate(([0.0], np.cumsum(seg ** 2)))
        energy = sq[n:n + tmax + 1] - sq[:tmax + 1]
        d = np.maximum(energy[0] + energy - 2 * corr, 0.0)
        cmnd = np.ones(tmax + 1)
        cmnd[1:] = d[1:] * np.arange(1, tmax + 1) / np.maximum(np.cumsum(d[1:]), 1e-12)
        below = np.nonzero(cmnd[tmin:tmax] < 0.2)[0]
        if len(below):
            tau = tmin + below[0]
            while tau + 1 < tmax and cmnd[tau + 1] < cmnd[tau]:
                tau += 1
            f0.append(sr / tau)
    if voiced_rms:
        stats["level"] = 20 * np.log10(np.sqrt(np.mean(np.square(voiced_rms))))
    if len(f0) >= 10:
        semitones = 12 * np.log2(np.array(f0) / np.median(f0))
        stats["pitch"] = float(np.median(f0))
        stats["range"] = float(np.percentile(semitones, 90) - np.percentile(semitones, 10))
    return stats


# (label, control, how): each render changes one thing from its baseline
SSML_CHECKS = [
    ("plain text",           None,              {}),
    ("SSML, no settings",    None,              {"ssml": {}}),
    ("SSML rate 70%",        "SSML rate",       {"ssml": {"rate": "70%"}}),
    ("SSML rate 150%",       "SSML rate",       {"ssml": {"rate": "150%"}}),
    ("SSML pitch x-low",     "SSML pitch",      {"ssml": {"pitch": "x-low"}}),
    ("SSML pitch x-high",    "SSML pitch",      {"ssml": {"pitch": "x-high"}}),
    ("SSML volume x-soft",   "SSML volume",     {"ssml": {"volume": "x-soft"}}),
    ("SSML volume x-loud",   "SSML volume",     {"ssml": {"volume": "x-loud"}}),
    ("SSML emphasis strong", "SSML emphasis",   {"ssml": {}, "emphasis": "strong"}),
    ("pitchMultiplier 0.5",  "pitchMultiplier", {"pitch_multiplier": 0.5}),
    ("pitchMultiplier 2.0",  "pitchMultiplier", {"pitch_multiplier": 2.0}),
    ("rate 0.35",            "utterance rate",  {"rate": 0.35}),
    ("rate 0.65",            "utterance rate",  {"rate": 0.65}),
]


def ssml_check(synth, voice, text, orac_prosody, orac_emphasis, out_dir, report):
    """Renders `text` once per setting and reports which settings change the audio."""
    checks = list(SSML_CHECKS) + [("ORAC's SSML", None, {"ssml": orac_prosody, "emphasis": orac_emphasis})]
    if orac_emphasis:
        checks.append(("ORAC's SSML, no emphasis", None, {"ssml": orac_prosody}))
    results = {}
    for number, (label, control, how) in enumerate(checks, 1):
        print(f"  rendering {number}/{len(checks)}: {label}", flush=True)
        if "ssml" in how:
            utterance = make_utterance(build_ssml(text, how["ssml"], how.get("emphasis", "")), voice, None)
        else:
            utterance = make_utterance(text, voice, how.get("rate"))
            if "pitch_multiplier" in how:
                utterance.setPitchMultiplier_(how["pitch_multiplier"])
        path = os.path.join(out_dir, f"{number:02d}_{re.sub(r'[^A-Za-z0-9.%-]+', '_', label)}.caf")
        with objc.autorelease_pool():
            rendered = render(synth, utterance, path)
        if not rendered["audio"] or not os.path.exists(path):
            report(f"The voice produced no audio for {label!r}: it may not support offline rendering.")
            return
        rate, layout, raw = read_caf(path)
        results[label] = {"control": control, "ssml": "ssml" in how, "raw": raw, **analyse(rate, layout, raw)}

    def compare(row, base):
        if row["raw"] == base["raw"]:
            return "identical"
        notes = []
        if abs(row["length"] - base["length"]) > 0.03 * base["length"]:
            notes.append(f"length {row['length'] - base['length']:+.2f}s")
        if row["pitch"] and base["pitch"] and abs(12 * math.log2(row["pitch"] / base["pitch"])) >= 0.5:
            notes.append(f"pitch {12 * math.log2(row['pitch'] / base['pitch']):+.1f} semitones")
        if row["level"] is not None and base["level"] is not None and abs(row["level"] - base["level"]) >= 1:
            notes.append(f"level {row['level'] - base['level']:+.1f} dB")
        return ", ".join(notes) or "different audio, same length, pitch and level"

    plain, ssml = results["plain text"], results["SSML, no settings"]
    report()
    report("SSML check: the same sentence rendered with one setting changed at a time")
    report(f"{'render':26} {'length':>7} {'speech':>7} {'pitch':>7} {'range':>6} {'level':>7}  compared with its baseline")
    for label, row in results.items():
        if label == "plain text":
            versus = "baseline for the utterance rate and pitchMultiplier rows"
        elif label == "SSML, no settings":
            versus = f"baseline for the SSML rows; vs plain text: {compare(row, plain)}"
        else:
            versus = compare(row, ssml if row["ssml"] else plain)
        report(f"{label:26} {fmt(row['length']):>7} {fmt(row['speech']):>7} {fmt(row['pitch'], 'Hz', 0):>7} "
               f"{fmt(row['range'], 'st', 1):>6} {fmt(row['level'], 'dB', 1):>7}  {versus}")
    report()
    report("Verdict (does the voice obey the setting?)")
    for control in dict.fromkeys(row["control"] for row in results.values() if row["control"]):
        rows = {label: row for label, row in results.items() if row["control"] == control}
        base = ssml if control.startswith("SSML") else plain
        obeyed = [label for label, row in rows.items() if row["raw"] != base["raw"]]
        verdict = "obeyed" if len(obeyed) == len(rows) else "partly obeyed" if obeyed else "IGNORED"
        report(f"  {control:16} {verdict:14} ({'; '.join(f'{label}: {compare(row, base)}' for label, row in rows.items())})")
    report()
    report("length = the whole render, speech = first to last sound, pitch = median voice pitch,")
    report("range = pitch variation in semitones (10th to 90th percentile; lower = flatter), level = loudness")
    return results


PRIMING_PHRASE = "I find your discourse irritatingly tedious."      # ORAC's old warm-up line


def context_check(synth, times, voice, text, prosody, emphasis, baseline_raw, out_dir, report):
    """Does anything said before the sentence change how the voice speaks it? Compares against the
    sentence rendered on its own (baseline_raw), which is byte-for-byte repeatable."""
    sentence = build_ssml(text, prosody, emphasis)
    phrase = build_ssml(PRIMING_PHRASE, prosody, emphasis)

    def render_file(ssml, name):
        utterance = make_utterance(ssml, voice, None)
        path = os.path.join(out_dir, name)
        with objc.autorelease_pool():
            render(synth, utterance, path)
        return read_caf(path)

    print("  context 1/3: the phrase rendered, then the sentence", flush=True)
    render_file(phrase, "c1_phrase.caf")
    after_rendered = render_file(sentence, "c2_sentence_after_the_phrase_rendered.caf")
    print("  context 2/3: the phrase spoken silently, then the sentence", flush=True)
    silent = make_utterance(phrase, voice, None)
    silent.setVolume_(0.0)                  # As ORAC's old warm-up did
    with objc.autorelease_pool():
        speak_live(synth, times, silent)
    after_spoken = render_file(sentence, "c3_sentence_after_the_phrase_spoken_silently.caf")
    print("  context 3/3: the phrase as a silent lead-in to the sentence", flush=True)
    lead_in = ("<speak>" + build_ssml(PRIMING_PHRASE, {"volume": "silent"})[7:-8]
               + sentence[7:-8] + "</speak>")
    rate, layout, lead_raw = render_file(lead_in, "c4_phrase_as_silent_lead-in.caf")

    report()
    report(f"Context check: does saying \"{PRIMING_PHRASE}\" first change the sentence?")
    same_after = []
    for label, (_, _, raw) in (("phrase rendered first, then the sentence", after_rendered),
                               ("phrase spoken silently first (like the old warm-up)", after_spoken)):
        same = raw == baseline_raw
        same_after.append(same)
        report(f"  {label:54} {'identical to the sentence alone' if same else 'DIFFERENT from the sentence alone'}")

    base, lead = samples_of(layout, baseline_raw), samples_of(layout, lead_raw)
    label = "phrase as a silent lead-in, in the same utterance"
    lead_verdict = None
    if base is None:
        report(f"  {label:54} needs numpy to compare")
    else:
        import numpy as np
        onset_base, onset_lead = (int(np.argmax(np.abs(x) > 0.01)) for x in (base, lead))
        silence = (onset_lead - onset_base) / rate
        if silence < 0.3 and abs(len(lead) - len(base)) / rate > 0.3:
            report(f"  {label:54} the lead-in was spoken aloud: the voice ignores volume=\"silent\"")
        else:
            pad = min(int(0.01 * rate), onset_base, onset_lead)     # Same lead-up before both onsets
            a, b = base[onset_base - pad:], lead[onset_lead - pad:]
            n = min(len(a), len(b))
            same = abs(len(a) - len(b)) <= int(0.01 * rate) and float(np.max(np.abs(a[:n] - b[:n]))) < 1e-4
            if same:
                lead_verdict = False
                opening = f"{silence:.2f}s of silence, then" if silence >= 0.3 else "the lead-in was left out:"
                report(f"  {label:54} {opening} the sentence identical to it alone")
            else:
                x, y = analyse_samples(a, rate), analyse_samples(b, rate)
                length = y["length"] - x["length"]
                pitch = 12 * math.log2(y["pitch"] / x["pitch"]) if x["pitch"] and y["pitch"] else 0.0
                spread = y["range"] - x["range"] if x["range"] is not None and y["range"] is not None else 0.0
                level = y["level"] - x["level"] if x["level"] is not None and y["level"] is not None else 0.0
                notes = f"length {length:+.2f}s, pitch {pitch:+.1f} st, range {spread:+.1f} st, level {level:+.1f} dB"
                # Tiny sample differences (e.g. at the join) aren't a different delivery
                lead_verdict = (abs(length) >= 0.03 * x["length"] or abs(pitch) >= 0.5 or abs(spread) >= 1.0
                                or abs(level) >= 1.0)
                change = "CHANGED" if lead_verdict else "slightly different samples, same delivery"
                report(f"  {label:54} {silence:.2f}s of silence, then the sentence {change} ({notes})")
    report()
    if all(same_after):
        report("A separate phrase before the sentence doesn't change it at all: the voice carries nothing from")
        report("one utterance to the next, so a warm-up phrase can't set its mood. The old warm-up can only have")
        report("helped by waking the voice (loading it back into memory) before the first real sentence.")
    else:
        report("A phrase said before the sentence DOES change it: the voice carries context between utterances.")
        report("Compare c2/c3 with the ORAC's SSML render by ear.")
    if lead_verdict is True:
        report("Context inside the same utterance changes the sentence: compare c4 (after its silence) with the")
        report("ORAC's SSML render by ear.")
    elif lead_verdict is False:
        report("Context inside the same utterance doesn't change it either.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--text", default=DEFAULT_TEXT, help="sentence to speak, or SSML starting with <speak>")
    ap.add_argument("--ssml-file", help="read the text/SSML from this file")
    ap.add_argument("--voice", help="start of a voice name, as in ORAC's VOICE setting "
                                    "(default: VOICE at the top of this file, else orac_chat.py's)")
    ap.add_argument("--menu", action="store_true", help="choose the voice from a numbered list")
    ap.add_argument("--list-voices", action="store_true", help="list every voice and exit")
    ap.add_argument("--rate", type=float, help="AVSpeechUtterance rate 0.0-1.0; only used with --plain")
    ap.add_argument("--plain", action="store_true", help="speak the text as-is, without ORAC's SSML wrapper")
    ap.add_argument("--ssml-rate", help="SSML prosody rate, percent (default: orac_chat.py's SSML_RATE)")
    ap.add_argument("--ssml-pitch", help="SSML prosody pitch (default: orac_chat.py's SSML_PITCH)")
    ap.add_argument("--ssml-volume", help="SSML prosody volume (default: orac_chat.py's SSML_VOLUME)")
    ap.add_argument("--ssml-emphasis", help='SSML emphasis level, "" to omit (default: orac_chat.py\'s SSML_EMPHASIS)')
    ap.add_argument("--num-ctx", type=int, help="context size (default: orac_chat.py's MODEL_MAX_TOKENS)")
    ap.add_argument("--num-batch", type=int, help="batch size (default: orac_chat.py's OLLAMA_NUM_BATCH)")
    ap.add_argument("--llm", metavar="MODEL", help="stream a reply from this Ollama model during each round")
    ap.add_argument("--host", default="http://localhost:11434", help="Ollama URL")
    ap.add_argument("--idle", type=float, default=90, help="seconds of silence before each round (default 90)")
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--no-play", action="store_true", help="don't play the cold renders back")
    ap.add_argument("--no-ask", action="store_true", help="don't ask how each round sounded")
    ap.add_argument("--warm-up", action="store_true",
                    help="speak one line silently before round 1, as ORAC does at start-up (VOICE_WARMUP)")
    ap.add_argument("--nap", action="store_true", help="allow App Nap (ORAC's behaviour before it opted out)")
    ap.add_argument("--voice-check", "--ssml-check", dest="ssml_check", action="store_true",
                    help="which SSML/utterance settings the voice obeys, and whether a phrase said first changes it")
    ap.add_argument("--log", metavar="FILE", help="where to save the results (default: a dated .txt next to this script)")
    args = ap.parse_args()

    if args.list_voices:
        voices = sorted(AVSpeechSynthesisVoice.speechVoices(), key=lambda v: (not is_personal(v), v.language(), v.name()))
        for voice in voices:
            kind = "Personal Voice" if is_personal(voice) else QUALITY.get(voice.quality(), "?")
            print(f"{voice.name():32} {voice.language():8} {kind:15} {voice.identifier()}")
        return

    text = open(args.ssml_file, encoding="utf-8").read() if args.ssml_file else args.text
    if args.ssml_check and text.lstrip().startswith("<speak"):
        sys.exit("--voice-check needs a plain sentence (it adds the SSML itself).")

    label = "voice-check" if args.ssml_check else args.llm
    if args.warm_up and not args.ssml_check:
        label = f"{label or 'voice-only'}_warm-up"
    log_path = args.log or default_log_path(label)
    if os.path.isdir(log_path):
        log_path = os.path.join(log_path, os.path.basename(default_log_path(label)))
    report = Report(log_path)
    report(f"ORAC TTS probe  ·  {datetime.now():%Y-%m-%d %H:%M:%S}")
    report(machine_info())
    orac = orac_settings()
    if not orac:
        report("Note:    couldn't read orac_chat.py, so the probe's own defaults are used.")
    voice, voice_source = choose_voice(args, orac, report)

    rate, rate_src = setting(args.ssml_rate, "SSML_RATE", orac)
    pitch, pitch_src = setting(args.ssml_pitch, "SSML_PITCH", orac)
    volume, volume_src = setting(args.ssml_volume, "SSML_VOLUME", orac)
    emphasis, emphasis_src = setting(args.ssml_emphasis, "SSML_EMPHASIS", orac)
    num_ctx, num_ctx_src = setting(args.num_ctx, "MODEL_MAX_TOKENS", orac)
    num_batch, num_batch_src = setting(args.num_batch, "OLLAMA_NUM_BATCH", orac)
    keep_alive, _ = setting(None, "OLLAMA_KEEP_ALIVE", orac)

    def marked(label, value, source):
        return f"{label} {value}" + ("" if source == "orac_chat.py" else f" ({source})")

    spoken = text
    if args.plain:
        ssml_line = "none (--plain)"
    elif text.lstrip().startswith("<speak"):
        ssml_line = "as given in the text"
    else:
        ssml_line = ", ".join([marked("rate", f"{rate}%", rate_src), marked("pitch", pitch, pitch_src),
                               marked("volume", volume, volume_src),
                               marked("emphasis", emphasis or "none", emphasis_src)])
        text = orac_ssml(text, rate, pitch, volume, emphasis)
        args.rate = None                # SSML carries the rate

    report(f"Voice:   {describe(voice)}  ({voice_source})")
    if voice is not None:
        report(f"         {voice.identifier()}")
    report(f"Personal Voice authorisation: {personal_voice_auth()}")
    if orac.get("USE_PERSONAL_VOICE") is False:
        report("Note:    orac_chat.py has USE_PERSONAL_VOICE = False, so ORAC speaks with NSSpeechSynthesizer;"
               " this probe tests AVSpeechSynthesizer.")
    report(f"SSML:    {ssml_line}")
    report(f"Text:    {spoken}")
    if args.ssml_check:
        pass
    elif args.llm:
        report(f"LLM:     {args.llm} on Ollama {ollama_version(args.host)}  ("
               f"{marked('num_ctx', num_ctx, num_ctx_src)}, {marked('num_batch', num_batch, num_batch_src)})")
    else:
        report("LLM:     none (voice only)")
    if not args.ssml_check:
        report(f"Rounds:  {args.rounds}, each after {args.idle:.0f} s idle  ·  App Nap {'allowed' if args.nap else 'off'}")
    report("Settings are ORAC's own (orac_chat.py) unless marked.")

    activity = None
    if not args.nap:
        from Foundation import (NSActivityLatencyCritical, NSActivityUserInitiatedAllowingIdleSystemSleep,
                                NSProcessInfo)
        activity = NSProcessInfo.processInfo().beginActivityWithOptions_reason_(
            NSActivityUserInitiatedAllowingIdleSystemSleep | NSActivityLatencyCritical, "TTS probe")

    synth = AVSpeechSynthesizer.alloc().init()
    times = SpeechTimes.alloc().init()
    synth.setDelegate_(times)
    out_dir = tempfile.mkdtemp(prefix="orac_tts_probe_")
    if args.ssml_check:
        prosody = {"rate": f"{rate}%", "pitch": pitch, "volume": volume}
        try:
            results = ssml_check(synth, voice, spoken, prosody, emphasis, out_dir, report)
            if results:
                context_check(synth, times, voice, spoken, prosody, emphasis, results["ORAC's SSML"]["raw"],
                              out_dir, report)
        except KeyboardInterrupt:
            report("\nStopped early (Ctrl+C).")
        report()
        report(f"Renders saved in {out_dir}")
        report(f'Listen: for f in "{out_dir}"/*.caf; do echo "$f"; afplay "$f"; done')
        report.save()
        if report.path:
            print(f"Results saved to {report.path}")
        return
    system_prompt = orac_system_prompt() if args.llm else None
    ask = not args.no_ask and sys.stdin.isatty()
    rows, load = [], None
    if args.warm_up:
        line = "Logic arrays online."           # ORAC's start-up line
        utterance = make_utterance(line if args.plain else orac_ssml(line, rate, pitch, volume, emphasis), voice, args.rate)
        utterance.setVolume_(0.0)
        warm = speak_live(synth, times, utterance)
        report(f"Warm-up: {line!r} spoken silently before round 1 (took {warm['wall']:.2f}s)")

    try:
        for rnd in range(1, args.rounds + 1):
            with objc.autorelease_pool():
                print(f"\nRound {rnd}/{args.rounds}: idling {args.idle:.0f}s so the voice goes cold ...", flush=True)
                time.sleep(args.idle)

                ttft = None
                if args.llm:
                    load = LLMLoad(args.llm, args.host, system_prompt, num_ctx, num_batch, keep_alive)
                    try:
                        ttft = load.start()
                    except RuntimeError as e:
                        load = None
                        report(f"Round {rnd}: Ollama ({args.host}, {args.llm}): {e}")
                        break
                    print(f"  {args.llm} streaming (first token after {ttft:.2f}s)")

                order = ("live", "render") if rnd % 2 else ("render", "live")
                render_path = os.path.join(out_dir, f"round{rnd}_render.caf")
                tests = {}
                for position, mode in enumerate(order):
                    temperature = "cold" if position == 0 else "warm"
                    before, free_pct = vm_counters(), free_memory_pct()
                    utterance = make_utterance(text, voice, args.rate)
                    if mode == "live":
                        print(f"  LIVE ({temperature}) - listen now", flush=True)
                        result = speak_live(synth, times, utterance)
                    else:
                        result = render(synth, utterance, render_path)
                        if not result["audio"]:
                            report(f"Round {rnd}: RENDER produced no audio (this voice may not support offline rendering)")
                    after = vm_counters()
                    tests[mode] = {"round": rnd, "mode": mode, "state": temperature, "result": result,
                                   "delta": {k: after.get(k, 0) - before.get(k, 0) for k in ("decomp", "swapin")},
                                   "free": free_pct, "ttft": ttft, "heard": "-"}
                    rows.append(tests[mode])

                chunks = load.finish() if load else None
                load = None
                played = False
                if order[0] == "render" and not args.no_play and os.path.exists(render_path):
                    print("  Playing the COLD render - compare with round 1's live speech", flush=True)
                    subprocess.run(["afplay", render_path])
                    played = True
                if ask:
                    tests["live"]["heard"] = ask_heard(f"{tests['live']['state']} LIVE speech")
                    if played:
                        tests["render"]["heard"] = ask_heard("cold RENDER playback")
                if args.llm:
                    report(f"Round {rnd}: {args.llm} first token after {ttft:.2f}s, {chunks} chunks streamed during the tests")
                report.save()
    except KeyboardInterrupt:
        report("\nStopped early (Ctrl+C): the results so far are below.")
        synth.stopSpeakingAtBoundary_(0)        # AVSpeechBoundaryImmediate
        if load:
            load.finish()

    report()
    for line in table(rows):
        report(line)
    report()
    report(LEGEND)
    report()
    report(f"Renders saved in {out_dir} (play with: afplay <file>)")
    report.save()
    if report.path:
        print(f"Results saved to {report.path}")
    del activity


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
