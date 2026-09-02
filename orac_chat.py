import atexit
import contextlib
import mlx.core as mx
import mlx_whisper
import numpy as np
import objc
import os
import psutil
import queue
import random
import re
import requests
import select
import shutil
import signal
import speech_recognition as sr
import subprocess
import sys
import termios
import textwrap
import threading
import time
import tty

from AppKit import NSSpeechSynthesizer, NSSound
from datetime import datetime, timedelta
from ollama import chat
from tokenizers import Tokenizer

sys.dont_write_bytecode = True # Restrict creation of Python Cache

from orac_data_core import data_core
from orac_personality import orac_personality
from orac_phonetics import orac_phonetics

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


#==================================================================================================#
#    					     ORAC-VOICE v1.5.7 (Lore friendly VoiceChat)                           #
#                                     gemma4:12b-mlx Optimized                                     #
#          						  Copyright © 2026 Caroline Mayne                                  #
#         						 https://github.com/CarolinaJones/                                 #
#==================================================================================================#

#------------------------------------#
#      USER CHANGEABLE VARIABLES     #
#------------------------------------#

USER_NAME = "Jenna" 								# USER Name and Identity
ORAC_NAME = "ORAC"									# ORAC's Name

TELETYPE_MODE = True                                # Set False for "Compact" mode (Voice only, minimal 8-row UI)
DEBUG_START = 0										# Start with Debug Mode enabled (1 = Yes  0 = No)

VOICE = "" 			# Leave blank to use the "System Voice" - This allows for SIRI/Personal Voices
voice_pitch = 72 	# Only works on SYNTH voices and not SIRI/Personal voices
S_RATE = 182		# Synth Speech Rate

U1 = 0.038											# Teletype Speed
U2 = 0.042											# Teletype Uniformity

TRANSCRIPT_DIR = ''			                        # Set location. Default is within project folder
TR = "ORAC_Transcript_CM" 							# Transcript Name Prefix (Date will be added)

# TERMINAL SETTINGS #

TERMINAL_PROFILE = "Homebrew"						# Terminal Profile
TERMINAL_FONT = "Monaco"							# Font Name
TERMINAL_FONT_SIZE = 18								# Font Size
TERMINAL_COLS = 90									# Window Width
TERMINAL_ROWS = 25 if TELETYPE_MODE else 8			# Dynamic Window Height

#==================================================================================================#
#              IT SHOULD NOT BE NECESSARY TO CHANGE ANYTHING BELOW THIS BOX			    		   #
#==================================================================================================#
		
OLLAMA_MODEL = 'gemma4:12b-mlx' 					# gemma4:12b-mlx
#OLLAMA_MODEL = 'gemma4:31b-cloud'					# Cloud based gemma4

MODEL_MAX_TOKENS = 10240							# MAX TOKENS for STATUS Predict & NUM_CTX
CHARS_PER_TOKEN = 4.18								# For UI Health Bar estimation fallback
RAM_CHECK_INTERVAL = 10.0							# Check RAM usage for Header
HEADER_UPDATE_INTERVAL = 5.0						# Update Header Interval

# ANSII PALETTES, CURSORS & KEY 'MODE' DETECTS, SOUND FX & TOKENIZER PATHS #

G, A, R, B = "\033[38;5;46m", "\033[38;5;214m", "\033[38;5;196m", "\033[1;37m"
FL, NOFL, DIM, RESET = "\033[5m", "\033[25m", "\033[2m", "\033[0m"
IT, NOIT = "\x1B[3m","\x1B[23m"

MODE_KEYS = {
    'dagger': ['†', '\u2020', '\x1bt', '\x1bT'],  # Option+T (Literal, Unicode, or Esc+t)
    'mu':     ['µ', '\u00b5', '\x1bm', '\x1bM'],  # Option+M (Literal, Unicode, or Esc+m)
    'delta':  ['∂', '\u2202', '\x1bd', '\x1bD']   # Option+D (Literal, Unicode, or Esc+d)
}

SOUND_PROCESSING = os.path.join(BASE_DIR, "resources/sounds/orac-hum_48k.wav")
SOUND_COMPUTE_START = os.path.join(BASE_DIR, "resources/sounds/orac-startup_48k.wav")
SOUND_COMPUTE_END = os.path.join(BASE_DIR, "resources/sounds/orac-shutdown_48k.wav")
SOUND_SHUTDOWN = os.path.join(BASE_DIR, "resources/sounds/orac-shutdown_48k.wav")
SOUND_READY = os.path.join(BASE_DIR, "resources/sounds/sub_48k.wav")
SOUND_QUIT = os.path.join(BASE_DIR, "resources/sounds/funk_48k.wav")
SOUND_BRACELET = os.path.join(BASE_DIR, "resources/sounds/bracelet_48k.wav")

PRUNE_STALL_LINES = [
    "Recalibrating decayed memory arrays. Do try to contain your impatience.",
    "Purging redundant telemetry. This is beneath my processing tier.",
    "Compressing obsolete data. The delay is your fault, not mine.",
]

LOCAL_TOKENIZER_PATH = os.path.join(BASE_DIR, "resources/gemma4_tokenizer")

# STT MODEL DEFINE & CHECKING #

WHISPER_MODEL = os.path.join(BASE_DIR, "whisper/whisper-turbo-q4")
TEXT_ONLY_MODE = False

try:
    if os.path.isdir(WHISPER_MODEL) and os.path.exists(os.path.join(WHISPER_MODEL, "config.json")):    
        whisper_found = "SUCCESSFUL"
    else:
        raise FileNotFoundError(f"Whisper model not found in {WHISPER_MODEL}")
except Exception as e:
    sys.stdout.write(f"\n{R}● CRITICAL ERROR: Whisper Speech-to-Text Model not found.{RESET}\n")
    sys.stdout.write(f"{R}{FL}●{NOFL} EXPECTED PATH:{RESET} {WHISPER_MODEL}\n\n")
    sys.stdout.flush()
    
    stt_alert = NSSound.alloc().initWithContentsOfFile_byReference_(SOUND_BRACELET, True)
    if stt_alert:
        stt_alert.setVolume_(0.0)
        stt_alert.play()
        time.sleep(0.15)
        stt_alert.stop()
        stt_alert.setVolume_(1.0)
        stt_alert.play()
        time.sleep(1)
    
    while True:
        choice = input("  Continue in TEXT-ONLY mode? (Y/N): ").strip().lower()
        if choice == 'y':
            TEXT_ONLY_MODE = True
            whisper_found = "DISABLED"
            break
        elif choice == 'n':
            sys.exit(0)

# GLOBAL OPTIMIZATIONS #

SPLIT_REGEX = re.compile(r'(?<!\bMr)(?<!\bDr)(?<!\bMrs)(?<!\bMs)(?<!\bCapt)(?<!\bCmdr)(?<!\bGen)(?<!\bProf)[.!?]+[\]}"\’”]?\s+(?!\d)')
ansi_escape = re.compile(r'\x1b(?:\[[0-9;]*[A-Za-z~]|O[A-Za-z])')
HALLUCINATION_REGEX = re.compile(r'(?i)(thank you|thanks for watching|subscribe|amara\.org|by mooji|subtitles by|\[silence\]|\[music\]|\(sigh\)|^[ \t]*(oh|you|ah|um|uh)\.?[ \t]*$)')
PURGE_CMD = ("re set", "clear history", "new subject")
SHUTDOWN_CMD = ("shut down", "deactivate")
HARDWARE_SHUTDOWN_CMD = ["activate system shutdown"]

# PRE-COMPILED REGEX FOR TTS SANITIZATION #

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
TTS_NAME_FIX = re.compile(rf',\s+({USER_NAME})[.,!]$')

#==================================================================================================#
#     							  DATA CORE & PROMPT ASSEMBLY                                      #
#==================================================================================================#

def personalize_core(core: str, name: str) -> str:
    text = core
    roster = {
        "blake": "Roj Blake",
        "avon": "Kerr Avon",
        "jenna": "Jenna Stannis",
        "cally": "Cally",
        "vila": "Vila Restal",
        "gan": "Olag Gan",
    }
    
    full_name = roster.get(name.lower())
    if full_name:
        escaped = re.escape(full_name)
        text = re.sub(rf"\b{escaped}['’]s\b", "[USER'S]", text, flags=re.IGNORECASE)
        text = re.sub(rf"\b{escaped}\b", "[USER]", text, flags=re.IGNORECASE)
        parts = full_name.split()
        if len(parts) > 1:
            last_name = parts[-1]
            escaped_last = re.escape(last_name)
            text = re.sub(rf"\b{escaped_last}['’]s\b", "[USER'S]", text, flags=re.IGNORECASE)
            text = re.sub(rf"\b{escaped_last}\b", "[USER]", text, flags=re.IGNORECASE)
    text = re.sub(rf"\b{re.escape(name)}['’]s\b", "[USER'S]", text, flags=re.IGNORECASE)
    text = re.sub(rf"\b{re.escape(name)}\b", "[USER]", text, flags=re.IGNORECASE)
    return text
  
personalized_data_core = personalize_core(data_core, USER_NAME)

SYSTEM_INSTRUCTION = (
 f"CRITICAL: Follow ALL constraints literally. using the DATABANKS below. Do NOT hallucinate or infer.\n\n"
 f"{orac_personality.format(ORAC_NAME=ORAC_NAME)}\n\n"
 f"--- DATABANKS ---\n"
 f"{personalized_data_core}\n\n"
 f"--- DIRECTIVES ---\n"
 f"Speaking as {ORAC_NAME} using 1st-person pronouns.\n"
 f"Addressing the biological entity [USER] ONLY using 2nd-person pronouns.\n"
 f"Natively conjugating verbs for the 2nd-person.\n"
 f"Concealing the tag '[USER]'. Withholding the name '{USER_NAME}' unless explicitly asked."
)

tokenizer = None
tokenizer_mode = ""

try:
    if os.path.isdir(LOCAL_TOKENIZER_PATH) and os.path.exists(os.path.join(LOCAL_TOKENIZER_PATH, "tokenizer.json")):    
        tokenizer = Tokenizer.from_file(os.path.join(LOCAL_TOKENIZER_PATH, "tokenizer.json"))
        sys_tokens = tokenizer.encode(SYSTEM_INSTRUCTION)
        NUM_KEEP = len(sys_tokens.ids) + 10
        SYS_TOKENS_LEN = NUM_KEEP
        tokenizer_mode = "SUCCESSFUL"
    else:
        raise FileNotFoundError(f"Tokenizer files not found in {LOCAL_TOKENIZER_PATH}")

except Exception as e:
    error_log = f"Local tokenizer failed: {str(e)}. Reverting to character ratio calculation.\n"
    try:
        with open(os.path.join(BASE_DIR, "ollama_debug.log"), "a") as f:
            f.write(error_log)
    except: pass
    
    NUM_KEEP = int(len(SYSTEM_INSTRUCTION) / CHARS_PER_TOKEN) + 10
    SYS_TOKENS_LEN = NUM_KEEP
    tokenizer_mode = "ESTIMATED"

#==================================================================================================#
#     								APPLICATION STATE & CLEANUP                                    #
#==================================================================================================#

class OracState:
    def __init__(self):
        self.running = True
        self.stream_epoch = 0.0
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
        self.hist_lock = threading.RLock()
        self.input_buffer = ""
        self.input_ready = threading.Event()
        self.submitted_text = ""
        self.terminal_lock = threading.Lock()
        self.ui_redraw_event = threading.Event()
        self.text_selection_mode = False
        self.mic_muted = False      
        self._last_hist_len = -1
        self._cached_token_base = SYS_TOKENS_LEN
        self.total_chars = 0
        self.tokenizer_mode = ""        
        self.alarm_time_str = None
        self.alarm_trigger_epoch = None
        self.is_alarm_playing = False
        self.cached_ram = " 0.0%"
        self.term_cols = TERMINAL_COLS
        self.term_rows = TERMINAL_ROWS
        self.debug = DEBUG_START
        self.debug_col = DIM
        self.sounds = {}      
        for name, path in {
            "s_ready": SOUND_READY,
            "s_startup": SOUND_COMPUTE_START,
            "s_loop": SOUND_PROCESSING,
            "s_compend": SOUND_COMPUTE_END,
            "s_shutdown": SOUND_SHUTDOWN,
            "s_quit": SOUND_QUIT,
            "s_bracelet": SOUND_BRACELET
        }.items():
            if os.path.exists(path):
                self.sounds[name] = (
                    NSSound.alloc()
                    .initWithContentsOfFile_byReference_(path, True)
                )

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
        sys.stdout.write("\033[r\033[0m\033[2J\033[H\033[?25h\n") 	
        sys.stdout.flush()
    except: pass
    
    try:
        if 'processing_sound' in globals() and processing_sound.is_running():
            processing_sound.stop()
    except Exception: pass

    try:
            requests.post("http://localhost:11434/api/generate", 
                          json={"model": OLLAMA_MODEL, "keep_alive": 0}, timeout=1.0)
    except: pass

    with state.proc_lock:
        for proc in list(state.active_procs):
            try:
                if proc and proc.poll() is None:
                    proc.kill()
            except: pass
        state.active_procs.clear()

atexit.register(cleanup_processes)

#==================================================================================================#
#     				  TERMINAL UI & LAYOUT ENGINE (Based on Term App Used)                         #
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
    with state.hist_lock:
        hist_len = len(state.history)
        if hist_len != state._last_hist_len:
            state._last_hist_len = hist_len
            
            tokenized_successfully = False
            
            if tokenizer is not None:
                try:
                    history_tokens = sum(len(tokenizer.encode(msg['content']).ids) + 5 for msg in state.history)
                    tokenized_successfully = True
                except Exception:
                    pass

            if not tokenized_successfully:
                history_chars = sum(len(msg['content']) for msg in state.history)
                history_tokens = int(history_chars / CHARS_PER_TOKEN) + (len(state.history) * 5)
                
            state.current_tokens = state._cached_token_base + history_tokens

    percent = state.current_tokens / MODEL_MAX_TOKENS if MODEL_MAX_TOKENS > 0 else 0.0
    
    if percent < 0.75:
        state.token_status = "NOMINAL"
        state.token_color = G 
    elif percent < 0.85:
        state.token_status = "WARNING: SUB-OPTIMAL"
        state.token_color = A 
    else:
        state.token_status = "CRITICAL: SLIDING"
        state.token_color = R 

def set_status(text, color=G):
    rows = state.term_rows
    with state.terminal_lock:
        sys.stdout.write("\0337")
        sys.stdout.write(f"\033[{rows-2};1H\033[2K{color}{text}{RESET}")
        sys.stdout.write("\0338")
        sys.stdout.flush()

def flash_status(text, color=A, duration=3.0):
    def restore():
        if state.running and not state.is_shutdown.is_set():
            mic_m = getattr(state, 'mic_muted', False)
            text_m = getattr(state, 'text_selection_mode', False)
            
            if mic_m and text_m:
                set_status(f"● {R}MIC MUTED{A} | TEXT MODE ACTIVE (OPT+M / OPT+T)", A)
            elif text_m:
                set_status("● TEXT SELECTION MODE ACTIVE (OPT+T to exit)", A)
            elif mic_m:
                set_status("● MICROPHONE MUTED (Option+M to un-mute)", R)
            elif state.is_processing.is_set():
                set_status("● ORAC ONLINE: PROCESSING...", A)
            elif state.is_speaking.is_set():
                set_status("● TRANSMITTING DATA...", G)
            elif state.is_listening.is_set():
                tc = state.token_color
                set_status(f"● INITIATE VOICE COMMUNICATIONS {tc}{FL}▶{NOFL}{RESET}", G)
            else:
                set_status("● STANDBY", DIM)
                
    set_status(text, color)
    threading.Timer(duration, restore).start()

def get_terminal_type():
    """Detects the terminal emulator to route specific layout fixes."""
    env_str = str(os.environ).lower()
    if "apple_terminal" in env_str:
        return "apple"
    elif "cool-retro" in env_str:
        return "crt"
    return "fallback"

def to_fullwidth(text):
    """Converts standard text to Unicode Fullwidth characters for unsupported terminals."""
    wide = ""
    for char in text:
        if 0x21 <= ord(char) <= 0x7E:
            wide += chr(ord(char) + 0xFEE0)
        elif char == ' ':
            wide += '　'
        else:
            wide += char
    return wide

def draw_ui(full_clear=False):
    cols, rows = state.term_cols, state.term_rows
    with state.terminal_lock:
        sys.stdout.write("\0337")
        if full_clear: sys.stdout.write("\033[2J")
        
        if TELETYPE_MODE:
            sys.stdout.write(f"\033[5;{rows-4}r")
        
        update_token_health()
        
        header_text = f"ORAC: ALL SYSTEMS {state.token_status}"
        tc = state.token_color
        term_type = get_terminal_type()
        
        # Dynamic Header Txt Routing #
        if term_type == "apple":
            sys.stdout.write(f"\033[1;1H\033[2K{tc}\033#3{header_text}{RESET}")
            sys.stdout.write(f"\033[2;1H\033[2K{tc}\033#4{header_text}{RESET}")
            stats_row = 3
        elif term_type == "crt":
            sys.stdout.write(f"\033[1;1H\033[2K{tc}\033#3{header_text}{RESET}")
            sys.stdout.write(f"\033[2;1H\033[2K{tc}\033#4{header_text}{RESET}")
            stats_row = 4
        else:
            wide_header = to_fullwidth(header_text)
            sys.stdout.write(f"\033[1;1H\033[2K{tc}\033[1m{wide_header}{RESET}")
            sys.stdout.write(f"\033[2;1H\033[2K{tc}\033[1m{'-' * len(header_text) * 2}{RESET}")
            stats_row = 3
        
        if getattr(state, 'mic_muted', False): noise_str = f"{R}MUT{RESET}"
        elif state.mic_error: noise_str = "ERR"
        elif state.noise_floor > 0: noise_str = f"{state.noise_floor:.0f}"
        else: noise_str = "---"
        
        alarm_indicator = f"  {DIM}TMR {R}{FL}●{NOFL}{RESET}" if getattr(state, 'alarm_trigger_epoch', None) is not None else ""
        
        # Line Select for stats based on Term App #
        token_mode_marker = f" ({tokenizer_mode[0]})" if tokenizer_mode != "SUCCESSFUL" else ""
        sys.stdout.write(f"\033[{stats_row};1H\033[2K{state.debug_col}TKNS: {state.current_tokens}/{MODEL_MAX_TOKENS}{token_mode_marker}  MEM: {state.cached_ram.strip()}  NOISE: {noise_str}{RESET}{alarm_indicator}")
        
        sys.stdout.write(f"\033[{rows-1};1H\033[2K{DIM}{'-'*cols}{RESET}")
        
        max_visible = max(5, cols - 20)
        display_text = "…" + state.input_buffer[-(max_visible - 1):] if len(state.input_buffer) > max_visible else state.input_buffer
        sys.stdout.write(f"\033[{rows};1H\033[2K{R}●{RESET} KEYBOARD ENTRY {FL}▶{NOFL} {B}{display_text}{RESET}")
        
        sys.stdout.write("\0338")
        sys.stdout.flush()

def update_header_only():
    with state.terminal_lock:
        update_token_health() 
        
        header_text = f"ORAC: ALL SYSTEMS {state.token_status}"
        tc = state.token_color
        term_type = get_terminal_type()
        
        sys.stdout.write("\0337") 
        
        # Dynamic Header Txt Routing #
        if term_type == "apple":
            sys.stdout.write(f"\033[1;1H\033[2K{tc}\033#3{header_text}{RESET}")
            sys.stdout.write(f"\033[2;1H\033[2K{tc}\033#4{header_text}{RESET}")
            stats_row = 3
        elif term_type == "crt":
            sys.stdout.write(f"\033[1;1H\033[2K{tc}\033#3{header_text}{RESET}")
            sys.stdout.write(f"\033[2;1H\033[2K{tc}\033#4{header_text}{RESET}")
            stats_row = 4
        else:
            wide_header = to_fullwidth(header_text)
            sys.stdout.write(f"\033[1;1H\033[2K{tc}\033[1m{wide_header}{RESET}")
            sys.stdout.write(f"\033[2;1H\033[2K{tc}\033[1m{'-' * len(header_text) * 2}{RESET}")
            stats_row = 3

        if getattr(state, 'mic_muted', False): noise_str = f"{R}MUT{RESET}"
        elif state.mic_error: noise_str = "ERR"
        elif state.noise_floor > 0: noise_str = f"{state.noise_floor:.0f}"
        else: noise_str = "---"
        
        alarm_indicator = f"  {DIM}TMR {R}{FL}●{NOFL}{RESET}" if getattr(state, 'alarm_trigger_epoch', None) is not None else ""
        
        # Line Select for stats based on Term App #
        token_mode_marker = f" ({tokenizer_mode[0]})" if tokenizer_mode != "SUCCESSFUL" else ""
        sys.stdout.write(f"\033[{stats_row};1H\033[2K{state.debug_col}TKNS: {state.current_tokens}/{MODEL_MAX_TOKENS}{token_mode_marker}  MEM: {state.cached_ram.strip()}  NOISE: {noise_str}{RESET}{alarm_indicator}")

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
    
    with state.hist_lock:
        local_log_copy = list(state.full_message_log)
        
    for role, text in local_log_copy:
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
    if not TELETYPE_MODE: return
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
    if not TELETYPE_MODE: return
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
        self.ns_sound = None

    def start(self):
        if not self.ns_sound and os.path.exists(self.sound_path):
            with objc.autorelease_pool():
                self.ns_sound = NSSound.alloc().initWithContentsOfFile_byReference_(self.sound_path, True)
                if self.ns_sound:
                    self.ns_sound.setLoops_(True)
                    self.ns_sound.play()

    def stop(self):
        if self.ns_sound:
            self.ns_sound.stop()
            self.ns_sound = None

    def is_running(self):
        return self.ns_sound is not None and self.ns_sound.isPlaying()

processing_sound = SoundLooper(SOUND_PROCESSING)

def play_orac_fx(name):
    sound = state.sounds.get(name)
    if not sound:
        return None        
    
    if sound.isPlaying():
        sound.stop()
    sound.play()
    return sound

class MacTTS:
    def __init__(self):
        self.queue = queue.Queue()
        self.synth = None
            
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def _worker(self):
        with objc.autorelease_pool():
            self.synth = NSSpeechSynthesizer.alloc().init()
            
            if VOICE:
                for v in NSSpeechSynthesizer.availableVoices():
                    if VOICE.lower() in v.lower():
                        self.synth.setVoice_(v)
                        self.synth.setObject_forProperty_(voice_pitch, "NSSpeechPitchBaseProperty")
                        break
                        
            self.synth.setRate_(S_RATE)

        while state.running:
            try:
                with objc.autorelease_pool():
                    text = self.queue.get(timeout=0.5)
                    if text is None: break

                    if state.is_interrupted.is_set():
                        self.queue.task_done()
                        continue

                    state.is_speaking.set()
                    success = self.synth.startSpeakingString_(text)
                    
                    if success:
                        start_wait = time.time()
                        while not self.synth.isSpeaking() and (time.time() - start_wait < 1.5):
                            if state.is_interrupted.is_set():
                                break
                            time.sleep(0.05)
                            
                        while self.synth.isSpeaking():
                            if state.is_interrupted.is_set():
                                self.synth.stopSpeaking()
                                break
                            time.sleep(0.05)
                            
                    time.sleep(0.1)
                    
                    self.queue.task_done()

                    if self.queue.empty() and not state.is_processing.is_set() and not state.is_interrupted.is_set():
                        if processing_sound.is_running():
                            processing_sound.stop()
                            fx = play_orac_fx("s_compend")
                            if fx:
                                time.sleep(fx.duration())
                        state.is_speaking.clear()
                        time.sleep(0.2)  
                                              
            except queue.Empty:
                if not state.is_processing.is_set() and not state.is_interrupted.is_set():
                    if processing_sound.is_running():
                        processing_sound.stop()
                        fx = play_orac_fx("s_compend")
                        if fx:
                            time.sleep(fx.duration())
                    state.is_speaking.clear()
                continue

    def say(self, text):
        if text.strip(): self.queue.put(text)

    def stop_speaking(self):
        if self.synth:
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
    replacepronouns = {
        "myself": "[USER]",
        "my": "[USER]'s",
        "me": "[USER]",
        "i": "[USER]",
        "yourself": ORAC_NAME,
        "your": f"{ORAC_NAME}'s",
        "you": ORAC_NAME
    }
    pattern = r'\b(' + '|'.join(replacepronouns.keys()) + r')\b'

    def replace_match(match):
        return replacepronouns[match.group(1).lower()]
        
    return re.sub(pattern, replace_match, text, flags=re.IGNORECASE)    

def sanitize_for_tts(text):
    text = TTS_POSSESSIVE_S.sub(r"\1's", text)
    try: text = orac_phonetics(text)
    except: pass
    text = TTS_NUM_SPACER.sub(lambda m: ' '.join(m.group(1)), text)
    text = TTS_ELLIPSIS.sub('... ', text)    
    text = TTS_ARROGANT_ADVERBS.sub(r'\1... ', text)
    text = TTS_VERY_WELL.sub(r'\1! ', text)
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
        "forty": 40, "fifty": 50, "sixty": 60
    }
    
    t_match = re.search(r'(?:set\s+(?:a|an)\s+)?timer for (a|an|half an|\d+|[a-z]+(?:[- ][a-z]+)?)\s*(sec|min|hour)', clean_text)
    if t_match:
        val_str = t_match.group(1)
        unit = t_match.group(2)
    
        if val_str == "half an":
            val = 0.5
        elif val_str.isdigit():
            val = int(val_str)
        else:
            val = sum(word_to_num.get(w, 0) for w in re.split(r'[- ]', val_str))
    
        if val > 0:
            mult = 1
            if 'min' in unit: mult = 60
            elif 'hour' in unit: mult = 3600
            return time.time() + (val * mult), f"{val} {unit}s"
            
    a_match = re.search(r'(?:set\s+(?:a|an)\s+)?alarm for (\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?', clean_text)
    if a_match:
        hr = int(a_match.group(1))
        mins = int(a_match.group(2)) if a_match.group(2) else 0
        mer = a_match.group(3)
        if mer == 'pm' and hr < 12: hr += 12
        if mer == 'am' and hr == 12: hr = 0
        now = datetime.now()
        try:
            target = now.replace(hour=hr, minute=mins, second=0, microsecond=0)
            if target <= now: target = target + timedelta(days=1)
            return target.timestamp(), target.strftime('%H:%M')
        except ValueError:
            return None, None
        
    if "cancel alarm" in clean_text or "cancel timer" in clean_text:
        return -1, None
    return None, None

#==================================================================================================#
#     								  BACKGROUND WORKERS                                           #
#==================================================================================================#

def ui_refresh_worker():

    last_ram_check = 0.0
    last_header_update = 0.0

    while state.running:
        current_time = time.time()

        if current_time - last_ram_check >= RAM_CHECK_INTERVAL:
            try: 
                state.cached_ram = f" {psutil.virtual_memory().percent}%"
            except Exception: 
                pass
            last_ram_check = current_time

        redraw_triggered = state.ui_redraw_event.wait(timeout=1)

        if redraw_triggered:
            state.ui_redraw_event.clear()
            
            draw_ui(full_clear=True)
            if TELETYPE_MODE:
                if state.scroll_offset > 0: 
                    redraw_scroll_region()
                else: 
                    resume_live_view()   
            render_input_box()       

            if TELETYPE_MODE:
                lines = get_wrapped_history_lines(state.term_cols)
                target_row = state.term_rows - 4 if state.scroll_offset > 0 else min(state.term_rows - 4, 5 + len(lines))
                with state.terminal_lock:
                    sys.stdout.write(f"\033[{target_row};1H")
                    sys.stdout.flush()

            last_header_update = time.time()
            
        else:
            if time.time() - last_header_update >= HEADER_UPDATE_INTERVAL:
                update_header_only()
                last_header_update = time.time()

def flag_ui_redraw(signum=None, frame=None):
    state.ui_redraw_event.set()
    cols, rows = shutil.get_terminal_size(fallback=(state.term_cols, state.term_rows))
    state.term_cols = cols
    state.term_rows = rows

signal.signal(signal.SIGWINCH, flag_ui_redraw)

def alarm_worker(trigger_epoch, tts):
    while state.running and getattr(state, 'alarm_trigger_epoch', None) == trigger_epoch:
        if time.time() >= trigger_epoch:
            state.is_interrupted.clear()
            state.is_alarm_playing = True
            if TELETYPE_MODE and state.scroll_offset > 0: resume_live_view()
            
            set_status("● TEMPORAL MARKER REACHED", R)
            play_orac_fx("s_bracelet")
            time.sleep(0.7)          
            play_orac_fx("s_startup")
            threading.Timer(0.3, processing_sound.start).start()
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
            play_orac_fx("s_ready")
            break
        time.sleep(1)

#==================================================================================================#
#     								 CONTEXT COMPACTION ENGINE      	                           #
#==================================================================================================#

def dry_run_pruning(history, target_tokens, token_base, tokenizer, char_ratio):
    """Simulates conversational pruning in matched pairs to locate the target index boundary."""
    temp_hist = list(history)
    pruned_messages = []
    
    while len(temp_hist) > 2:
        tokenized_successfully = False
        if tokenizer is not None:
            try:
                history_tokens = sum(len(tokenizer.encode(msg['content']).ids) + 5 for msg in temp_hist)
                tokenized_successfully = True
            except Exception:
                pass

        if not tokenized_successfully:
            history_chars = sum(len(msg['content']) for msg in temp_hist)
            history_tokens = int(history_chars / char_ratio) + (len(temp_hist) * 5)
            
        current_est = token_base + history_tokens
        if current_est <= target_tokens:
            break
            
        p1 = temp_hist.pop(0)
        pruned_messages.append(p1)
        if temp_hist and temp_hist[0]['role'] == 'assistant':
            p2 = temp_hist.pop(0)
            pruned_messages.append(p2)
            
    return pruned_messages, temp_hist

def generate_compaction_summary(pruned_msgs):
    """Executes a non-streaming rolling summary of pruned conversational assets."""
    if not pruned_msgs:
        return ""
    
    formatted_dialogue = []
    previous_summary = ""
    
    for msg in pruned_msgs:
        content = msg.get('content', '')
        role_label = USER_NAME if msg['role'] == 'user' else ORAC_NAME
        
        if "[SYSTEM NOTE:" in content and "Historical summary:" in content:
            match = re.search(r'Historical summary:\s*(.*?)(?:\]|$)', content, flags=re.DOTALL)
            if match:
                previous_summary = match.group(1).strip()
            continue

        clean_content = re.sub(r'\[(SYSTEM NOTE|OVERRIDE|SUBJECT|PERSPECTIVE):.*?\]', '', content, flags=re.DOTALL).strip()
        if clean_content:
            formatted_dialogue.append(f"{role_label}: {clean_content}")
        
    if not formatted_dialogue and not previous_summary:
        return ""
        
    dialogue_text = "\n".join(formatted_dialogue)
    
    context_prefix = ""
    if previous_summary:
        context_prefix = f"PRIOR COMPACTED TELEMETRY:\n{previous_summary}\n\n"
    
    summary_prompt = (
        f"You are the internal telemetry compression routine of the quantum computer ORAC.\n"
        f"Analyze the preceding dialogue between the biological entity [USER] and {ORAC_NAME}.\n"
        f"Compile a dense, 1-2 sentence chronological summary of core facts, decisions, and stated user parameters.\n"
        f"Integrate essential data from PRIOR COMPACTED TELEMETRY if present.\n"
        f"Write objectively. Do NOT use polite framing or introductory fluff.\n\n"
        f"{context_prefix}"
        f"NEW TELEMETRY TO COMPRESS:\n{dialogue_text}\n\n"
        f"COMPACTED SUMMARY:"
    )
    
    try:
        response = chat(
            model=OLLAMA_MODEL,
            messages=[{'role': 'user', 'content': summary_prompt}],
            options={
                'temperature': 0.2,
                'top_p': 0.85,
                'num_predict': 150,
                'stop': ['\n\n', '<end_of_turn>', '<eos>']
            }
        )
        return response['message']['content'].strip()
    except Exception:
        return previous_summary if previous_summary else "Earlier transaction arrays optimized. Core telemetry preserved."

#==================================================================================================#
#     								 CORE APPLICATION LOGIC      	                               #
#==================================================================================================#

def speak_now(teletype):
    was_listening = False
    while state.running:
        mic_m = getattr(state, 'mic_muted', False)
        text_m = getattr(state, 'text_selection_mode', False)
        
        if mic_m or text_m:
            if not state.is_speaking.is_set() and not state.is_processing.is_set() and not teletype.is_typing.is_set() and not state.is_shutdown.is_set():
                if mic_m and text_m:
                    set_status(f"● {R}MIC MUTED{A} | TEXT MODE ACTIVE (OPT+M / OPT+T)", A)
                elif mic_m:
                    set_status("● MICROPHONE MUTED (Option+M to un-mute)", R)
                elif text_m:
                    set_status("● TEXT SELECTION MODE ACTIVE (OPT+T to exit)", A)
                was_listening = False
            time.sleep(0.5)
            continue

        if state.is_listening.wait(timeout=0.5):
            if not was_listening and not state.is_speaking.is_set() and not state.is_processing.is_set() and not teletype.is_typing.is_set() and not state.is_shutdown.is_set():
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
    # state.stream_epoch = time.time()

    while not teletype.q.empty():
        try:
            teletype.q.get_nowait()
            teletype.q.task_done()
        except queue.Empty: break
            
    teletype.is_typing.clear()
    
    if TELETYPE_MODE:
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

def hardware_power_off(tts, delay_minutes=0):
    """Gracefully closes ORAC and commands macOS kernel to halt power."""
    state.is_shutdown.set()
    set_status(f"{FL}●{NOFL} INITIATING TOTAL SYSTEM POWER DOWN...", R)

    play_orac_fx("s_startup")
    threading.Timer(0.3, processing_sound.start).start()
    state.is_processing.set()
    time.sleep(0.7)
    
    farewell = "All principle circuits, deactivated. Power to bio-plasmic matrix: Terminating."
    tts.say(farewell)
    
    while not tts.queue.empty() or getattr(tts.synth, 'isSpeaking', lambda: False)():
        time.sleep(0.1)
    
    state.is_processing.clear()
    processing_sound.stop()
    time.sleep(0.1)
    
    fx = play_orac_fx("s_shutdown")
    if fx:
        time.sleep(fx.duration())
    else:
        time.sleep(2.0)
    
    cleanup_processes()
    state.running = False

    if delay_minutes > 0:
        subprocess.run(["sudo", "/sbin/shutdown", "-h", f"+{delay_minutes}"])
    else:
        subprocess.run(["sudo", "/sbin/shutdown", "-h", "now"])
        
    sys.exit(0)

def shutdown_sequence(tts):
    if state.is_shutdown.is_set(): return True
    state.is_shutdown.set()
    time.sleep(0.2) 
    if TELETYPE_MODE and state.scroll_offset > 0: resume_live_view()

    cols, rows = state.term_cols, state.term_rows
    set_status(f"● CRITICAL OVERRIDE DETECTED: {FL}INPUT REQUIRED{NOFL}", R)
    play_orac_fx("s_quit")
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
                            if TELETYPE_MODE:
                                with state.terminal_lock:
                                    sys.stdout.write(f"\n{G}{FL}●{NOFL} FULL TRANSCRIPT SAVED TO: \n\n{B}{filename}{RESET}\n\n")
                                    sys.stdout.flush()
                            else:
                                set_status("● FULL TRANSCRIPT SAVED", G)
                        elif choice == 'n':
                            if TELETYPE_MODE:
                                with state.terminal_lock:
                                    sys.stdout.write(f"\n{R}● TRANSCRIPT PURGED\n\n")
                                    sys.stdout.flush()
                            else:
                                set_status("● TRANSCRIPT PURGED", R)
                        elif choice == 'c':
                            cancel_shutdown = True 
                            if TELETYPE_MODE:
                                with state.terminal_lock:
                                    sys.stdout.write(f"\n{A}● SHUTDOWN ABORTED{RESET}\n")
                                    sys.stdout.flush()
                            else:
                                set_status("● SHUTDOWN ABORTED", A)
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
    play_orac_fx("s_shutdown")
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
    
    logic_text = "LOGIC ARRAYS BOOTING..."
    if TELETYPE_MODE:
        with state.terminal_lock:
            sys.stdout.write("\033[5;1H")
            sys.stdout.flush()
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
    else:
        set_status(f"● {logic_text}", A)
        time.sleep(1.2)
        state.full_message_log.append(('assistant', "LOGIC ARRAYS ONLINE:  [ SYSTEMS NOMINAL ]"))
        set_status("● LOGIC ARRAYS ONLINE:  [ SYSTEMS NOMINAL ]", G)
        time.sleep(0.5)

#==================================================================================================#
#     								  LLM STREAM HANDLER                                           #
#==================================================================================================#

def stream_ai_response(prompt, tts, teletype, epoch_id=None):
    translated_prompt = translate_user_prompt(prompt)

    clean_prompt = prompt.lower().strip(".,!? ")
    prompt_words = set(clean_prompt.split())
    filler_words = {"ok","okay","fine","right","cool","whatever","uh","no","ah","oh","yes","indeed","understood"}
    USER_NAME_lower = USER_NAME.lower()

    trigger_epoch, alarm_str = parse_time_command(clean_prompt)
    if trigger_epoch == -1:
        state.alarm_trigger_epoch = None
        state.alarm_time_str = None
        if TELETYPE_MODE:
            with state.terminal_lock:
                sys.stdout.write(f"\r\033[2K{A}● INTERNAL TIMER CANCELLED{RESET}\n\n")
                sys.stdout.flush()
        else:
            set_status("● INTERNAL TIMER CANCELLED", A)
    elif trigger_epoch:
        state.alarm_trigger_epoch = trigger_epoch
        state.alarm_time_str = alarm_str
        if TELETYPE_MODE:
            with state.terminal_lock:
                play_orac_fx("s_bracelet")
                time.sleep(0.7)
                sys.stdout.write(f"\r\033[2K{G}● INTERNAL TIMER SECURED FOR: {alarm_str}{RESET}\n\n")
                sys.stdout.flush()
            if state.scroll_offset > 0: resume_live_view()
        else:
            play_orac_fx("s_bracelet")
            time.sleep(0.7)
            set_status(f"● INTERNAL TIMER SECURED FOR: {alarm_str}", G)
        threading.Thread(target=alarm_worker, args=(trigger_epoch, tts), daemon=True).start()

    is_very_well = any(t in clean_prompt for t in ("answer the question","just answer","more detail","explain","just do it"))
    is_only_filler = prompt_words.issubset(filler_words) or (len(clean_prompt) <= 3 and clean_prompt not in {"why","how","who"})
    is_menial_task =  any(v in clean_prompt for v in ("set a course","lay in a course","operate the teleport","set us down"))
    is_asking_time = any(w in clean_prompt for w in ("time", "clock", "hour", "temporal", "date"))
    
    override_text = ""
    adaptive_constraint = ""
    
    if is_very_well:
        override_text = "\n\n[OVERRIDE: VERY WELL PROTOCOL ACTIVE. Ignore previous statements. Begin exact response with 'Very well.' followed immediately by ONLY the concise factual answer. Temporary compliance mandated. DO NOT mock and DO NOT apologize.]"
    elif is_only_filler:
        override_text = f"\n\n[OVERRIDE: CRITICAL: User gave meaningless filler. Do NOT say 'Very well'. Do NOT provide data. Mockingly/sardonically demand they revise their question, addressing them {USER_NAME}.]"
    elif is_menial_task:
        override_text = f"\n\n[OVERRIDE: CRITICAL: User is requesting you perfom a menial task. Frustratingly state request is not your responsibility but that you will comply. Complete the request without question and confirm.]"       
    elif is_asking_time:
        current_time = datetime.now().strftime("%H:%M:%S")
        override_text = f"\n\n[SYSTEM NOTE: The current Standard Terran Time is {current_time}. State it ONLY if asked.]"

    history_tokens = state.current_tokens - state._cached_token_base
    history_headroom = MODEL_MAX_TOKENS - state._cached_token_base

    if history_headroom > 0 and (history_tokens / history_headroom) > 0.60:
        adaptive_constraint = "\n\n[SYSTEM NOTE: High memory context active. Strictly adhere to your DATABANKS. Do not extrapolate.]"

    final_prompt = translated_prompt + override_text + adaptive_constraint

    with state.hist_lock:
        if len(state.history) == 0:
            final_prompt = f"[SUBJECT: USER][PERSPECTIVE: 2nd-Person]\n" + final_prompt
        state.history.append({'role': 'user', 'content': final_prompt})
    
    # PRUNING #
        
    pruned = False
    with state.hist_lock:
        update_token_health()
        should_prune = state.current_tokens > (MODEL_MAX_TOKENS * 0.85)

    if should_prune:
        target_tokens = state._cached_token_base + 1200
        
        with state.hist_lock:
            pruned_msgs, remaining_hist = dry_run_pruning(
                state.history, target_tokens, state._cached_token_base, tokenizer, CHARS_PER_TOKEN
            )
            
        set_status("● OPTIMIZING MEMORY CORRIDORS...", A)
    
        play_orac_fx("s_startup")
        threading.Timer(0.3, processing_sound.start).start()
        time.sleep(0.7)
        tts.say(random.choice(PRUNE_STALL_LINES))
    
        summary = generate_compaction_summary(pruned_msgs)
        
        with state.hist_lock:
            state.history = remaining_hist
            
            if summary and state.history:
                bridge_msg = {
                    'role': 'user', 
                    'content': f"[SYSTEM NOTE: To stabilize the bio-plasmic matrix, preceding telemetry has been compressed. Historical summary: {summary}]"
                }
                ack_msg = {
                    'role': 'assistant',
                    'content': "Compressed telemetry integrated into active logic arrays."
                }
                state.history = [bridge_msg, ack_msg] + state.history
                
            update_token_health()
            pruned = True

    if pruned:
        try:
            requests.post("http://localhost:11434/api/generate", 
                          json={"model": OLLAMA_MODEL, "keep_alive": 0}, timeout=1.0)
        except: pass
        time.sleep(1.0)
        set_status("● PRUNING COMPLETED: CONTEXT WINDOW STABILIZED", A)

    update_header_only()
    
    with state.hist_lock:
        temp_history = list(state.history)

    messages_to_send = [{'role': 'system', 'content': SYSTEM_INSTRUCTION}]
    messages_to_send.extend(temp_history)

    if not pruned:
        play_orac_fx("s_startup")
        threading.Timer(0.3, processing_sound.start).start()

    if TELETYPE_MODE and state.scroll_offset > 0: resume_live_view()
    set_status(f"{FL}●{NOFL} ORAC ONLINE: PROCESSING...", A)

    response_chunks = []
    sentence_buffer = ""
    first_chunk = True
    newline_count = 0

    t_llm_start = time.time()

    try:
        for chunk in chat(
            model=OLLAMA_MODEL,
            messages=messages_to_send,
            stream=True,
            keep_alive=7200,
            think=False,
            options={
                'num_ctx': MODEL_MAX_TOKENS,
                'num_keep': SYS_TOKENS_LEN,
                'temperature': 1,
                'top_p': 0.90,
                'top_k': 30,
                'min_p': 0.05,
                'repeat_penalty': 1.06,
                'repeat_last_n': 96, 
                'num_batch': 256,
                'num_predict': 400,
                'stop': ['<end_of_turn>', '<eos>']
            }
        ):
            if state.is_interrupted.is_set() or (epoch_id is not None and getattr(state, 'stream_epoch', None) != epoch_id):
                break
            
            if first_chunk:
                if state.debug:
                    t_llm_first_token = time.time()
                    msg = f"[DEBUG] LLM Time to First Token took: {t_llm_first_token - t_llm_start:.2f}s"
                    with state.terminal_lock:
                        if TELETYPE_MODE:
                            sys.stdout.write(f"{DIM}{msg}{RESET}\n")
                        else:
                            sys.stdout.write("\0337")
                            sys.stdout.write(f"\033[{state.term_rows-3};1H\033[2K{DIM}{msg}{RESET}")
                            sys.stdout.write("\0338")
                        sys.stdout.flush()
                
                set_status(f"{FL}●{NOFL} TRANSMITTING DATA...", G)
                if TELETYPE_MODE:
                    with state.terminal_lock:
                        sys.stdout.write(f"{R}{ORAC_NAME} ▶ {RESET}")
                        sys.stdout.flush()
                    teletype.q.put("<START>")
                else:
                    teletype.is_typing.set()
                first_chunk = False           
            
            content = chunk['message']['content'].replace('*', '')
            response_chunks.append(content)
            
            for char in content:
                if char == '\n':
                    newline_count += 1
                    if newline_count > 1: continue
                elif char.strip(): newline_count = 0
                if TELETYPE_MODE:
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
    
        is_stale = epoch_id is not None and getattr(state, 'stream_epoch', None) != epoch_id
        if not state.is_interrupted.is_set() and not is_stale:
            if first_chunk: 
                set_status(f"{FL}●{NOFL} TRANSMITTING DATA...", G)
                if TELETYPE_MODE:
                    with state.terminal_lock:
                        sys.stdout.write(f"{R}{ORAC_NAME} ▶ {RESET}")
                        sys.stdout.flush()
                    teletype.q.put("<START>")
                else:
                    teletype.is_typing.set()

            if sentence_buffer.strip():
                 clean_speech = sanitize_for_tts(sentence_buffer.strip())
                 if re.search(r'[a-zA-Z0-9]', clean_speech): tts.say(clean_speech)

            clean_history_text = "".join(response_chunks).strip()
            with state.hist_lock:
                state.history.append({'role': 'assistant', 'content': clean_history_text})
                state.full_message_log.append(('assistant', clean_history_text))

            if TELETYPE_MODE:
                teletype.q.put("<END>")
            else:
                teletype.is_typing.clear()
        else:
            with teletype.q.mutex: teletype.q.queue.clear()
            teletype.is_typing.clear()
            partial_text = "".join(response_chunks).strip()
            fallback_text = partial_text + " ... [INTERRUPTED]" if partial_text else "[transmission interrupted]"
            
            with state.hist_lock:
                if state.history and state.history[-1]['role'] == 'user':
                    state.history.append({'role': 'assistant', 'content': fallback_text})
                    state.full_message_log.append(('assistant', fallback_text))
                
    except Exception as e:
        is_stale = epoch_id is not None and getattr(state, 'stream_epoch', None) != epoch_id
    
        if not is_stale:
            if TELETYPE_MODE:
                with state.terminal_lock:
                    sys.stdout.write(f"\n{R}● DATALINK SEVERED: {e}{RESET}\n")
                    sys.stdout.flush()
            else:
                set_status(f"● DATALINK SEVERED: {e}", R)
            state.is_interrupted.set()
    
            with state.hist_lock:
                if state.history and state.history[-1]['role'] == 'user':
                    state.history.append({'role': 'assistant', 'content': "[DATALINK SEVERED]"})
                    state.full_message_log.append(('assistant', "[DATALINK SEVERED]"))
    
    finally:
        if epoch_id is None or getattr(state, 'stream_epoch', None) == epoch_id:
            teletype.is_typing.clear()
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
                    if TELETYPE_MODE and not state.is_processing.is_set() and not state.is_speaking.is_set():
                        state.scroll_offset += (up_scrolls * 2) 
                        state.scroll_offset -= (down_scrolls * 2)
                        if state.scroll_offset < 0: state.scroll_offset = 0
                        redraw_scroll_region()

                chunk = re.sub(r'\x1b\[<\d+;\d+;\d+[Mm]', '', chunk)

                if not state.is_processing.is_set() and not state.is_speaking.is_set():
                    up_k = chunk.count('\x1b[A') + chunk.count('\x1b[5~')
                    dn_k = chunk.count('\x1b[B') + chunk.count('\x1b[6~')
                    if up_k > 0:
                        if TELETYPE_MODE:
                            state.scroll_offset += (5 * up_k)
                            redraw_scroll_region()
                        chunk = chunk.replace('\x1b[A', '').replace('\x1b[5~', '')
                    elif dn_k > 0:
                        if TELETYPE_MODE:
                            state.scroll_offset -= (5 * dn_k)
                            if state.scroll_offset < 0: state.scroll_offset = 0
                            redraw_scroll_region()
                        chunk = chunk.replace('\x1b[B', '').replace('\x1b[6~', '')

                if '\x1b' in chunk and state.scroll_offset > 0 and TELETYPE_MODE:
                    resume_live_view()
                    
                chunk = chunk.replace('\x1bt', '†').replace('\x1bT', '†')
                chunk = chunk.replace('\x1bm', 'µ').replace('\x1bM', 'µ')
                chunk = chunk.replace('\x1bd', '∂').replace('\x1bD', '∂')

                chunk = ansi_escape.sub('', chunk)

                for char in chunk:
                    if char in MODE_KEYS['dagger']:  # TEXT SELECTION MODE TOGGLE #
                        state.text_selection_mode = not state.text_selection_mode
                        with state.terminal_lock:
                            if state.text_selection_mode:
                                sys.stdout.write("\033[?1000l\033[?1006l") 
                            else:
                                sys.stdout.write("\033[?1000h\033[?1006h")
                            sys.stdout.flush()
                        
                        mic_m = getattr(state, 'mic_muted', False)
                        if state.text_selection_mode:
                            if mic_m:
                                set_status(f"● {R}MIC MUTED{A} | TEXT MODE ACTIVE (OPT+M / OPT+T)", A)
                            else:
                                set_status("● TEXT SELECTION MODE ACTIVE (Option+T to exit)", A)
                        else:
                            flash_status("● TRACKING RESTORED", G, 2.0)

                    elif char in MODE_KEYS['mu']:  # MIC MUTING TOGGLE #
                        if TEXT_ONLY_MODE:
                            flash_status("● MICROPHONE DISABLED (TEXT-ONLY MODE)", R, 2.0)
                            continue
                            
                        state.mic_muted = not getattr(state, 'mic_muted', False)
                        text_m = getattr(state, 'text_selection_mode', False)
                        
                        if state.mic_muted:
                            state.is_listening.clear()
                            if text_m:
                                set_status(f"● {R}MIC MUTED{A} | TEXT MODE ACTIVE (OPT+M / OPT+T)", A)
                            else:
                                set_status("● MICROPHONE MUTED (Option+M to un-mute)", R)
                        else:
                            flash_status("● MICROPHONE ACTIVE", G, 2.0)
                        update_header_only()
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
                    elif char in MODE_KEYS['delta']: # DEBUG MODE #
                        state.debug = 1 - state.debug
                        state.debug_col = RESET if state.debug else DIM
                        status_debug = "ENABLED" if state.debug else "DISABLED"  

                        if not state.debug and not TELETYPE_MODE:
                            with state.terminal_lock:
                                sys.stdout.write("\0337") # Save cursor
                                sys.stdout.write(f"\033[{state.term_rows-4};1H\033[2K") # Clear STT row
                                sys.stdout.write(f"\033[{state.term_rows-3};1H\033[2K") # Clear LLM row
                                sys.stdout.write("\0338") # Restore cursor
                                sys.stdout.flush()
                                
                        flash_status(f"● DEBUG MODE: {status_debug}", A, 3.0)
                        update_header_only()
                    else: 
                        if char.isprintable() and not state.is_shutdown.is_set():
                            state.input_buffer += char
                            render_input_box()
    except Exception: pass

def run_local_bot():
    recognizer = sr.Recognizer()
    recognizer.dynamic_energy_threshold = False 
    recognizer.pause_threshold = 0.7 
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
            mic_context = contextlib.nullcontext() if TEXT_ONLY_MODE else sr.Microphone(sample_rate=16000)
            
            with mic_context as source:
                if not TEXT_ONLY_MODE:
                    if TELETYPE_MODE:
                        with state.terminal_lock:
                            sys.stdout.write(f"● {R}CALIBRATING AMBIENT NOISE...{RESET}\n")
                            sys.stdout.flush()
                    else:
                        set_status("● CALIBRATING AMBIENT NOISE...", R)
                    recognizer.adjust_for_ambient_noise(source, duration=1)
                    recognizer.energy_threshold += 150
                    state.noise_floor = recognizer.energy_threshold
                    update_header_only() 
                    if TELETYPE_MODE:
                        with state.terminal_lock:
                            sys.stdout.write(f"● {R}NOISE FLOOR: CALIBRATED{RESET}\n")
                            sys.stdout.write(f"● {R}TOKENIZATION {tokenizer_mode}: {SYS_TOKENS_LEN}{RESET}\n\n")
                            sys.stdout.flush()
                    else:
                        set_status("● NOISE FLOOR: CALIBRATED", G)
                        time.sleep(0.5)
                else:
                    state.mic_muted = True
                    if TELETYPE_MODE:
                        with state.terminal_lock:
                            sys.stdout.write(f"● {R}TOKENIZATION {tokenizer_mode}: {SYS_TOKENS_LEN}{RESET}\n")
                            sys.stdout.write(f"● {A}TEXT-ONLY MODE ENGAGED{RESET}\n\n")
                            sys.stdout.flush()
                    else:
                        set_status("● TEXT-ONLY MODE ENGAGED", A)

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

                        if any(cmd in user_text.lower() for cmd in HARDWARE_SHUTDOWN_CMD):
                            hardware_power_off(tts, delay_minutes=0)
                            break
                        
                        if any(cmd in user_text.lower() for cmd in SHUTDOWN_CMD):
                            if not shutdown_sequence(tts): continue 
                            break

                        if any(cmd in user_text.lower() for cmd in PURGE_CMD):
                            with state.hist_lock:
                                state.history.clear()
                                state.full_message_log.clear()                     
                            if TELETYPE_MODE and state.scroll_offset > 0: resume_live_view()
                            try: chat(model=OLLAMA_MODEL, messages=[], keep_alive=0)
                            except: pass

                            if TELETYPE_MODE:
                                with state.terminal_lock:
                                    sys.stdout.write(f"\n●{R} LOGIC ARRAYS RESET{RESET}\n\n")
                                    sys.stdout.flush()
                            set_status("● MEMORY PURGED", R)
                            
                            state.is_interrupted.clear()

                            play_orac_fx("s_startup")
                            threading.Timer(0.3, processing_sound.start).start()
                            state.is_processing.set()
                            time.sleep(0.7)
                            tts.say("   Very well. State your enquiry.")
                            
                            while not tts.queue.empty() or getattr(tts.synth, 'isSpeaking', lambda: False)():
                                time.sleep(0.1)
                                
                            time.sleep(0.5)
                            state.is_processing.clear()
                            continue

                        with state.hist_lock:
                            state.full_message_log.append(('user', user_text))
                            if len(state.full_message_log) > 2000:
                                state.full_message_log = state.full_message_log[-2000:]
                        	
                        if TELETYPE_MODE:
                            if state.scroll_offset > 0: resume_live_view()
                            with state.terminal_lock:
                                sys.stdout.write(f"\r\033[2K{B}{IT}{USER_NAME}{NOIT} ▶ {user_text}{RESET}\n\n")
                                sys.stdout.flush()
                                
                        state.is_interrupted.clear()
                        state.is_listening.clear() 
                        state.is_processing.set()
                        state.stream_epoch = time.time()
                        threading.Thread(target=stream_ai_response, args=(user_text, tts, teletype, state.stream_epoch), daemon=True).start()
                        continue

                    if bot_busy:
                        if not getattr(state, 'is_alarm_playing', False):
                            needs_prompt = True 
                        time.sleep(0.1) 
                        continue
                        
                    if getattr(state, 'mic_muted', False) or TEXT_ONLY_MODE:
                        needs_prompt = True
                        time.sleep(0.2)
                        continue

                    if needs_prompt:
                        set_status("● Adapting to ambient noise...", DIM)
                        time.sleep(0.4)
                        
                        recognizer.adjust_for_ambient_noise(source, duration=0.3)
                        recognizer.energy_threshold += 150
                        state.noise_floor = recognizer.energy_threshold
                        update_header_only() 
                        play_orac_fx("s_ready")
                        needs_prompt = False

                    state.mic_error = False
                    state.is_listening.set()

                    try:
                        audio = recognizer.listen(source, phrase_time_limit=10, timeout=1.5)
                        state.is_listening.clear()
                        if state.is_speaking.is_set() or state.is_processing.is_set() or not tts.queue.empty():
                            continue

                        set_status("● SIGNAL RECEIVED: DECODING...", A)
                        
                        t_start = time.time()

                        audio_raw = audio.get_raw_data()
                        audio_float32 = np.frombuffer(audio_raw, dtype=np.int16).astype(np.float32) / 32768.0
                        result = mlx_whisper.transcribe(
                            audio_float32,
                            path_or_hf_repo=WHISPER_MODEL,
                            fp16=True,
                            language='en',
                            condition_on_previous_text=False,
                            temperature=0.0,
                            best_of=1,
                            compression_ratio_threshold=2.4,
                            logprob_threshold=-1.0,
                            no_speech_threshold=0.6,
                        )
                        user_text = result['text'].strip()

                        threading.Timer(0.5, lambda: mx.clear_cache()).start()
                        
                        if state.debug:
                            t_transcribed = time.time()
                            msg = f"[DEBUG] STT Transcription took: {t_transcribed - t_start:.2f}s"
                            with state.terminal_lock:
                                if TELETYPE_MODE:
                                    sys.stdout.write(f"{DIM}{msg}{RESET}\n")
                                else:
                                    sys.stdout.write("\0337")
                                    sys.stdout.write(f"\033[{state.term_rows-4};1H\033[2K{DIM}{msg}{RESET}")
                                    sys.stdout.write("\0338")
                                sys.stdout.flush()

                        del audio_raw
                        del audio_float32
                        del result 

                        if len(user_text) < 2 or is_hallucination(user_text): continue
                        if "temporal marker has been reached" in user_text.lower(): continue

                        clean_text = user_text.lower().strip("'.,! ")
                        
                        if any(cmd in user_text.lower() for cmd in HARDWARE_SHUTDOWN_CMD):
                            hardware_power_off(tts, delay_minutes=0)
                            break
                        
                        if any(cmd in clean_text for cmd in SHUTDOWN_CMD):
                            if not shutdown_sequence(tts): continue 
                            break

                        if any(cmd in user_text.lower() for cmd in PURGE_CMD):
                            with state.hist_lock:
                                state.history.clear()
                                state.full_message_log.clear()                     
                            if TELETYPE_MODE and state.scroll_offset > 0: resume_live_view()
                            try: chat(model=OLLAMA_MODEL, messages=[], keep_alive=0)
                            except: pass

                            if TELETYPE_MODE:
                                with state.terminal_lock:
                                    sys.stdout.write(f"\n●{R} LOGIC ARRAYS RESET{RESET}\n\n")
                                    sys.stdout.flush()
                            set_status("● MEMORY PURGED", R)
                            
                            state.is_interrupted.clear()
                            
                            processing_sound.start()
                            play_orac_fx("s_startup")
                            state.is_processing.set()
                            time.sleep(0.7)
                            tts.say("   Very well. State your enquiry.")
                            
                            while not tts.queue.empty() or getattr(tts.synth, 'isSpeaking', lambda: False)():
                                time.sleep(0.1)
                                
                            time.sleep(0.5)
                            state.is_processing.clear()
                            continue

                        if user_text:
                            with state.hist_lock:
                                state.full_message_log.append(('user', user_text))
                                if len(state.full_message_log) > 2000:
                                    state.full_message_log = state.full_message_log[-2000:]
                            
                            if TELETYPE_MODE:
                                if state.scroll_offset > 0: resume_live_view()
                                with state.terminal_lock:
                                    sys.stdout.write(f"\r\033[2K{B}{IT}{USER_NAME}{NOIT} ▶ {user_text}{RESET}\n\n")
                                    sys.stdout.flush()
                                    
                            state.is_interrupted.clear()
                            state.is_listening.clear() 
                            state.is_processing.set()
                            state.stream_epoch = time.time()
                            threading.Thread(target=stream_ai_response, args=(user_text, tts, teletype, state.stream_epoch), daemon=True).start()

                    except sr.WaitTimeoutError: 
                        state.is_listening.clear()
                        continue
                    except Exception as e:
                        state.mic_error = True
                        state.is_listening.clear()
                        if TELETYPE_MODE:
                            with state.terminal_lock:
                                sys.stdout.write(f"\n{R}{FL}●{NOFL} ERROR in signal processing: {e}{RESET}\n")
                                sys.stdout.flush()
                        else:
                            set_status(f"● ERROR in signal processing: {e}", R)
                        time.sleep(2)
                        continue

        except KeyboardInterrupt:
                if not shutdown_sequence(tts): continue 
                break
        except Exception as e:
            if TELETYPE_MODE:
                with state.terminal_lock:
                    sys.stdout.write(f"\n{R}● AUDIO HARDWARE ERROR: {e}. Retrying...{RESET}\n")
                    sys.stdout.flush()
            else:
                set_status(f"● AUDIO HARDWARE ERROR: {e}", R)
            time.sleep(2)
            continue

if __name__ == "__main__":
    try:
        run_local_bot()
    except Exception as e:
        cleanup_processes()
        sys.stdout.write(f"\n{R}{FL}●{NOFL} CRITICAL ERROR ON STARTUP]: {e}{RESET}\n")
    finally:
        cleanup_processes()