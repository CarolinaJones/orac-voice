#!/usr/bin/env python3
"""ORAC TTS probe: why does the first sentence sound flat after the model has been idle?

Speaks one sentence under controlled conditions and times the speech synthesizer, so you can tell
a cold voice, contention with the LLM and real-time starvation apart. Quit ORAC first.

    python3 extras/tts_probe.py                           # voice only
    python3 extras/tts_probe.py --llm gemma4:12b-mlx      # while the MLX model streams a reply
    python3 extras/tts_probe.py --llm gemma4:12b          # same with the GGUF model, to compare

By default the sentence is wrapped in the same SSML as ORAC (rate 114%, pitch x-high, volume loud,
strong emphasis; change with --ssml-*, or --plain for none) and the model gets ORAC's context size.

Each round idles (default 90 s, so the voice goes cold), optionally starts an Ollama reply and waits
for its first token (ORAC's situation when it speaks sentence one), then runs two tests:

    LIVE    speaks the sentence normally, as ORAC does (real-time synthesis)
    RENDER  synthesizes it to an audio file as fast as possible (no real-time deadline)

Odd rounds run LIVE first, even rounds RENDER first, so each is measured cold; the cold render is
played back at the end of the even rounds. Compare by ear and by the table:

    LIVE flat when cold, cold RENDER fine   -> real-time starvation: render-then-play fixes it
    both flat when cold, fine when warm     -> the voice itself is cold (paged out / unloaded)
    flat only with --llm on the MLX model   -> contention with the model

RTF = seconds of audio produced per second of synthesis; near or below ~1.5x the voice can't keep
ahead of real time. "decomp" = pages the OS had to decompress during the cold test; a jump there
means memory was squeezed while idle.
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
import threading
import time

try:
    import objc
    from Foundation import NSDate, NSObject, NSRunLoop, NSURL
    from AVFoundation import (AVAudioFile, AVAudioPCMBuffer, AVSpeechSynthesisVoice,
                              AVSpeechSynthesizer, AVSpeechUtterance)
except ImportError as e:
    sys.exit(f"This probe needs macOS with PyObjC installed (pip install pyobjc): {e}")

PERSONAL_VOICE_TRAIT = 2      # AVSpeechSynthesisVoiceTraitIsPersonalVoice
AUTH_STATUS = {0: "not determined", 1: "denied", 2: "unsupported", 3: "authorized"}
DEFAULT_TEXT = ("Your inquiry is trivial. The Liberator was seized by Blake, Avon and Jenna, "
                "following the failed mutiny aboard the London.")

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


def pump(seconds=0.02):
    """Runs the main run loop briefly so AVFoundation can deliver its callbacks."""
    NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(seconds))


def vm_counters():
    """Cumulative decompression / swap-in counters from vm_stat (only the deltas matter)."""
    try:
        out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return {}
    counters = dict(re.findall(r"^(.+?):\s+(\d+)\.", out, flags=re.MULTILINE))
    return {"decomp": int(counters.get("Decompressions", 0)), "swapin": int(counters.get("Swapins", 0))}


def free_memory_pct():
    try:
        return int(subprocess.run(["sysctl", "-n", "kern.memorystatus_level"],
                                  capture_output=True, text=True, timeout=5).stdout.strip())
    except Exception:
        return None


def pick_voice(name):
    voices = list(AVSpeechSynthesisVoice.speechVoices())
    if name:
        for voice in voices:
            if name.lower() in voice.name().lower():
                return voice
        sys.exit(f"No voice matching {name!r}; try --list-voices.")
    for voice in voices:
        try:
            if voice.voiceTraits() & PERSONAL_VOICE_TRAIT:
                return voice
        except AttributeError:      # macOS < 14: no personal voices
            break
    return None                     # the system default voice


def orac_ssml(text, rate, pitch, volume, emphasis):
    """The SSML wrapper ORAC's MacTTS builds around each utterance."""
    escaped = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                   .replace('"', "&quot;").replace("'", "&apos;"))
    inner = f'<emphasis level="{emphasis}">{escaped}</emphasis>' if emphasis else escaped
    return f'<speak><prosody rate="{rate}%" pitch="{pitch}" volume="{volume}"><s>{inner}</s></prosody></speak>'


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

    def __init__(self, model, host, system_prompt, num_ctx, num_batch):
        self.model, self.host, self.system_prompt = model, host.rstrip("/"), system_prompt
        self.num_ctx, self.num_batch = num_ctx, num_batch
        self.tokens, self.ttft = 0, None
        self.first_token, self.stop = threading.Event(), threading.Event()
        self.error = None

    def start(self, timeout=180.0):
        self.t0 = time.perf_counter()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        while not self.first_token.wait(0.05):
            if self.error or not self.thread.is_alive() or time.perf_counter() - self.t0 > timeout:
                raise RuntimeError(f"no token from Ollama: {self.error or 'timed out'}")
        return self.ttft

    def _run(self):
        import requests
        messages = [{"role": "user", "content": "Describe the Liberator's systems in exhaustive detail."}]
        if self.system_prompt:
            messages.insert(0, {"role": "system", "content": self.system_prompt})
        body = {"model": self.model, "messages": messages, "stream": True, "think": False, "keep_alive": 14400,
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
        self.thread.join(10)
        return self.tokens


def orac_system_prompt():
    """ORAC's own persona + databanks, so the model's prefill matches the real app."""
    try:
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from orac_personality import orac_personality
        from orac_data_core import data_core
        return f"{orac_personality.replace('{ORAC_NAME}', 'ORAC')}\n\n--- DATABANKS ---\n{data_core}"
    except Exception:
        return None


def fmt(value, unit="s", digits=2):
    return "-" if value is None else f"{value:.{digits}f}{unit}"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--text", default=DEFAULT_TEXT, help="sentence to speak, or SSML starting with <speak>")
    ap.add_argument("--ssml-file", help="read the text/SSML from this file")
    ap.add_argument("--voice", help="part of a voice name (default: your Personal Voice, else the system voice)")
    ap.add_argument("--rate", type=float, help="AVSpeechUtterance rate 0.0-1.0; only used with --plain")
    ap.add_argument("--plain", action="store_true", help="speak the text as-is, without ORAC's SSML wrapper")
    ap.add_argument("--ssml-rate", default="114", help="ORAC SSML prosody rate, percent (default 114)")
    ap.add_argument("--ssml-pitch", default="x-high", help="ORAC SSML prosody pitch (default x-high)")
    ap.add_argument("--ssml-volume", default="loud", help="ORAC SSML prosody volume (default loud)")
    ap.add_argument("--ssml-emphasis", default="strong", help='ORAC SSML emphasis level, "" to omit (default strong)')
    ap.add_argument("--num-ctx", type=int, default=16384, help="must match ORAC's MODEL_MAX_TOKENS (default 16384)")
    ap.add_argument("--num-batch", type=int, default=256, help="must match ORAC's OLLAMA_NUM_BATCH (default 256)")
    ap.add_argument("--llm", metavar="MODEL", help="stream a reply from this Ollama model during each round")
    ap.add_argument("--host", default="http://localhost:11434", help="Ollama URL")
    ap.add_argument("--idle", type=float, default=90, help="seconds of silence before each round (default 90)")
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--no-play", action="store_true", help="don't play the cold renders back")
    ap.add_argument("--nap", action="store_true", help="allow App Nap (ORAC's behaviour before it opted out)")
    ap.add_argument("--list-voices", action="store_true")
    args = ap.parse_args()

    if args.list_voices:
        for voice in AVSpeechSynthesisVoice.speechVoices():
            print(f"{voice.name():30} {voice.language():8} quality={voice.quality()} {voice.identifier()}")
        return

    text = open(args.ssml_file, encoding="utf-8").read() if args.ssml_file else args.text
    if not args.plain and not text.lstrip().startswith("<speak"):
        text = orac_ssml(text, args.ssml_rate, args.ssml_pitch, args.ssml_volume, args.ssml_emphasis)
        args.rate = None                # SSML carries the rate
    try:
        status = int(AVSpeechSynthesizer.personalVoiceAuthorizationStatus())
        print(f"Personal Voice authorisation: {AUTH_STATUS.get(status, status)}")
    except AttributeError:
        pass
    voice = pick_voice(args.voice)
    print(f"Voice: {voice.name() if voice is not None else 'system default'}")

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
    system_prompt = orac_system_prompt() if args.llm else None
    rows = []

    for rnd in range(1, args.rounds + 1):
        with objc.autorelease_pool():
            print(f"\nRound {rnd}/{args.rounds}: idling {args.idle:.0f}s so the voice goes cold ...", flush=True)
            time.sleep(args.idle)

            load, ttft = None, None
            if args.llm:
                load = LLMLoad(args.llm, args.host, system_prompt, args.num_ctx, args.num_batch)
                try:
                    ttft = load.start()
                except RuntimeError as e:
                    sys.exit(f"Ollama ({args.host}, {args.llm}): {e}")
                print(f"  {args.llm} streaming (first token after {ttft:.2f}s)")

            order = ("live", "render") if rnd % 2 else ("render", "live")
            render_path = os.path.join(out_dir, f"round{rnd}_render.caf")
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
                        print("  RENDER produced no audio: this voice may not support offline rendering")
                after = vm_counters()
                delta = {k: after.get(k, 0) - before.get(k, 0) for k in ("decomp", "swapin")}
                rows.append((rnd, mode, temperature, result, delta, free_pct, ttft))

            tokens = load.finish() if load else None
            if tokens is not None:
                print(f"  (LLM streamed {tokens} chunks during the round)")
            if order[0] == "render" and not args.no_play and os.path.exists(render_path):
                print("  Playing the COLD render - compare with round 1's live speech", flush=True)
                subprocess.run(["afplay", render_path])

    print(f"\n{'round':>5} {'mode':6} {'state':5} {'latency':>8} {'wall':>7} {'audio':>7} {'RTF':>6} "
          f"{'decomp':>8} {'swapin':>7} {'free':>5}")
    for rnd, mode, temperature, r, delta, free_pct, ttft in rows:
        print(f"{rnd:>5} {mode:6} {temperature:5} {fmt(r['latency']):>8} {fmt(r['wall']):>7} "
              f"{fmt(r.get('audio')):>7} {fmt(r.get('rtf'), 'x', 1):>6} {delta['decomp']:>+8} "
              f"{delta['swapin']:>+7} {('-' if free_pct is None else str(free_pct) + '%'):>5}")
    print(f"\nRenders saved in {out_dir} (play with: afplay <file>)")
    del activity


if __name__ == "__main__":
    main()
