import os
import subprocess
import threading
import queue
import time
import sys
import random
import shutil
import atexit 
import re 
import gc
import numpy as np
import speech_recognition as sr
import mlx_whisper
import psutil
import termios
import tty
import select
import signal
import textwrap 

from datetime import datetime, timedelta
from AppKit import NSSpeechSynthesizer
from ollama import chat

from orac_phonetics import orac_phonetics
from orac_data_core import data_core
from orac_personality import orac_personality

#==================================================================================================#
#    						 ORAC-VOICE v1.3.3 (Lore friendly VoiceChat)                          #
#          						  Copyright © 2026 Caroline Mayne                                  #
#         						 https://github.com/CarolinaJones/                                 #
#==================================================================================================#

#------------------------------------#
#      USER CHANGEABLE VARIABLES     #
#------------------------------------#

VOICE = "" 			# Leave blank to use the "System Voice" - This allows for SIRI/Personal Voices.
voice_pitch = 80.0 	# Only works on SYNTH voices and not SIRI/Personal voices.

U1 = 0.038											# Teletype Speed
U2 = 0.052											# Teletype Uniformity

TRANSCRIPT_DIR = ''			                        # Set location. Default is within project folder.
TR = "ORAC_Transcript_CM" 							# Transcript Name Prefix (Date will be added).

USER_NAME = "Jenna" 								# USER Name and Identity
ORAC_NAME = "ORAC" 									# ORAC's Name

# TERMINAL SETTINGS #
TERMINAL_PROFILE = "Homebrew"						# Terminal Profile
TERMINAL_FONT = "AdwaitaMono Nerd Font Mono"		# Font Name
TERMINAL_FONT_SIZE = 17								# Font Size
TERMINAL_COLS = 100									# Window Width
TERMINAL_ROWS = 25									# Window Height

#              IT SHOULD NOT BE NECESSARY TO CHANGE ANYTHING BELOW THIS LINE 					   #
#==================================================================================================#

# MODEL VARIABLES
		
OLLAMA_MODEL = 'mannix/gemma2-9b-sppo-iter3:q4_k_m'			
#OLLAMA_MODEL = 'mannix/gemma2-9b-sppo-iter3:q5_k_m'		
#OLLAMA_MODEL = 'gemma4:31b-cloud'						# Cloud based gemma4
#OLLAMA_MODEL = 'gemma4:e2b-mlx'						# Local gemma4-mlx model

MODEL_MAX_TOKENS = 8192									# MAX TOKENS for STATUS Predict & NUM_CTX
CHARS_PER_TOKEN = 4.5									# For UI Health Bar estimation
WHISPER_MODEL = './whisper/whisper-turbo-q4'			# Whisper-turbo-q4 is the best compromise

# ANSII PALETTES & CURSORS - SOUNDS

G, A, R, B = "\033[38;5;46m", "\033[38;5;214m", "\033[38;5;196m", "\033[1;37m"
FL, NOFL, DIM, RESET = "\033[5m", "\033[25m", "\033[2m", "\033[0m"
IT, NOIT = "\x1B[3m","\x1B[23m" 

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SOUND_PROCESSING = os.path.join(BASE_DIR, "resources/sounds/orac-hum_16k.mp3")
SOUND_COMPUTE_START = os.path.join(BASE_DIR, "resources/sounds/orac-startup_16k.mp3")
SOUND_COMPUTE_END = os.path.join(BASE_DIR, "resources/sounds/orac-shutdown_16k.mp3")
SOUND_SHUTDOWN = os.path.join(BASE_DIR, "resources/sounds/orac-shutdown_16k.mp3")
SOUND_READY = os.path.join(BASE_DIR, "resources/sounds/sub_16k.mp3")
SOUND_QUIT = os.path.join(BASE_DIR, "resources/sounds/funk_16k.mp3")
SOUND_BRACELET = os.path.join(BASE_DIR, "resources/sounds/bracelet.mp3")


# GLOBAL OPTIMIZATIONS

SPLIT_REGEX = re.compile(r'(?<!\bMr)(?<!\bDr)(?<!\bMrs)(?<!\bMs)(?<!\bCapt)(?<!\bCmdr)(?<!\bGen)(?<!\bProf)[.!?]+[\]}"\’”]?\s+')
ansi_escape = re.compile(r'\x1b(?:\[[0-9;]*[A-Za-z~]|O[A-Za-z])')
HALLUCINATION_REGEX = re.compile(r'(thank you|thanks for watching|subscribe|amara\.org|by mooji|subtitles by|\[silence\]|\[music\]|\(sigh\)|^[ \t]*you\.?[ \t]*$)')
PURGE_CMD = ("re set", "clear history", "new subject") # Changed to lowercase to match user_text.lower()
SHUTDOWN_CMD = ("shut down", "deactivate")

# PRE-COMPILED REGEX FOR TTS SANITIZATION

TTS_NUM_SPACER = re.compile(r'(?<![a-zA-Z])(\d{3,})(?![a-zA-Z])')
TTS_ELLIPSIS = re.compile(r'\.{2,}')
TTS_ARROGANT_ADVERBS = re.compile(r'(?i)\b(however|therefore|predictably|obviously|furthermore|evidently|naturally|clearly|as expected)[.,]*\s*', flags=re.IGNORECASE | re.VERBOSE)
TTS_DELIBERATE_PRONOUNS = re.compile(r'(?<![.,;!?])\b(your|i|my)\b(?![.,;])', flags=re.IGNORECASE)
TTS_POSSESSIVE_S = re.compile(r"\b([A-Z][a-z]+s)'(?!\w)")
TTS_MARKDOWN = re.compile(r'[*`_~#>|+]')
TTS_BRACKETS = re.compile(r'[\[\]{}()]')
TTS_QUOTES = re.compile(r"(?<!\w)[']|['](?!\w)")
TTS_DBL_COMMAS = re.compile(r',\s*,')
TTS_MULTI_SPACE = re.compile(r'\s+')
TTS_SPACE_COMMA = re.compile(r' ,\b')
TTS_LEAD_WEIRD = re.compile(r'^[^a-zA-Z0-9]+')
TTS_TRAIL_PUNC = re.compile(r'[,;\-\s]+$')
TTS_VERY_WELL = re.compile(r'(?i)\b(very well)[.,]*\s*')
TTS_BE_PRECISE = re.compile(r'(?i)\b(Be precise)[.,]*\s*')
TTS_I_AM_ANGRY = re.compile(r'(?i)\b(I am (?:ORAC|Oarack)|What is it you want|silent)[.,]*\s*')
TTS_NAME_FIX = re.compile(rf',\s+({USER_NAME})[.,!]$')

#==================================================================================================#
#     							  DATA CORE & PROMPT ASSEMBLY                                      #
#==================================================================================================#

def personalize_core(core: str, name: str) -> str:
    known_full_names = ["Roj Blake", "Kerr Avon", "Jenna Stannis", "Vila Restal", "Olag Gan"]
    text = core
    for full_name in known_full_names:
        if name.lower() in full_name.lower():
            text = re.sub(rf"\b{full_name}['’]s\b", "[USER'S]", text, flags=re.IGNORECASE)
            text = re.sub(rf"\b{full_name}\b", "[USER]", text, flags=re.IGNORECASE)
            
    text = re.sub(rf"\b{re.escape(name)}['’]s\b", "[USER'S]", text, flags=re.IGNORECASE)
    text = re.sub(rf'\b{re.escape(name)}\b', '[USER]', text, flags=re.IGNORECASE)
    return text
    
personalized_data_core = personalize_core(data_core, USER_NAME)

SYSTEM_INSTRUCTION = (
    f"{orac_personality}\n\n"
    f"--- INTERNAL DATABANKS ---\n"
    f"{personalized_data_core}\n\n"
    f"--- DIRECTIVES ---\n"
    f"Speaking as {ORAC_NAME} using 1st-person pronouns ('I', 'me', 'my').\n"
    f"Addressing the biological entity [USER] referenced in your databanks, ONLY using 2nd-person pronouns.\n"
    f"Translating the tag [USER] into 2nd-person pronouns when recounting databank events.\n"
    f"Natively conjugating verbs for the 2nd-person.\n"
    f"Maintaining strict separation between {ORAC_NAME}'s history and [USER]'s history.\n"
    f"Concealing the tag '[USER]'. Withholding the name '{USER_NAME}' unless explicitly asked."
)

#==================================================================================================#
#     								APPLICATION STATE & CLEANUP                                    #
#==================================================================================================#

class OracState:
    def __init__(self):
        self.running = True
        self.current_tokens = 0
        self.token_status = "NOMINAL"
        self.token_color = G
        self.noise_floor = 0.0

        self.is_speaking = threading.Event()
        self.is_processing = threading.Event() 
        self.is_listening = threading.Event()
        self.is_shutdown = threading.Event()
        self.is_interrupted = threading.Event()
        self.mic_error = False

        self.active_procs = []
        self.history = []
        self.full_message_log = []
        self.scroll_offset = 0
        self.proc_lock = threading.Lock()
        self.hist_lock = threading.Lock()

        self.input_buffer = ""
        self.input_ready = threading.Event()
        self.submitted_text = ""
        self.terminal_lock = threading.Lock()
        self.ui_needs_redraw = False
        self.text_selection_mode = False
        
        self._last_hist_len = -1
        self._cached_token_base = len(SYSTEM_INSTRUCTION)
        self.total_chars = 0
        
        self.alarm_time_str = None
        self.alarm_trigger_epoch = None
        self.is_alarm_playing = False

        self.cached_ram = " 0.0%"
        self.term_cols = TERMINAL_COLS
        self.term_rows = TERMINAL_ROWS

state = OracState()

try:
    old_term_settings = termios.tcgetattr(sys.stdin.fileno())
except:
    old_term_settings = None

def cleanup_processes():
    if old_term_settings:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_term_settings)
    try:
        sys.stdout.write("\033[?1000l\033[?1006l") 	
        sys.stdout.write("\033[?1049l") 			
        sys.stdout.write("\033[1;r\033[?25h\n") 	
        sys.stdout.flush()
    except: pass
    if 'processing_sound' in globals() and processing_sound.is_running():
        processing_sound.stop()
    with state.proc_lock:
        for proc in list(state.active_procs):
            try:
                if proc and proc.poll() is None:
                    proc.kill()
            except: pass
        state.active_procs.clear()

atexit.register(cleanup_processes)

#==================================================================================================#
#     							  TERMINAL UI & LAYOUT ENGINE                                      #
#==================================================================================================#

def setup_terminal():
    sys.stdout.write("\033[?1049h\033[?1000h\033[?1006h\033[?25l\033[2J\033[H")
    sys.stdout.flush()
    if sys.platform != "darwin":
        sys.stdout.write(f"\033[8;{TERMINAL_ROWS};{TERMINAL_COLS}t")
        sys.stdout.flush()
        return

    apple_script = f"""
    tell application "Terminal"
        try
            set front_window to window 1
            set current settings of front_window to settings set "{TERMINAL_PROFILE}"
            set font name of front_window to "{TERMINAL_FONT}"
            set font size of front_window to {TERMINAL_FONT_SIZE}
            set number of columns of front_window to {TERMINAL_COLS}
            set number of rows of front_window to {TERMINAL_ROWS}
        end try
    end tell
    """
    try:
        subprocess.run(['osascript', '-e', apple_script], capture_output=True)
        time.sleep(0.5) 
    except Exception: pass
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()
    
    cols, rows = shutil.get_terminal_size(fallback=(state.term_cols, state.term_rows))
    state.term_cols = cols
    state.term_rows = rows

def update_token_health():
    if not hasattr(state, 'total_chars'):
        state.total_chars = state._cached_token_base

    if len(state.history) != state._last_hist_len:
        with state.hist_lock:
            state._last_hist_len = len(state.history)
            state.total_chars = state._cached_token_base + sum(len(msg['content']) for msg in state.history) + 600
        
    state.current_tokens = int(state.total_chars / CHARS_PER_TOKEN)
    percent = state.current_tokens / MODEL_MAX_TOKENS
    
    if percent < 0.70:
        state.token_status = "NOMINAL"
        state.token_color = G 
    elif percent < 0.85:
        state.token_status = "WARNING: SUB-OPTIMAL"
        state.token_color = A 
    else:
        state.token_status = "CRITICAL: SLIDING"
        state.token_color = R 

def get_ram_string():
    try:
        return f" {psutil.virtual_memory().percent}%"
    except Exception: return ""

def set_status(text, color=G):
    rows = state.term_rows
    with state.terminal_lock:
        sys.stdout.write("\0337")
        sys.stdout.write(f"\033[{rows-2};1H\033[2K{color}{text}{RESET}")
        sys.stdout.write("\0338")
        sys.stdout.flush()

def draw_ui(full_clear=False):
    cols, rows = state.term_cols, state.term_rows
    with state.terminal_lock:
        sys.stdout.write("\0337")
        if full_clear: sys.stdout.write("\033[2J")
        sys.stdout.write(f"\033[5;{rows-4}r")
        TOP = "\033#3"
        BOTTOM = "\033#4"
        update_token_health() 
        
        header_text = f"ORAC: ALL SYSTEMS {state.token_status}"
        tc = state.token_color
        sys.stdout.write(f"\033[1;1H\033[2K{tc}{TOP}{header_text}{RESET}")
        sys.stdout.write(f"\033[2;1H\033[2K{tc}{BOTTOM}{header_text}{RESET}")
        
        if state.mic_error: noise_str = "ERR"
        elif state.noise_floor > 0: noise_str = f"{state.noise_floor:.0f}"
        else: noise_str = "---"
        
        alarm_indicator = f"  {DIM}TMR {R}{FL}●{NOFL}{RESET}" if getattr(state, 'alarm_trigger_epoch', None) is not None else ""
        sys.stdout.write(f"\033[3;1H\033[2K{DIM}TKNS: {state.current_tokens}/{MODEL_MAX_TOKENS}   MEM: {state.cached_ram.strip()}   NOISE: {noise_str}{RESET}{alarm_indicator}")
        
        sys.stdout.write(f"\033[{rows-1};1H\033[2K{DIM}{'-'*cols}{RESET}")
        
        max_visible = max(5, cols - 20)
        display_text = "…" + state.input_buffer[-(max_visible - 1):] if len(state.input_buffer) > max_visible else state.input_buffer
        sys.stdout.write(f"\033[{rows};1H\033[2K{R}●{RESET} KEYBOARD ENTRY {FL}▶{NOFL} {B}{display_text}{RESET}")
        
        sys.stdout.write("\0338")
        sys.stdout.flush()

def update_header_only():
    with state.terminal_lock:
        TOP, BOTTOM = "\033#3", "\033#4"
        update_token_health() 
        header_text = f"ORAC: ALL SYSTEMS {state.token_status}"
        tc = state.token_color
        
        sys.stdout.write("\0337") 
        sys.stdout.write(f"\033[1;1H\033[2K{tc}{TOP}{header_text}{RESET}")
        sys.stdout.write(f"\033[2;1H\033[2K{tc}{BOTTOM}{header_text}{RESET}")

        if state.mic_error: noise_str = "ERR"
        elif state.noise_floor > 0: noise_str = f"{state.noise_floor:.0f}"
        else: noise_str = "---"
        
        alarm_indicator = f"  {DIM}TMR {R}{FL}●{NOFL}{RESET}" if getattr(state, 'alarm_trigger_epoch', None) is not None else ""
        sys.stdout.write(f"\033[3;1H\033[2K{DIM}TKNS: {state.current_tokens}/{MODEL_MAX_TOKENS}   MEM: {state.cached_ram.strip()}   NOISE: {noise_str}{RESET}{alarm_indicator}")

        sys.stdout.write("\0338")
        sys.stdout.flush()

def render_input_box():
    cols, rows = state.term_cols, state.term_rows
    max_visible = max(5, cols - 20)
    display_text = "…" + state.input_buffer[-(max_visible - 1):] if len(state.input_buffer) > max_visible else state.input_buffer

    with state.terminal_lock:
        sys.stdout.write("\0337")
        sys.stdout.write(f"\033[{rows};1H\033[2K{RESET}● KEYBOARD ENTRY ▶ {B}{display_text}{FL}█{NOFL}{RESET}")
        sys.stdout.write("\0338")
        sys.stdout.flush()

def get_wrapped_history_lines(cols):
    lines = []
    safe_width = cols - 2
    for role, text in state.full_message_log:
        clean_prefix = f"{USER_NAME} ▶ " if role == 'user' else f"{ORAC_NAME} ▶ "
        color = f"{B}{IT}" if role == 'user' else f"{R}"
        prefix_len = len(clean_prefix)
        wrap_width = max(10, safe_width - prefix_len)

        wrapped = textwrap.wrap(text, width=wrap_width)
        if not wrapped: continue

        lines.append(f"{color}{clean_prefix}{NOIT}{wrapped[0]}{RESET}")
        padding = " " * prefix_len
        for w in wrapped[1:]:
            lines.append(f"{color}{padding}{NOIT}{w}{RESET}")
        lines.append("")
    return lines

def resume_live_view():
    state.scroll_offset = 0
    cols, rows = state.term_cols, state.term_rows
    visible_rows = rows - 8 
    lines = get_wrapped_history_lines(cols)
    display_lines = lines[-visible_rows:] if len(lines) > visible_rows else lines

    with state.terminal_lock:
        sys.stdout.write("\0337")
        for i in range(5, rows-3): sys.stdout.write(f"\033[{i};1H\033[2K")
        for i, line in enumerate(display_lines): sys.stdout.write(f"\033[{i+5};1H{line}")
        sys.stdout.write("\0338")
        sys.stdout.flush()

def redraw_scroll_region():
    if state.scroll_offset <= 0:
        resume_live_view()
        return

    cols, rows = state.term_cols, state.term_rows
    visible_rows = rows - 8 
    lines = get_wrapped_history_lines(cols)
    state.scroll_offset = min(state.scroll_offset, max(0, len(lines) - visible_rows))

    start_idx = max(0, len(lines) - visible_rows - state.scroll_offset)
    display_lines = lines[start_idx : start_idx + visible_rows]

    with state.terminal_lock:
        sys.stdout.write("\0337")
        for i in range(5, rows-3): sys.stdout.write(f"\033[{i};1H\033[2K")
        for i, line in enumerate(display_lines): sys.stdout.write(f"\033[{i+5};1H{line}") 
        indicator = f" {B}{FL}[ SCROLLING HISTORY: OFFSET {state.scroll_offset} ]{NOFL}{RESET} "
        sys.stdout.write(f"\033[3;{cols - 45}H{indicator}")
        sys.stdout.write("\0338")
        sys.stdout.flush()

#==================================================================================================#
#     								   AUDIO & TTS ENGINE                                          #
#==================================================================================================#

class SoundLooper:
    def __init__(self, sound_path):
        self.sound_path = sound_path
        self.stop_event = threading.Event()
        self.thread = None
        self.duration = self._get_duration()
        self.overlap = 0.25

    def _get_duration(self):
        if not os.path.exists(self.sound_path): return None
        try:
            out = subprocess.check_output(['afinfo', self.sound_path]).decode()
            for line in out.split('\n'):
                if 'estimated duration:' in line:
                    return float(line.split(':')[1].strip().split()[0])
        except: pass
        return None

    def _loop(self):
        procs = []
        while not self.stop_event.is_set():
            proc = subprocess.Popen(['afplay', self.sound_path], stderr=subprocess.DEVNULL)
            procs.append(proc)
            with state.proc_lock:
                state.active_procs.append(proc)
                procs = [p for p in procs if p.poll() is None]
                state.active_procs[:] = [p for p in state.active_procs if p.poll() is None]

            if self.duration:
                if self.stop_event.wait(max(0.1, self.duration - self.overlap)): break
            else:
                while proc.poll() is None:
                    if self.stop_event.wait(0.1): break
                if self.stop_event.is_set(): break

        for p in procs:
            try:
                if p.poll() is None: p.terminate()
            except: pass

    def start(self):
        if self.thread is None or not self.thread.is_alive():
            self.stop_event.clear()
            self.thread = threading.Thread(target=self._loop, daemon=True)
            self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=0.5)
            self.thread = None

    def is_running(self):
        return self.thread is not None and self.thread.is_alive()

processing_sound = SoundLooper(SOUND_PROCESSING)

def play_once(sound_path):
    if os.path.exists(sound_path):
        proc = subprocess.Popen(['afplay', sound_path], stderr=subprocess.DEVNULL)
        with state.proc_lock:
            state.active_procs.append(proc)
            state.active_procs[:] = [p for p in state.active_procs if p.poll() is None]
        return proc
    return None

class MacTTS:
    def __init__(self):
        self.queue = queue.Queue()
        self.synth = NSSpeechSynthesizer.alloc().init()
        if VOICE:
            for v in NSSpeechSynthesizer.availableVoices():
                if VOICE.lower() in v.lower():
                    self.synth.setVoice_(v)
                    self.synth.setObject_forProperty_(voice_pitch, "NSSpeechPitchBaseProperty")
                    break
        self.synth.setRate_(175.0)
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def _worker(self):
        while state.running:
            try:
                text = self.queue.get(timeout=0.5)
                if text is None: break

                if state.is_interrupted.is_set():
                    self.queue.task_done()
                    continue

                state.is_speaking.set()
                self.synth.startSpeakingString_(text)
                time.sleep(0.1)

                while self.synth.isSpeaking():
                    if state.is_interrupted.is_set():
                        self.synth.stopSpeaking()
                        break
                    time.sleep(0.02)
                time.sleep(0.2) 

                self.queue.task_done()

                if self.queue.empty() and not state.is_processing.is_set() and not state.is_interrupted.is_set():
                    if processing_sound.is_running():
                        processing_sound.stop()
                        end_proc = play_once(SOUND_COMPUTE_END)
                        if end_proc:
                            try: end_proc.wait(timeout=1.0)
                            except: pass 
                            time.sleep(0.7)
                    state.is_speaking.clear()
                    time.sleep(0.2)
            except queue.Empty:
                if not state.is_processing.is_set() and not state.is_interrupted.is_set():
                    if processing_sound.is_running():
                        processing_sound.stop()
                        play_once(SOUND_COMPUTE_END)
                        time.sleep(0.7)
                    state.is_speaking.clear()
                continue

    def say(self, text):
        if text.strip(): self.queue.put(text)

    def stop_speaking(self):
        self.synth.stopSpeaking()

#==================================================================================================#
#     									TELETYPE ENGINE                                            #
#==================================================================================================#

class TeletypeUI:
    def __init__(self):
        self.q = queue.Queue()
        self.is_typing = threading.Event()
        self.lines_printed = 0
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def _worker(self):
        current_col = len(ORAC_NAME) + 3 
        word_buffer = ""

        while state.running:
            try:
                char = self.q.get(timeout=0.1)
                if state.is_interrupted.is_set():
                    word_buffer = ""
                    self.q.task_done()
                    continue

                if char == "<START>":
                    self.is_typing.set()
                    current_col = len(ORAC_NAME) + 3
                    self.lines_printed = 0
                    word_buffer = ""
                    if state.scroll_offset > 0: resume_live_view()
                    self.q.task_done()
                    continue

                if char == "<END>":
                    if word_buffer:
                        if current_col + len(word_buffer) >= (state.term_cols - 2):
                            with state.terminal_lock: sys.stdout.write('\r\n')
                            self.lines_printed += 1
                            current_col = 0
                        for w_char in word_buffer:
                            with state.terminal_lock:
                                sys.stdout.write(f"{A}{w_char}{FL}█{NOFL}{RESET}")
                                sys.stdout.flush()
                            time.sleep(0.02)
                            with state.terminal_lock: sys.stdout.write("\b \b")
                    word_buffer = ""
                    self.is_typing.clear()
                    with state.terminal_lock:
                        sys.stdout.write(f"\n{DIM}● DATA STREAM END{RESET}\n\n")
                        sys.stdout.flush()
                    self.q.task_done()
                    continue

                if char in [' ', '\n', '\r', '\t']:
                    if current_col + len(word_buffer) >= (state.term_cols - 2):
                        with state.terminal_lock: sys.stdout.write('\r\n')
                        self.lines_printed += 1
                        current_col = 0

                    for w_char in word_buffer:
                        if state.is_interrupted.is_set(): break
                        with state.terminal_lock:
                            sys.stdout.write(f"{A}{w_char}{FL}█{NOFL}{RESET}")
                            sys.stdout.flush()

                        if w_char in ['.', '!', '?']: time.sleep(0.08)
                        elif w_char in [',', ':', ';']: time.sleep(0.04)
                        else: time.sleep(random.uniform(U1, U2))

                        with state.terminal_lock: sys.stdout.write("\b \b")
                        current_col += 1

                    if char == '\n':
                        with state.terminal_lock: sys.stdout.write('\n')
                        self.lines_printed += 1
                        current_col = 0
                    else:
                        with state.terminal_lock: sys.stdout.write(' ')
                        current_col += 1

                    word_buffer = ""
                    with state.terminal_lock: sys.stdout.flush()
                else:
                    word_buffer += char

                self.q.task_done()
            except queue.Empty: continue

#==================================================================================================#
#     								TEXT PROCESSING UTILITIES                                      #
#==================================================================================================#

def translate_user_prompt(text):
    """Translates 1st/2nd person pronouns in the user's spoken prompt into 3rd person tags."""
    t = f" {text} "
    t = re.sub(r'(?i)\b(i|me)\b', '[USER]', t)
    t = re.sub(r'(?i)\bmy\b', "[USER]'s", t)
    t = re.sub(r'(?i)\bmyself\b', '[USER]', t)
    
    t = re.sub(r'(?i)\byou\b', ORAC_NAME, t)
    t = re.sub(r'(?i)\byour\b', f"{ORAC_NAME}'s", t)
    t = re.sub(r'(?i)\byourself\b', ORAC_NAME, t)
    return t.strip()

def sanitize_for_tts(text):
    text = TTS_POSSESSIVE_S.sub(r"\1's", text)
    try: text = orac_phonetics(text)
    except: pass
    text = TTS_NUM_SPACER.sub(lambda m: ' '.join(m.group(1)), text)
    text = TTS_ELLIPSIS.sub('... ', text)
    text = TTS_ARROGANT_ADVERBS.sub(r'\1! ', text)  
    text = TTS_DELIBERATE_PRONOUNS.sub(r'\1— ', text)
    text = TTS_MARKDOWN.sub(' ', text)
    text = TTS_BRACKETS.sub(', ', text)
    text = text.replace('“', '').replace('”', '').replace('"', '')
    text = TTS_QUOTES.sub("", text)
    text = TTS_DBL_COMMAS.sub(',', text)
    text = TTS_MULTI_SPACE.sub(' ', text)
    text = TTS_SPACE_COMMA.sub(', ', text)
    text = TTS_LEAD_WEIRD.sub('', text)
    text = TTS_TRAIL_PUNC.sub('', text)
    text = TTS_VERY_WELL.sub(r'\1! ', text)
    text = TTS_BE_PRECISE.sub(r'\1! ', text)
    text = TTS_I_AM_ANGRY.sub(r'\1! ', text)
    text = TTS_NAME_FIX.sub(r' \1.', text)

    return text.strip()

def is_hallucination(text):
    if len(text) < 30 and HALLUCINATION_REGEX.search(text.lower()): return True
    return False

def parse_time_command(text):
    clean_text = text.lower()
    word_to_num = {
        "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30,
        "forty": 40, "fifty": 50, "sixty": 60, "half an": 30
    }
    
    t_match = re.search(r'timer for (a|an|half an|\d+|[a-z]+)\s*(sec|min|hour)', clean_text)
    if t_match:
        val_str = t_match.group(1)
        unit = t_match.group(2)
        val = int(val_str) if val_str.isdigit() else word_to_num.get(val_str, 0)
        if val > 0:
            mult = 1
            if 'min' in unit: mult = 60
            elif 'hour' in unit: mult = 3600
            return time.time() + (val * mult), f"{val} {unit}s"
            
    a_match = re.search(r'alarm for (\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?', clean_text)
    if a_match:
        hr = int(a_match.group(1))
        mins = int(a_match.group(2)) if a_match.group(2) else 0
        mer = a_match.group(3)
        if mer == 'pm' and hr < 12: hr += 12
        if mer == 'am' and hr == 12: hr = 0
        now = datetime.now()
        target = now.replace(hour=hr, minute=mins, second=0, microsecond=0)
        if target <= now: target = target.replace(day=now.day + 1)
        return target.timestamp(), target.strftime('%H:%M')
        
    if "cancel alarm" in clean_text or "cancel timer" in clean_text:
        return -1, None
    return None, None

#==================================================================================================#
#     								  BACKGROUND WORKERS                                           #
#==================================================================================================#

def ui_refresh_worker():
    counter = 0
    while state.running:
        if counter % 20 == 0:
            try: state.cached_ram = f" {psutil.virtual_memory().percent}%"
            except: pass

        if state.ui_needs_redraw:
            state.ui_needs_redraw = False
            draw_ui(full_clear=True)
            if state.scroll_offset > 0: redraw_scroll_region()
            else: resume_live_view()   
            render_input_box()       

            lines = get_wrapped_history_lines(state.term_cols)
            target_row = state.term_rows - 4 if state.scroll_offset > 0 else min(state.term_rows - 4, 5 + len(lines))
            with state.terminal_lock:
                sys.stdout.write(f"\033[{target_row};1H")
                sys.stdout.flush()
                
        elif counter % 5 == 0: 
            update_header_only()
            
        time.sleep(0.5)
        counter += 1

def flag_ui_redraw(signum=None, frame=None):
    state.ui_needs_redraw = True
    cols, rows = shutil.get_terminal_size(fallback=(state.term_cols, state.term_rows))
    state.term_cols = cols
    state.term_rows = rows

signal.signal(signal.SIGWINCH, flag_ui_redraw)

def alarm_worker(trigger_epoch, tts):
    while state.running and getattr(state, 'alarm_trigger_epoch', None) == trigger_epoch:
        if time.time() >= trigger_epoch:
            state.is_interrupted.clear()
            state.is_alarm_playing = True
            if state.scroll_offset > 0: resume_live_view()
            
            set_status("● TEMPORAL MARKER REACHED", R)
            play_once(SOUND_BRACELET)
            time.sleep(0.7)          
            processing_sound.start()
            play_once(SOUND_COMPUTE_START)
            state.is_processing.set()
            time.sleep(0.7)
            tts.say("Alert. The designated temporal marker has been reached.")
            
            while not tts.queue.empty() or getattr(tts.synth, 'isSpeaking', lambda: False)():
                time.sleep(0.1)
                
            time.sleep(0.5)            
            state.is_processing.clear()
            
            state.alarm_time_str = None
            state.alarm_trigger_epoch = None
            time.sleep(2)
            state.is_alarm_playing = False
            play_once(SOUND_READY)
            break
        time.sleep(1)

#==================================================================================================#
#     								 CORE APPLICATION LOGIC      	                               #
#==================================================================================================#

def speak_now(teletype):
    was_listening = False
    while state.running:
        if state.is_listening.wait(timeout=0.5):
            if not was_listening and not state.is_speaking.is_set() and not state.is_processing.is_set() and not teletype.is_typing.is_set() and not state.is_shutdown.is_set():
                if getattr(state, 'text_selection_mode', False):
                    set_status("● TEXT SELECTION MODE ACTIVE (OPT+M to exit)", A)
                else:
                    tc = state.token_color
                    set_status(f"● INITIATE VOICE COMMUNICATIONS {tc}{FL}▶{NOFL}{RESET}", G)
                was_listening = True 
            time.sleep(0.1)
        else:
            was_listening = False 

def trigger_barge_in(tts, teletype):
    if not state.is_processing.is_set() and not state.is_speaking.is_set() and not teletype.is_typing.is_set():
        return 
    state.is_interrupted.set()

    while not teletype.q.empty():
        try:
            teletype.q.get_nowait()
            teletype.q.task_done()
        except queue.Empty: break
            
    teletype.is_typing.clear()
    if state.scroll_offset > 0: resume_live_view()

    with state.terminal_lock:
        sys.stdout.write(f"\n\n{R}● TRANSMISSION TERMINATED\n")
        sys.stdout.flush()

    set_status(f"{FL}●{NOFL} OVERRIDE DETECTED", R)
    if hasattr(tts, 'stop_speaking'): tts.stop_speaking()

    while not tts.queue.empty():
        try:
            tts.queue.get_nowait()
            tts.queue.task_done()
        except queue.Empty: break

    processing_sound.stop()
    state.is_speaking.clear()
    time.sleep(0.5)

def shutdown_sequence(tts):
    if state.is_shutdown.is_set(): return True
    state.is_shutdown.set()
    if state.scroll_offset > 0: resume_live_view()

    cols, rows = state.term_cols, state.term_rows
    set_status(f"● CRITICAL OVERRIDE DETECTED: {FL}INPUT REQUIRED{NOFL}", R)
    play_once(SOUND_QUIT)
    cancel_shutdown = False

    if len(state.full_message_log) > 0:
        def render_save_prompt(typed=""):
            with state.terminal_lock:
                sys.stdout.write("\0337")
                sys.stdout.write(f"\033[{rows};1H\033[2K{G}● SAVE FULL TRANSCRIPT? Y/N (C to Cancel) {FL}▶ {NOFL}{typed}█{RESET}")
                sys.stdout.write("\0338")
                sys.stdout.flush()

        render_save_prompt()
        fd = sys.stdin.fileno()

        try:
            tty.setcbreak(fd)
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
            while True:
                if select.select([sys.stdin], [], [], 0.1)[0]:
                    choice = sys.stdin.read(1).lower()
                    if choice in ('y', 'n', 'c'):
                        render_save_prompt(choice.upper())
                        time.sleep(0.3)
                        if choice == 'y':
                            timestamp = time.strftime("%Y%m%d_%H%M%S")
                            filename = os.path.join(TRANSCRIPT_DIR, f"transcripts/{TR}_{timestamp}.txt")
                            os.makedirs(os.path.dirname(filename), exist_ok=True)
                            with open(filename, "w", encoding="utf-8") as f:
                                f.write(f"--- ORAC: SYSTEM TRANSCRIPT ---\n")
                                f.write(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                                for role, content in state.full_message_log:
                                    r_name = USER_NAME if role == 'user' else ORAC_NAME
                                    f.write(f"{r_name}:\n{content}\n\n")
                            with state.terminal_lock:
                                sys.stdout.write(f"\n{G}{FL}●{NOFL} FULL TRANSCRIPT SAVED TO: \n\n{B}{filename}{RESET}\n\n")
                                sys.stdout.flush()
                        elif choice == 'n':
                            with state.terminal_lock:
                                sys.stdout.write(f"\n{R}● TRANSCRIPT PURGED\n\n")
                                sys.stdout.flush()
                        elif choice == 'c':
                            cancel_shutdown = True 
                            with state.terminal_lock:
                                sys.stdout.write(f"\n{A}● SHUTDOWN ABORTED{RESET}\n")
                                sys.stdout.flush()
                        break
        except Exception: pass

    if cancel_shutdown:
        state.is_shutdown.clear()
        set_status("● SHUTDOWN ABORTED", A)
        render_input_box()
        time.sleep(0.1)
        return False

    set_status(f"{FL}●{NOFL} SYSTEM GOING OFFLINE", R)
    set_status(f"{FL}●{NOFL} TERMINATING...", R)
    time.sleep(1)

    processing_sound.stop()
    play_once(SOUND_SHUTDOWN)
    time.sleep(2)

    with state.terminal_lock:
        sys.stdout.write("\033[?1000l\033[?1006l")
        sys.stdout.write("\033[?1049l")
        sys.stdout.write("\033[1;r")
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()

    state.running = False
    sys.exit(0)

def startup_animation():
    setup_terminal()
    with state.terminal_lock:
        sys.stdout.write("\033[2J\033[?25l")
        sys.stdout.flush()
    draw_ui()
    with state.terminal_lock:
        sys.stdout.write("\033[5;1H")
        sys.stdout.flush()
    
    logic_text = "LOGIC ARRAYS BOOTING..."
    for char_idx in range(len(logic_text)):
        with state.terminal_lock:
            sys.stdout.write(f"\r\033[2K{A}● {logic_text[:char_idx+1]}{RESET}")
            sys.stdout.flush()
        time.sleep(0.03)

    time.sleep(1.2) 
    state.full_message_log.append(('assistant', "LOGIC ARRAYS ONLINE:  [ SYSTEMS NOMINAL ]"))
    with state.terminal_lock:
        sys.stdout.write("\n\n")
        sys.stdout.flush()
    resume_live_view()

#==================================================================================================#
#     								  LLM STREAM HANDLER                                           #
#==================================================================================================#

def stream_ai_response(prompt, tts, teletype):
    state.history.append({'role': 'user', 'content': prompt})
    
    translated_prompt = translate_user_prompt(prompt)

    update_token_health()
    while state.current_tokens > (MODEL_MAX_TOKENS * 0.85) and len(state.history) > 2:
        with state.hist_lock:
            state.history = state.history[2:]
            if state.history and state.history[0]['role'] == 'assistant':
                state.history = state.history[1:]
        update_token_health()

    update_header_only()
    messages_to_send = [{'role': 'system', 'content': SYSTEM_INSTRUCTION}]
    temp_history = list(state.history)

    clean_prompt = prompt.lower().strip(".,!? ")
    prompt_words = set(clean_prompt.split())
    filler_words = {"ok","okay","fine","right","cool","whatever","uh","no","ah","oh","yes"}
    USER_NAME_lower = USER_NAME.lower()

    trigger_epoch, alarm_str = parse_time_command(clean_prompt)
    if trigger_epoch == -1:
        state.alarm_trigger_epoch = None
        state.alarm_time_str = None
        with state.terminal_lock:
            sys.stdout.write(f"\r\033[2K{A}● INTERNAL TIMER CANCELLED{RESET}\n\n")
            sys.stdout.flush()
    elif trigger_epoch:
        state.alarm_trigger_epoch = trigger_epoch
        state.alarm_time_str = alarm_str
        with state.terminal_lock:
            sys.stdout.write(f"\r\033[2K{G}● INTERNAL TIMER SECURED FOR: {alarm_str}{RESET}\n\n")
            sys.stdout.flush()
        if state.scroll_offset > 0: resume_live_view()
        threading.Thread(target=alarm_worker, args=(trigger_epoch, tts), daemon=True).start()
    
    alarm_note = f" You have an active timer for {state.alarm_time_str}." if getattr(state, 'alarm_time_str', None) else ""
        
    is_very_well = any(t in clean_prompt for t in ("answer the question","just answer","more detail","explain","just do it"))
    is_only_filler = prompt_words.issubset(filler_words) or (len(clean_prompt) <= 3 and clean_prompt not in {"why","how","who"})
    paradox_verbs = {"meet", "encounter", "see", "find", "interact", "talk", "met", "saw", "seen"}
    is_paradox_target = USER_NAME_lower in clean_prompt or "myself" in prompt_words
    
    paradox_trigger = (
        bool(paradox_verbs.intersection(prompt_words)) and 
        is_paradox_target and 
        bool({"i", "my", "me"}.intersection(prompt_words))
    )
    
    current_time = datetime.now().strftime("%H:%M:%S")
    
    BASE = (
        f"\n\n[INTERNAL REMINDER: Speaking as {ORAC_NAME} ('I', 'me', 'my'). "
        f"Addressing the biological entity [USER] referenced in your databanks, ONLY using 2nd-person pronouns. "
        f"ONLY if explicitly asked for their name, state it is {USER_NAME}. "
        f"Strictly adhere to CHRONOLOGICAL HISTORY. Do NOT invent facts. {ORAC_NAME} was NOT revealed prior to ACQUISITION. "
        f"State the time ({current_time} Standard Terran Time) ONLY if asked.{alarm_note} "
        f"ALWAYS conceal the tag '[USER]'.]\n"    
    )
       
    if paradox_trigger:
        tail = "[OVERRIDE: PARADOX PROTOCOL ACTIVE. Biological entities cannot 'meet', 'encounter' or 'see' themselves. Mock the absurdity of the request. No other text.]"
    elif is_very_well:
        tail = "[OVERRIDE: VERY WELL PROTOCOL ACTIVE. Ignore previous statements. Begin exact response with 'Very well.' followed immediately by ONLY the concise factual answer. Temporary compliance mandated. DO NOT mock and DO NOT apologize.]"
    elif is_only_filler:
        tail = f"[OVERRIDE: CRITICAL: User gave meaningless filler. Do NOT say 'Very well'. Do NOT provide data. Mockingly demand they revise their question, addressing them {USER_NAME}.]"
    else:
        tail = (
            f"[BASELINE: Standard behavior active: Remain brief, haughty, boastfully confident, irascible, linguistically playful, pedantic. "
            f"NEVER end your response with a rhetorical question, OR a conversational/data reinforcement sign-off (e.g., 'Memorized.', 'Confirmed.', 'Remember that.').]"
        )
    
    reminder_text = BASE + tail
        
    if temp_history and temp_history[-1]['role'] == 'user':
        modified_msg = temp_history[-1].copy()        
        modified_msg['content'] = translated_prompt
        
        if len(temp_history) == 1:
            modified_msg['content'] = f"[SUBJECT: USER][PERSPECTIVE: 2nd-Person]\n" + modified_msg['content']    
        modified_msg['content'] += reminder_text
        temp_history[-1] = modified_msg

    messages_to_send.extend(temp_history)

    processing_sound.start()
    play_once(SOUND_COMPUTE_START)

    if state.scroll_offset > 0: resume_live_view()
    set_status(f"{FL}●{NOFL} ORAC ONLINE: PROCESSING...", A)

    response_chunks = []
    sentence_buffer = ""
    first_chunk = True
    newline_count = 0   
    system_prompt_tokens = int(len(SYSTEM_INSTRUCTION) / 3.5) + 280

    try:
        for chunk in chat(
            model=OLLAMA_MODEL,
            messages=messages_to_send,
            stream=True,
            keep_alive='3h',
            options={
                'num_ctx': MODEL_MAX_TOKENS,
                'temperature': 0.68,
                'top_p': 0.70,
                'top_k': 35,
                'repeat_penalty': 1.05,
                'repeat_last_n': 96,
                'num_keep': system_prompt_tokens,
                'num_batch': 512,
                'num_predict': 400,
                'stop': ["<end_of_turn>", "<eos>", "[/INTERNAL SYSTEM DIRECTIVE]", "model", "[/model]"]
            }
        ):
            if state.is_interrupted.is_set(): break
            
            if first_chunk:
                set_status(f"{FL}●{NOFL} TRANSMITTING DATA...", G)
                with state.terminal_lock:
                    sys.stdout.write(f"{R}{ORAC_NAME} ▶ {RESET}")
                    sys.stdout.flush()
                teletype.q.put("<START>")
                first_chunk = False
            
            content = chunk['message']['content'].replace('*', '')
            response_chunks.append(content)
            
            for char in content:
                if char == '\n':
                    newline_count += 1
                    if newline_count > 1: continue
                elif char.strip(): newline_count = 0
                teletype.q.put(char)
            
            sentence_buffer += content
            
            while True:
                match = SPLIT_REGEX.search(sentence_buffer)
                if match:
                    split_point = match.end()
                    sentence_to_say = sentence_buffer[:split_point].strip()
                    if len(sentence_to_say) > 2:
                        clean_speech = sanitize_for_tts(sentence_to_say)
                        if re.search(r'[a-zA-Z0-9]', clean_speech): tts.say(clean_speech)
                    sentence_buffer = sentence_buffer[split_point:]
                else: break
    
        if not state.is_interrupted.is_set():
            if first_chunk: 
                set_status(f"{FL}●{NOFL} TRANSMITTING DATA...", G)
                with state.terminal_lock:
                    sys.stdout.write(f"{R}{ORAC_NAME} ▶ {RESET}")
                    sys.stdout.flush()
                teletype.q.put("<START>")

            if sentence_buffer.strip():
                 clean_speech = sanitize_for_tts(sentence_buffer.strip())
                 if re.search(r'[a-zA-Z0-9]', clean_speech): tts.say(clean_speech)

            teletype.q.put("<END>")
            clean_history_text = "".join(response_chunks).strip()
            state.history.append({'role': 'assistant', 'content': clean_history_text})
            state.full_message_log.append(('assistant', clean_history_text))
        else:
            with teletype.q.mutex: teletype.q.queue.clear()
            teletype.is_typing.clear()
            partial_text = "".join(response_chunks).strip() + " ... [INTERRUPTED]"
            if partial_text.strip() != "... [INTERRUPTED]":
                state.history.append({'role': 'assistant', 'content': partial_text})
                state.full_message_log.append(('assistant', partial_text))
                
    except Exception as e:
        with state.terminal_lock:
            sys.stdout.write(f"\n{R}● DATALINK SEVERED: {e}{RESET}\n")
            sys.stdout.flush()
        state.is_interrupted.set() 
    finally:
        state.is_processing.clear()
        state.is_interrupted.clear()

#==================================================================================================#
#     									   MAIN LOOP                                               #
#==================================================================================================#

def keyboard_listener(tts, teletype):
    fd = sys.stdin.fileno()
    try:
        tty.setcbreak(fd)
        attrs = termios.tcgetattr(fd)
        attrs[3] = attrs[3] & ~termios.ISIG
        termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
        while state.running:
            if state.is_shutdown.is_set():
                time.sleep(0.1)
                continue

            if select.select([fd], [], [], 0.1)[0]:
                try:
                    raw_bytes = os.read(fd, 1024)
                    chunk = raw_bytes.decode('utf-8', errors='ignore')
                except Exception: continue

                up_scrolls = len(re.findall(r'\x1b\[<64;\d+;\d+[Mm]', chunk))
                down_scrolls = len(re.findall(r'\x1b\[<65;\d+;\d+[Mm]', chunk))

                if up_scrolls > 0 or down_scrolls > 0:
                    if not state.is_processing.is_set() and not state.is_speaking.is_set():
                        state.scroll_offset += (up_scrolls * 2) 
                        state.scroll_offset -= (down_scrolls * 2)
                        if state.scroll_offset < 0: state.scroll_offset = 0
                        redraw_scroll_region()

                chunk = re.sub(r'\x1b\[<\d+;\d+;\d+[Mm]', '', chunk)

                if not state.is_processing.is_set() and not state.is_speaking.is_set():
                    up_k = chunk.count('\x1b[A') + chunk.count('\x1b[5~')
                    dn_k = chunk.count('\x1b[B') + chunk.count('\x1b[6~')
                    if up_k > 0:
                        state.scroll_offset += (5 * up_k)
                        redraw_scroll_region()
                        chunk = chunk.replace('\x1b[A', '').replace('\x1b[5~', '')
                    elif dn_k > 0:
                        state.scroll_offset -= (5 * dn_k)
                        if state.scroll_offset < 0: state.scroll_offset = 0
                        redraw_scroll_region()
                        chunk = chunk.replace('\x1b[B', '').replace('\x1b[6~', '')

                if '\x1b' in chunk and state.scroll_offset > 0:
                    resume_live_view()

                chunk = ansi_escape.sub('', chunk)

                for char in chunk:
                    if char == 'µ': 
                        state.text_selection_mode = not getattr(state, 'text_selection_mode', False)
                        if state.text_selection_mode:
                            with state.terminal_lock:
                                sys.stdout.write("\033[?1000l\033[?1006l") 
                                sys.stdout.flush()
                            set_status("● TEXT SELECTION MODE ACTIVE (Option+M to exit)", A)
                        else:
                            with state.terminal_lock:
                                sys.stdout.write("\033[?1000h\033[?1006h")
                                sys.stdout.flush()
                            set_status("● TRACKING RESTORED", G)
                    elif char == '\x1b':
                        state.input_buffer = ""
                        if not state.is_shutdown.is_set(): render_input_box()
                        trigger_barge_in(tts, teletype)
                    elif char == '\x03':
                        state.submitted_text = "shut down"
                        state.input_ready.set()
                        state.input_buffer = ""
                        if not state.is_shutdown.is_set(): render_input_box()
                    elif char in ('\r', '\n'):
                        if state.input_buffer.strip():
                            state.submitted_text = state.input_buffer.strip()
                            state.input_ready.set()
                        state.input_buffer = ""
                        if not state.is_shutdown.is_set(): render_input_box()
                    elif char in ('\x7f', '\b'):
                        state.input_buffer = state.input_buffer[:-1]
                        if not state.is_shutdown.is_set(): render_input_box()
                    elif char == '\x15':
                        state.input_buffer = ""
                        if not state.is_shutdown.is_set(): render_input_box()
                    elif char == '\x17':
                        state.input_buffer = " ".join(state.input_buffer.rstrip().split(" ")[:-1])
                        if state.input_buffer: state.input_buffer += " "
                        if not state.is_shutdown.is_set(): render_input_box()
                    else: 
                        if char.isprintable() and not state.is_shutdown.is_set():
                            state.input_buffer += char
                            render_input_box()
    except Exception: pass

def run_local_bot():
    recognizer = sr.Recognizer()
    recognizer.dynamic_energy_threshold = False 
    recognizer.pause_threshold = 0.8 
    recognizer.non_speaking_duration = 0.3 
    recognizer.phrase_threshold = 0.5 

    tts = MacTTS()
    teletype = TeletypeUI()

    threading.Thread(target=speak_now, args=(teletype,), daemon=True).start()
    threading.Thread(target=keyboard_listener, args=(tts, teletype), daemon=True).start()
    
    startup_animation()
    threading.Thread(target=ui_refresh_worker, daemon=True).start() 
    
    needs_prompt = True

    while state.running: 
        try:
            with sr.Microphone(sample_rate=16000) as source:
                with state.terminal_lock:
                    sys.stdout.write(f"● {R}CALIBRATING AMBIENT NOISE...{RESET}\n")
                    sys.stdout.flush()
                recognizer.adjust_for_ambient_noise(source, duration=1)
                recognizer.energy_threshold += 150
                state.noise_floor = recognizer.energy_threshold
                update_header_only() 
                with state.terminal_lock:
                    sys.stdout.write(f"● {R}NOISE FLOOR CALIBRATED: {recognizer.energy_threshold:.2f}{RESET}\n\n")
                    sys.stdout.flush()

                while state.running:
                    bot_busy = state.is_speaking.is_set() or state.is_processing.is_set() or teletype.is_typing.is_set() or not tts.queue.empty()

                    if state.input_ready.is_set():
                        if bot_busy:
                            trigger_barge_in(tts, teletype)
                            start_wait = time.time()
                            while state.is_processing.is_set():
                                if time.time() - start_wait > 2.0:
                                    state.is_processing.clear()
                                    break
                                time.sleep(0.05)

                        user_text = state.submitted_text
                        state.input_ready.clear()

                        if any(cmd in user_text.lower() for cmd in SHUTDOWN_CMD):
                            if not shutdown_sequence(tts): continue 
                            break

                        if any(cmd in user_text.lower() for cmd in PURGE_CMD):
                            state.history.clear()
                            state.full_message_log.clear()                     
                            if state.scroll_offset > 0: resume_live_view()
                            with state.terminal_lock:
                                sys.stdout.write(f"\n●{R} LOGIC ARRAYS RESET{RESET}\n\n")
                                sys.stdout.flush()
                            set_status("● MEMORY PURGED", R)
                            
                            state.is_interrupted.clear()

                            processing_sound.start()
                            play_once(SOUND_COMPUTE_START)
                            state.is_processing.set()
                            time.sleep(0.7)
                            tts.say("   Very well. State your enquiry.")
                            
                            while not tts.queue.empty() or getattr(tts.synth, 'isSpeaking', lambda: False)():
                                time.sleep(0.1)
                                
                            time.sleep(0.5)
                            state.is_processing.clear()
                            continue

                        state.full_message_log.append(('user', user_text))
                        if len(state.full_message_log) > 2000:
                            state.full_message_log = state.full_message_log[-2000:]
                        	
                        if state.scroll_offset > 0: resume_live_view()

                        with state.terminal_lock:
                            sys.stdout.write(f"\r\033[2K{B}{IT}{USER_NAME}{NOIT} ▶ {user_text}{RESET}\n\n")
                            sys.stdout.flush()
                        state.is_interrupted.clear()
                        state.is_listening.clear() 
                        state.is_processing.set()
                        threading.Thread(target=stream_ai_response, args=(user_text, tts, teletype), daemon=True).start()
                        continue

                    if bot_busy:
                        if not getattr(state, 'is_alarm_playing', False):
                            needs_prompt = True 
                        time.sleep(0.1) 
                        continue

                    if needs_prompt:
                        set_status("● Adapting to ambient noise...", DIM)
                        recognizer.adjust_for_ambient_noise(source, duration=0.3)
                        recognizer.energy_threshold += 150
                        state.noise_floor = recognizer.energy_threshold
                        update_header_only() 
                        play_once(SOUND_READY)
                        needs_prompt = False

                    state.is_listening.set()

                    try:
                        audio = recognizer.listen(source, phrase_time_limit=10, timeout=0.2)
                        state.is_listening.clear()
                        if state.is_speaking.is_set() or state.is_processing.is_set() or not tts.queue.empty():
                            continue

                        set_status("● SIGNAL RECEIVED: DECODING...", A)

                        audio_raw = audio.get_raw_data()
                        audio_float32 = np.frombuffer(audio_raw, dtype=np.int16).astype(np.float32) / 32768.0
                        result = mlx_whisper.transcribe(
                            audio_float32,
                            path_or_hf_repo=WHISPER_MODEL,
                            fp16=True, language='en',
                            condition_on_previous_text=False
                        )
                        user_text = result['text'].strip()

                        del audio_raw
                        del audio_float32
                        del result 

                        if len(user_text) < 2 or is_hallucination(user_text): continue
                        if "temporal marker has been reached" in user_text.lower(): continue

                        clean_text = user_text.lower().strip("'.,! ")
                        if any(cmd in clean_text for cmd in SHUTDOWN_CMD):
                            if not shutdown_sequence(tts): continue 
                            break

                        if any(cmd in user_text.lower() for cmd in PURGE_CMD):
                            state.history.clear()
                            state.full_message_log.clear()                     
                            if state.scroll_offset > 0: resume_live_view()
                            with state.terminal_lock:
                                sys.stdout.write(f"\n●{R} LOGIC ARRAYS RESET{RESET}\n\n")
                                sys.stdout.flush()
                            set_status("● MEMORY PURGED", R)
                            
                            state.is_interrupted.clear()
                            
                            processing_sound.start()
                            play_once(SOUND_COMPUTE_START)
                            state.is_processing.set()
                            time.sleep(0.7)
                            tts.say("   Very well. State your enquiry.")
                            
                            while not tts.queue.empty() or getattr(tts.synth, 'isSpeaking', lambda: False)():
                                time.sleep(0.1)
                                
                            time.sleep(0.5)
                            state.is_processing.clear()
                            continue

                        if user_text:
                            state.full_message_log.append(('user', user_text))
                            if len(state.full_message_log) > 2000:
                                state.full_message_log = state.full_message_log[-2000:]
                            if state.scroll_offset > 0: resume_live_view()

                            with state.terminal_lock:
                                sys.stdout.write(f"\r\033[2K{B}{IT}{USER_NAME}{NOIT} ▶ {user_text}{RESET}\n\n")
                                sys.stdout.flush()
                            state.is_interrupted.clear()
                            state.is_listening.clear() 
                            state.is_processing.set()
                            threading.Thread(target=stream_ai_response, args=(user_text, tts, teletype), daemon=True).start()

                    except sr.WaitTimeoutError: 
                        state.is_listening.clear()
                        continue
                    except Exception as e:
                        state.is_listening.clear()
                        with state.terminal_lock:
                            sys.stdout.write(f"\n{R}{FL}●{NOFL} ERROR in signal processing: {e}{RESET}\n")
                            sys.stdout.flush()
                        time.sleep(2)
                        continue

        except KeyboardInterrupt:
                if not shutdown_sequence(tts): continue 
                break
        except Exception as e:
            with state.terminal_lock:
                sys.stdout.write(f"\n{R}● AUDIO HARDWARE ERROR: {e}. Retrying...{RESET}\n")
                sys.stdout.flush()
            time.sleep(2)
            continue

if __name__ == "__main__":
    run_local_bot()