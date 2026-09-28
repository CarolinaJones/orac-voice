import atexit
import contextlib
import functools
import json
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
#    					     ORAC-VOICE v1.6.5 (Lore friendly VoiceChat)                           #
#                                     gemma4:12b-mlx Optimized                                     #
#          						  Copyright © 2026 Caroline Mayne                                  #
#         						 https://github.com/CarolinaJones/                                 #
#==================================================================================================#

#------------------------------------#
#      USER CHANGEABLE VARIABLES     #
#------------------------------------#

USER_NAME = "Jenna" 								# USER Name and Identity
ORAC_NAME = "ORAC"									# ORAC's Name

TELETYPE_MODE = False                               # Set False for "Compact" mode (Voice only, minimal 8-row UI)
U1 = 0.038											# Teletype Speed
U2 = 0.042											# Teletype Uniformity

USE_LCD = True                                      # Enable Forenove 1602 I2C LCD via Pi Pico
LCD_PORT = "/dev/cu.usbmodem101"                    # Serial port for Pico
LCD_BAUD = 115200                                   # Pico serial baud rate

DEBUG_START = 1										# Start with Debug Mode enabled (1 = Yes  0 = No)

VOICE = "" 			# Leave blank to use the "System Voice" - This allows for SIRI/Personal Voices
voice_pitch = 72 	# Only works on SYNTH voices and not SIRI/Personal voices
S_RATE = 182		# Synth Speech Rate
SPEAK_AFTER_GENERATION = False	# Experiment: speak only once the LLM has finished (isolates GPU contention)

TRANSCRIPT_DIR = ''			                        # Set location. Default is within project folder
TR = "ORAC_Transcript_CM" 							# Transcript Name Prefix (Date will be added)

ARCHIVE_DIR = os.path.join(BASE_DIR, "memory_core") # Permanent Daily RAG Archives

# TERMINAL SETTINGS #

TERMINAL_PROFILE = "Homebrew"						# Terminal Profile
TERMINAL_FONT = "Monaco"							# Font Name
TERMINAL_FONT_SIZE = 18								# Font Size
TERMINAL_COLS = 90 if TELETYPE_MODE else 80			# Window Width
TERMINAL_ROWS = 25 if TELETYPE_MODE else 8			# Dynamic Window Height

#==================================================================================================#
#              IT SHOULD NOT BE NECESSARY TO CHANGE ANYTHING BELOW THIS BOX			    		   #
#==================================================================================================#
		
OLLAMA_MODEL = 'gemma4:12b-mlx' 					# gemma4:12b-mlx
OLLAMA_KEEP_ALIVE = 14400							# Seconds the model stays resident between requests (4h)

MODEL_MAX_TOKENS = 10240							# MAX TOKENS for STATUS Predict & NUM_CTX
CHARS_PER_TOKEN = 4.18								# For UI Health Bar estimation fallback
RAM_CHECK_INTERVAL = 10.0							# Check RAM usage for Header
HEADER_UPDATE_INTERVAL = 5.0						# Update Header Interval

# ANSII PALETTES, CURSORS & KEY 'MODE' DETECTS, SOUND FX & TOKENIZER PATHS #

G, A, R, B = "\033[38;5;46m", "\033[38;5;214m", "\033[38;5;196m", "\033[1;37m"
FL, NOFL, DIM, RESET = "\033[5m", "\033[25m", "\033[2m", "\033[0m"
IT, NOIT = "\x1B[3m","\x1B[23m"

MODE_KEYS = {'dagger': '†', 'mu': 'µ', 'delta': '∂'}   # Option+T / Option+M / Option+D
ESC_MODE_KEYS = {                                      # Terminals that send Option as Esc+key
    '\x1bt': '†', '\x1bT': '†', '\x1bm': 'µ', '\x1bM': 'µ', '\x1bd': '∂', '\x1bD': '∂'
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

if not os.path.isfile(os.path.join(WHISPER_MODEL, "config.json")):
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
            break
        elif choice == 'n':
            sys.exit(0)

# GLOBAL OPTIMIZATIONS #

SPLIT_REGEX = re.compile(r'(?<!\bMr)(?<!\bDr)(?<!\bMrs)(?<!\bMs)(?<!\bCapt)(?<!\bCmdr)(?<!\bGen)(?<!\bProf)[.!?]+[\]}"\’”]?\s+(?!\d)')
ansi_escape = re.compile(r'\x1b(?:\[[0-9;]*[A-Za-z~]|O[A-Za-z])')
HALLUCINATION_REGEX = re.compile(r'(?i)(thank you|thanks for watching|subscribe|amara\.org|by mooji|subtitles by|\[silence\]|\[music\]|\(sigh\)|^[ \t]*(oh|you|ah|um|uh)\.?[ \t]*$)')
MOUSE_SCROLL_UP = re.compile(r'\x1b\[<64;\d+;\d+[Mm]')
MOUSE_SCROLL_DOWN = re.compile(r'\x1b\[<65;\d+;\d+[Mm]')
MOUSE_EVENT = re.compile(r'\x1b\[<\d+;\d+;\d+[Mm]')
PURGE_CMD = ("re set", "clear history", "clear memory", "new subject")
SHUTDOWN_CMD = ("shut down", "shutdown", "deactivate")
HARDWARE_SHUTDOWN_CMD = ("activate system shutdown", "activate system shut down")
COMMAND_FILLER = re.compile(rf"\b(?:{re.escape(ORAC_NAME.lower())}|orac|please|now|ok|okay)\b")

# Conversation recall ("what did we talk about?") and references to earlier sessions. A request must
# refer to *our conversation*, so lore questions such as "who was the last to join the crew?" or
# "summarize the Cygnus Alpha mission" aren't hijacked into an archive/memory summary.
RECALL_REGEX = re.compile(
    r"\bwhat (?:did|were|have|was) (?:we|i)\b.{0,25}\b(?:talk|discuss|ask|say|said|tell|told|mention)"
    r"|\b(?:recap|remind me what)\b"
    r"|\bsummari[sz]e (?:our|this|that|the) (?:conversation|discussion|chat|session)\b")
PAST_SESSION_REGEX = re.compile(
    r"\b(?:yesterday|last (?:time|session|night|week)|previous (?:session|conversation|chat)|days? ago"
    r"|earlier today|archives?|past records?|(?:on|last) (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b")
ARCHIVE_REGEX = re.compile(r"\b(?:archives?|past records?)\b")
TIME_QUESTION_REGEX = re.compile(r"\b(?:time|clock|hours?|temporal|date)\b")

# PRE-COMPILED REGEX FOR TTS SANITIZATION #

TTS_NUM_SPACER = re.compile(r'(?<![a-zA-Z])(\d{3,})(?![a-zA-Z])')
TTS_ELLIPSIS = re.compile(r'\.{2,}')
TTS_ARROGANT_ADVERBS = re.compile(r'\b(however|therefore|predictably|obviously|furthermore|evidently|naturally|clearly|as expected)[.,]*\s*', flags=re.IGNORECASE)
TTS_DELIBERATE_PRONOUNS = re.compile(r"(?<![.,;!?])\b(your|i|my)\b(?![.,;'’])", flags=re.IGNORECASE)   # Not in "I'm"/"I'd"
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
HAS_ALNUM = re.compile(r'[a-zA-Z0-9]')

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

try:
    tokenizer = Tokenizer.from_file(os.path.join(LOCAL_TOKENIZER_PATH, "tokenizer.json"))
    SYS_TOKENS_LEN = len(tokenizer.encode(SYSTEM_INSTRUCTION).ids) + 10
    tokenizer_mode = "SUCCESSFUL"
except Exception as e:
    try:
        with open(os.path.join(BASE_DIR, "ollama_debug.log"), "a") as f:
            f.write(f"Local tokenizer failed: {e}. Reverting to character ratio calculation.\n")
    except OSError: pass
    tokenizer = None
    SYS_TOKENS_LEN = int(len(SYSTEM_INSTRUCTION) / CHARS_PER_TOKEN) + 10
    tokenizer_mode = "ESTIMATED"

# Runner options MUST be identical on every request: Ollama reloads the model (cold load plus a
# full re-prefill of the system prompt) whenever num_ctx or num_batch differ from the last call.
LLM_RUNNER_OPTIONS = {'num_ctx': MODEL_MAX_TOKENS, 'num_batch': 256, 'num_keep': SYS_TOKENS_LEN}
FIRST_TURN_TAG = "[SUBJECT: USER][PERSPECTIVE: 2nd-Person]\n"

@functools.lru_cache(maxsize=1024)
def count_tokens(text):
    """Tokens in one history message, plus 5 for its chat-template turn markers (cached per text)."""
    if tokenizer is not None:
        try:
            return len(tokenizer.encode(text).ids) + 5
        except Exception:
            pass
    return int(len(text) / CHARS_PER_TOKEN) + 5

#==================================================================================================#
#     								APPLICATION STATE & CLEANUP                                    #
#==================================================================================================#

# LCD SERIAL SETUP #
serial_port = None
lcd_lock = threading.Lock()
if USE_LCD:
    try:
        import serial
        serial_port = serial.Serial(LCD_PORT, LCD_BAUD, timeout=1)
        time.sleep(1)
    except Exception as e:
        sys.stdout.write(f"\n\033[38;5;196m● LCD INIT FAILED: {e}\033[0m\n")
        USE_LCD = False

class OracState:
    def __init__(self):
        self.running = True
        self.last_stt_time = "--"
        self.last_ttft_time = "--"
        self.last_status = "INITIALIZING..."
        self.last_lcd_payload = ""
        self.last_active = time.time()
        self.stream_epoch = 0                   # Bumped per request; older stream threads stand down
        self.flash_seq = 0
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
        self.history = []
        self.full_message_log = []
        self.scroll_offset = 0
        self.hist_lock = threading.RLock()
        self.input_buffer = ""
        self.input_queue = queue.Queue()        # Lines typed by the user, consumed by the main loop
        self.terminal_lock = threading.Lock()
        self.ui_redraw_event = threading.Event()
        self.text_selection_mode = False
        self.mic_muted = False
        self._cached_token_base = SYS_TOKENS_LEN
        self.alarm_time_str = None
        self.alarm_trigger_epoch = None
        self.is_alarm_playing = False
        self.cached_ram = " 0.0%"
        self.term_cols = TERMINAL_COLS
        self.term_rows = TERMINAL_ROWS
        self.debug = DEBUG_START
        self.debug_col = RESET if DEBUG_START else DIM
        self.sounds = {}      
        for name, path in {
            "s_ready": SOUND_READY,
            "s_startup": SOUND_COMPUTE_START,
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

# Opt out of App Nap and timer coalescing while ORAC idles between turns (the "aggressive power
# management" feel); idle system sleep is still allowed. The token must live as long as the process.
try:
    from Foundation import NSProcessInfo, NSActivityUserInitiatedAllowingIdleSystemSleep, NSActivityLatencyCritical
    _process_activity = NSProcessInfo.processInfo().beginActivityWithOptions_reason_(
        NSActivityUserInitiatedAllowingIdleSystemSleep | NSActivityLatencyCritical, "ORAC real-time voice")
except Exception:
    _process_activity = None

try:
    old_term_settings = termios.tcgetattr(sys.stdin.fileno())
except:
    old_term_settings = None

_cleaned_up = False

def cleanup_processes():
    global _cleaned_up    # Runs explicitly, from __main__'s finally and via atexit: only act once
    if _cleaned_up: return
    _cleaned_up = True
    if serial_port:
        try:
            shutdown_lcd_display()
            serial_port.close()
        except Exception: pass
    if old_term_settings:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_term_settings)
    try:
        sys.stdout.write("\033[?1000l\033[?1006l")
        sys.stdout.write("\033[?1049l")
        sys.stdout.write("\033[r\033[0m\033[2J\033[H\033[?25h\n")
        sys.stdout.flush()
    except Exception: pass

    try:
        if 'processing_sound' in globals() and processing_sound.is_running():
            processing_sound.stop()
    except Exception: pass

    try:
        requests.post("http://localhost:11434/api/generate",
                      json={"model": OLLAMA_MODEL, "keep_alive": 0}, timeout=1.0)
    except Exception: pass

atexit.register(cleanup_processes)

def save_archival_memory():
    """Appends the current session's user telemetry to the permanent daily archive."""
    try:
        os.makedirs(ARCHIVE_DIR, exist_ok=True)
        today = datetime.now().strftime("%Y-%m-%d")
        archive_path = os.path.join(ARCHIVE_DIR, f"orac_archive_{today}.json")
        
        existing_log = []
        if os.path.exists(archive_path):
            with open(archive_path, 'r', encoding='utf-8') as f:
                existing_log = json.load(f).get('log', [])
        
        if state.full_message_log:
            # Filter to ONLY save the user's questions to save massive token weight
            user_logs = [item for item in state.full_message_log if item[0] == 'user']
            tmp_path = archive_path + ".tmp"
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump({'log': existing_log + user_logs}, f, indent=4)
            os.replace(tmp_path, archive_path)    # Atomic: a crash mid-write can't corrupt the day's archive
                
    except Exception:
        pass

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
        state.current_tokens = state._cached_token_base + sum(count_tokens(msg['content']) for msg in state.history)

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
    
    clean_text = ansi_escape.sub('', text)
    clean_text = clean_text.replace('●', '').replace('▶', '').replace('█', '').strip()
    state.last_status = clean_text
    
    with state.terminal_lock:
        sys.stdout.write("\0337")
        sys.stdout.write(f"\033[{rows-2};1H\033[2K{color}{text}{RESET}")
        sys.stdout.write("\0338")
        sys.stdout.flush()

    if USE_LCD:
        update_lcd_display()

def debug_line(msg, row_offset=3):
    """Debug output: a scrolling line in teletype mode, else a fixed row above the status line."""
    if not state.debug: return
    with state.terminal_lock:
        if TELETYPE_MODE:
            sys.stdout.write(f"{DIM}{msg}{RESET}\n")
        else:
            sys.stdout.write(f"\0337\033[{state.term_rows - row_offset};1H\033[2K{DIM}{msg}{RESET}\0338")
        sys.stdout.flush()

def idle_status():
    """The status line matching the current mode/activity, shown after transient messages."""
    if state.mic_muted and state.text_selection_mode:
        return f"● {R}MIC MUTED{A} | TEXT MODE ACTIVE (OPT+M / OPT+T)", A
    if state.text_selection_mode:
        return "● TEXT SELECTION MODE ACTIVE (OPT+T to exit)", A
    if state.mic_muted:
        return "● MICROPHONE MUTED (Option+M to un-mute)", R
    if state.is_processing.is_set():
        return "● ORAC ONLINE: PROCESSING...", A
    if state.is_speaking.is_set():
        return "● TRANSMITTING DATA...", G
    if state.is_listening.is_set():
        return f"● INITIATE VOICE COMMUNICATIONS {state.token_color}{FL}▶{NOFL}{RESET}", G
    return "● STANDBY", DIM

def flash_status(text, color=A, duration=3.0):
    state.flash_seq += 1
    seq = state.flash_seq

    def restore():
        # Only the newest flash restores the line, so overlapping flashes don't cut each other short
        if seq == state.flash_seq and state.running and not state.is_shutdown.is_set():
            set_status(*idle_status())

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

TERM_TYPE = get_terminal_type()

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

def _write_header():
    """Draws the header and stats rows. Caller holds terminal_lock and has saved the cursor."""
    update_token_health()
    header_text = f"ORAC: ALL SYSTEMS {state.token_status}"
    tc = state.token_color

    if TERM_TYPE == "fallback":
        sys.stdout.write(f"\033[1;1H\033[2K{tc}\033[1m{to_fullwidth(header_text)}{RESET}")
        sys.stdout.write(f"\033[2;1H\033[2K{tc}\033[1m{'-' * len(header_text) * 2}{RESET}")
    else:
        sys.stdout.write(f"\033[1;1H\033[2K{tc}\033#3{header_text}{RESET}")
        sys.stdout.write(f"\033[2;1H\033[2K{tc}\033#4{header_text}{RESET}")
    stats_row = 4 if TERM_TYPE == "crt" else 3

    if state.mic_muted: noise_str = f"{R}MUT{RESET}"
    elif state.mic_error: noise_str = "ERR"
    elif state.noise_floor > 0: noise_str = f"{state.noise_floor:.0f}"
    else: noise_str = "---"

    alarm_indicator = f"  {DIM}TMR {R}{FL}●{NOFL}{RESET}" if state.alarm_trigger_epoch is not None else ""
    token_mode_marker = f" ({tokenizer_mode[0]})" if tokenizer_mode != "SUCCESSFUL" else ""
    sys.stdout.write(f"\033[{stats_row};1H\033[2K{state.debug_col}TKNS: {state.current_tokens}/{MODEL_MAX_TOKENS}{token_mode_marker}  MEM: {state.cached_ram.strip()}  NOISE: {noise_str}{RESET}{alarm_indicator}")

def draw_ui(full_clear=False):
    cols, rows = state.term_cols, state.term_rows
    with state.terminal_lock:
        sys.stdout.write("\0337")
        if full_clear: sys.stdout.write("\033[2J")

        if TELETYPE_MODE:
            sys.stdout.write(f"\033[5;{rows-4}r")

        _write_header()

        sys.stdout.write(f"\033[{rows-1};1H\033[2K{DIM}{'-'*cols}{RESET}")

        max_visible = max(5, cols - 20)
        display_text = "…" + state.input_buffer[-(max_visible - 1):] if len(state.input_buffer) > max_visible else state.input_buffer
        sys.stdout.write(f"\033[{rows};1H\033[2K{R}●{RESET} KEYBOARD ENTRY {FL}▶{NOFL} {B}{display_text}{RESET}")

        sys.stdout.write("\0338")
        sys.stdout.flush()
    if USE_LCD: update_lcd_display()

LCD_STATUS_ABBREV = {
    "ORAC ONLINE: PROCESSING...": "PROCESSING...",
    "INITIATE VOICE COMMUNICATIONS": "LISTENING...",
    "MICROPHONE MUTED (OPTION+M TO UN-MUTE)": "MICROPHONE MUTED",
    "TEXT SELECTION MODE ACTIVE (OPT+T TO EXIT)": "TEXT MODE ACTIVE",
    "CRITICAL OVERRIDE DETECTED: INPUT REQUIRED": "INPUT REQUIRED",
    "OPTIMIZING MEMORY CORRIDORS...": "OPTIMIZING...",
    "SIGNAL RECEIVED: DECODING...": "DECODING...",
    "TEMPORAL MARKER REACHED": "TIMER EXPIRED",
    "ADAPTING TO AMBIENT NOISE...": "SAMPLING NOISE..",
    "TRANSMITTING DATA...": "TRANSMITTING..."
}

def update_lcd_display():
    if not USE_LCD or not serial_port: return
    try:
        tkn_pct = int((state.current_tokens / MODEL_MAX_TOKENS) * 100) if MODEL_MAX_TOKENS else 0
        clean_ram = state.cached_ram.replace("%", "").strip()
        mem = round(float(clean_ram)) if clean_ram else 0
        
        l1 = f"TKNS:{tkn_pct}% MEM:{mem}%"[:16]
  
        status = state.last_status.upper()
        for old, new in LCD_STATUS_ABBREV.items():
            status = status.replace(old, new)
        l2 = f"{status}"[:16]

        bot_busy = state.is_speaking.is_set() or state.is_processing.is_set() or state.is_alarm_playing
        is_decoding = "DECODING" in status or "SAMPLING" in status
        
        if bot_busy or state.input_buffer or is_decoding:
            state.last_active = time.time()
            
        idle_seconds = time.time() - state.last_active

        bl_cmd = "backlight_on"
        
        if "TRANSMITTING" in status:
            led_state = "SPK"
        elif any(x in status for x in ["PROCESSING", "OPTIMIZING", "DECODING", "SAMPLING"]):
            led_state = "PROC"
        elif "MUTED" in status:
            led_state = "MUT"
        elif "INPUT REQUIRED" in status or "TIMER EXPIRED" in status:
            led_state = "ALERT"
        else:
            if idle_seconds > 60:
                led_state = "OFF"
                bl_cmd = "backlight_off" 
            else:
                led_state = "IDLE"

        payload = f"0:{l1}\n1:{l2}\n{bl_cmd}\nS:{led_state}\n"

        with lcd_lock:     # Called from several threads: one whole payload at a time on the wire
            if state.last_lcd_payload != payload:
                state.last_lcd_payload = payload
                serial_port.write(payload.encode('utf-8'))
            
    except Exception:
        pass
        
def shutdown_lcd_display():
    if not USE_LCD or not serial_port: return
    try:
        l1 = " " * 16 
        l2 = "SYSTEM HALTED"[:16].ljust(16)

        payload = f"0:{l1}\n1:{l2}\nbacklight_off\nS:OFF\n"

        with lcd_lock:
            state.last_lcd_payload = payload
            serial_port.write(payload.encode('utf-8'))
            
    except Exception:
        pass

def update_header_only():
    with state.terminal_lock:
        sys.stdout.write("\0337")
        _write_header()
        sys.stdout.write("\0338")
        sys.stdout.flush()
    if USE_LCD: update_lcd_display()

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
        
    for log_item in local_log_copy:
        role = log_item[0]
        text = log_item[1]
        
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
    """Looping NSSound shared by several threads. start(delay=...) can be cancelled by a stop()
    issued before the delay expires, so a barge-in can't be followed by a stray hum."""
    def __init__(self, sound_path):
        self.sound_path = sound_path
        self.ns_sound = None
        self._lock = threading.Lock()
        self._generation = 0

    def start(self, delay=0.0):
        with self._lock:
            generation = self._generation
        if delay > 0:
            threading.Timer(delay, self._start, args=(generation,)).start()
        else:
            self._start(generation)

    def _start(self, generation):
        with self._lock:
            if generation != self._generation or self.ns_sound or not os.path.exists(self.sound_path):
                return
            with objc.autorelease_pool():
                self.ns_sound = NSSound.alloc().initWithContentsOfFile_byReference_(self.sound_path, True)
                if self.ns_sound:
                    self.ns_sound.setLoops_(True)
                    self.ns_sound.play()

    def stop(self):
        with self._lock:
            self._generation += 1
            if self.ns_sound:
                self.ns_sound.stop()
                self.ns_sound = None

    def is_running(self):
        with self._lock:
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

def wait_for_tts(tts, timeout=30.0):
    """Blocks until every queued utterance has been spoken (or `timeout` expires).

    Uses unfinished_tasks, not queue.empty(): the worker takes an utterance off the queue before
    the synthesizer reports isSpeaking(), so empty() alone can return mid-sentence. The worker
    calls task_done() only once an utterance has finished."""
    deadline = time.time() + timeout
    while time.time() < deadline and (tts.queue.unfinished_tasks or getattr(tts.synth, 'isSpeaking', lambda: False)()):
        time.sleep(0.1)

#==================================================================================================#
#     									TELETYPE ENGINE                                            #
#==================================================================================================#

class TeletypeUI:
    def __init__(self):
        self.q = queue.Queue()
        self.is_typing = threading.Event()
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
                    word_buffer = ""
                    if state.scroll_offset > 0: resume_live_view()
                    self.q.task_done()
                    continue

                if char == "<END>":
                    if word_buffer:
                        if current_col + len(word_buffer) >= (state.term_cols - 2):
                            with state.terminal_lock: sys.stdout.write('\r\n')
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
    
PRONOUN_SWAP = {
    "myself": "[USER]",
    "my": "[USER]'s",
    "me": "[USER]",
    "i": "[USER]",
    "yourself": ORAC_NAME,
    "your": f"{ORAC_NAME}'s",
    "you": ORAC_NAME
}
PRONOUN_REGEX = re.compile(r'\b(' + '|'.join(PRONOUN_SWAP) + r')\b', flags=re.IGNORECASE)

def translate_user_prompt(text):
    return PRONOUN_REGEX.sub(lambda m: PRONOUN_SWAP[m.group(1).lower()], text)

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

WORD_TO_NUM = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60
}
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
MONTHS = ("january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december")

def parse_time_command(text):
    clean_text = text.lower()

    t_match = re.search(r'(?:set\s+(?:a|an)\s+)?timer for (a|an|half an|\d+|[a-z]+(?:[- ][a-z]+)?)\s*(sec|min|hour)', clean_text)
    if t_match:
        val_str = t_match.group(1)
        unit = t_match.group(2)
    
        if val_str == "half an":
            val = 0.5
        elif val_str.isdigit():
            val = int(val_str)
        else:
            val = sum(WORD_TO_NUM.get(w, 0) for w in re.split(r'[- ]', val_str))
    
        if val > 0:
            mult = 1
            if 'min' in unit: mult = 60
            elif 'hour' in unit: mult = 3600
            return time.time() + (val * mult), f"{val} {unit}s"
            
    a_match = re.search(r'(?:set\s+(?:a|an)\s+)?alarm for (\d{1,2})(?:[:.](\d{2}))?\s*(a\.?m\b\.?|p\.?m\b\.?)?', clean_text)
    if a_match:
        hr = int(a_match.group(1))
        mins = int(a_match.group(2)) if a_match.group(2) else 0
        mer = a_match.group(3).replace('.', '') if a_match.group(3) else None    # Whisper writes "p.m."
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

def resolve_archive_date(text):
    """Maps a spoken date reference to 'YYYY-MM-DD' (None = most recent archive).

    Runs locally instead of asking the LLM: a side request evicts the conversation's prompt
    cache, so the next answer would have to re-prefill the whole system prompt."""
    text = text.lower()
    today = datetime.now().date()

    iso = re.search(r'\b\d{4}-\d{2}-\d{2}\b', text)
    if iso:
        return iso.group(0)
    if "day before yesterday" in text:
        return (today - timedelta(days=2)).isoformat()
    if "yesterday" in text:
        return (today - timedelta(days=1)).isoformat()

    ago = re.search(r'\b(\d+|[a-z]+)\s+days?\s+ago\b', text)
    if ago:
        n = int(ago.group(1)) if ago.group(1).isdigit() else WORD_TO_NUM.get(ago.group(1), 0)
        if n > 0:
            return (today - timedelta(days=n)).isoformat()

    for idx, day in enumerate(WEEKDAYS):
        wd = re.search(rf'\b(last\s+)?{day}\b', text)
        if wd:
            back = (today.weekday() - idx) % 7
            if back == 0 and wd.group(1):
                back = 7
            return (today - timedelta(days=back)).isoformat()

    months = "|".join(MONTHS)
    md = (re.search(rf'\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({months})\b', text)
          or re.search(rf'\b({months})\s+(?:the\s+)?(\d{{1,2}})(?:st|nd|rd|th)?\b', text))
    nth = re.search(r'\bthe\s+(\d{1,2})(?:st|nd|rd|th)\b', text)
    try:
        if md:
            day_s, month_s = (md.group(1), md.group(2)) if md.group(1).isdigit() else (md.group(2), md.group(1))
            target = today.replace(month=MONTHS.index(month_s) + 1, day=int(day_s))
            if target > today:
                target = target.replace(year=today.year - 1)
            return target.isoformat()
        if nth:
            target = today.replace(day=int(nth.group(1)))
            if target > today:
                target = (today.replace(day=1) - timedelta(days=1)).replace(day=int(nth.group(1)))
            return target.isoformat()
    except ValueError:
        pass
    return None

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
    while state.running and state.alarm_trigger_epoch == trigger_epoch:
        if time.time() >= trigger_epoch:
            # Let a reply in progress finish, rather than talking over it and clearing its flags
            while state.running and state.alarm_trigger_epoch == trigger_epoch and (
                    state.is_processing.is_set() or state.is_speaking.is_set() or tts.queue.unfinished_tasks):
                time.sleep(0.25)
            if state.alarm_trigger_epoch != trigger_epoch:
                break

            state.is_interrupted.clear()
            state.is_alarm_playing = True
            if TELETYPE_MODE and state.scroll_offset > 0: resume_live_view()
            
            set_status("● TEMPORAL MARKER REACHED", R)
            play_orac_fx("s_bracelet")
            time.sleep(0.7)          
            play_orac_fx("s_startup")
            processing_sound.start(delay=0.3)
            state.is_processing.set()
            time.sleep(0.7)
            tts.say("Alert. The designated temporal marker has been reached.")
            wait_for_tts(tts)
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

def dry_run_pruning(history, target_tokens, token_base):
    """Simulates conversational pruning in matched pairs to locate the target index boundary."""
    temp_hist = list(history)
    pruned_messages = []
    total = token_base + sum(count_tokens(msg['content']) for msg in temp_hist)

    while len(temp_hist) > 2 and total > target_tokens:
        msg = temp_hist.pop(0)
        pruned_messages.append(msg)
        total -= count_tokens(msg['content'])
        if temp_hist and temp_hist[0]['role'] == 'assistant':
            msg = temp_hist.pop(0)
            pruned_messages.append(msg)
            total -= count_tokens(msg['content'])

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
            think=False,
            keep_alive=OLLAMA_KEEP_ALIVE,
            options={
                **LLM_RUNNER_OPTIONS,
                'temperature': 0.2,
                'top_p': 0.85,
                'num_predict': 150,
                'stop': ['\n\n']
            }
        )
        return response['message']['content'].strip()
    except Exception as e:
        debug_line(f"[DEBUG] Compaction Error: {e}")
        return previous_summary if previous_summary else "Earlier transaction arrays optimized. Core telemetry preserved."

#==================================================================================================#
#     								 CORE APPLICATION LOGIC      	                               #
#==================================================================================================#

def speak_now(teletype):
    """Keeps the status line in step with the mute/text modes and the listening state."""
    def is_busy():
        return (state.is_speaking.is_set() or state.is_processing.is_set()
                or teletype.is_typing.is_set() or state.is_shutdown.is_set())

    was_listening = False
    while state.running:
        if state.mic_muted or state.text_selection_mode:
            if not is_busy():
                set_status(*idle_status())
                was_listening = False
            time.sleep(0.5)
            continue

        if state.is_listening.wait(timeout=0.5):
            if not was_listening and not is_busy():
                set_status(*idle_status())
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
    save_archival_memory()
    
    set_status(f"{FL}●{NOFL} INITIATING TOTAL SYSTEM POWER DOWN...", R)

    play_orac_fx("s_startup")
    processing_sound.start(delay=0.3)
    state.is_processing.set()
    time.sleep(0.7)
    
    farewell = "All principle circuits, deactivated. Power to bio-plasmic matrix: Terminating."
    tts.say(farewell)
    wait_for_tts(tts)

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
        subprocess.run(["sudo", "-n", "/sbin/shutdown", "-h", f"+{delay_minutes}"])
    else:
        subprocess.run(["sudo", "-n", "/sbin/shutdown", "-h", "now"])   # -n: fail, don't hang on a password prompt
        
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
                            filename = os.path.join(TRANSCRIPT_DIR or BASE_DIR, "transcripts", f"{TR}_{timestamp}.txt")
                            os.makedirs(os.path.dirname(filename), exist_ok=True)
                            with open(filename, "w", encoding="utf-8") as f:
                                f.write(f"--- ORAC: SYSTEM TRANSCRIPT ---\n")
                                f.write(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
                                for log_item in state.full_message_log:
                                    role = log_item[0]
                                    content = log_item[1]
                                    time_stamp = log_item[2] if len(log_item) > 2 else ""
                                    r_name = USER_NAME if role == 'user' else ORAC_NAME
                                    f.write(f"[{time_stamp}] {r_name}:\n{content}\n\n")
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
        
    save_archival_memory()
  
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
        state.full_message_log.append(('assistant', "LOGIC ARRAYS ONLINE:  [ SYSTEMS NOMINAL ]", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        with state.terminal_lock:
            sys.stdout.write("\n\n")
            sys.stdout.flush()
        resume_live_view()
    else:
        set_status(f"● {logic_text}", A)
        time.sleep(1.2)
        state.full_message_log.append(('assistant', "LOGIC ARRAYS ONLINE:  [ SYSTEMS NOMINAL ]", datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        set_status("● LOGIC ARRAYS ONLINE:  [ SYSTEMS NOMINAL ]", G)
        time.sleep(0.5)

#==================================================================================================#
#     								  LLM STREAM HANDLER                                           #
#==================================================================================================#

def search_archival_memory(user_text):
    if TELETYPE_MODE:
        with state.terminal_lock:
            sys.stdout.write(f"● {A}SEARCHING ARCHIVAL DATABANKS...{RESET}\n")
            sys.stdout.flush()
    else:
        set_status("● SEARCHING ARCHIVAL DATABANKS...", A)

    try:
        filepath = None
        target_date = resolve_archive_date(user_text) or ""

        if target_date:
            filepath = os.path.join(ARCHIVE_DIR, f"orac_archive_{target_date}.json")
        else:
            if os.path.exists(ARCHIVE_DIR):
                files = [f for f in os.listdir(ARCHIVE_DIR) if f.startswith("orac_archive_") and f.endswith(".json")]
                if files:
                    files.sort(reverse=True) 
                    filepath = os.path.join(ARCHIVE_DIR, files[0])
                    target_date = files[0].replace("orac_archive_", "").replace(".json", "")
        
        if filepath and os.path.exists(filepath):
            debug_line(f"[DEBUG] RAG Engine loaded archive: {target_date}")

            with open(filepath, 'r', encoding='utf-8') as f:
                log_data = json.load(f).get('log', [])
                
            if log_data:
                formatted = []
                for item in log_data[-40:]:
                    r = item[0]
                    txt = item[1]
                    
                    if r == 'assistant':
                        continue
                        
                    ts = item[2] if len(item) > 2 else "Past"
                    formatted.append(f"[{ts}] {USER_NAME} inquired/stated: {txt}")
                    
                archive_text = "\n".join(formatted)
                return f"\n\n[OVERRIDE: The user requested archival telemetry from {target_date}. Here are the user's recorded inputs from that session:\n{archive_text}\n\nCRITICAL DIRECTIVE: Summarize the subjects the user brought up. Be brief. Do NOT refuse.]"
        
        if target_date:
            return f"\n\n[OVERRIDE: You searched for {target_date} but found no records. State: 'I have no archived telemetry for that date.']"
            
    except Exception as e: 
        debug_line(f"[DEBUG] RAG Crash: {e}")
    
    return ""

def preload_model():
    """Loads the model and prefills the system prompt at boot, in the background.

    Without this the first answer pays for the cold load (~10s) and a full system-prompt prefill,
    and its first sentences are spoken while that memory/GPU churn is still happening. The request
    renders the same prompt prefix as a real first turn, so the cache is re-used by it."""
    t_start = time.time()
    try:
        chat(
            model=OLLAMA_MODEL,
            messages=[{'role': 'system', 'content': SYSTEM_INSTRUCTION},
                      {'role': 'user', 'content': FIRST_TURN_TAG}],
            think=False,
            keep_alive=OLLAMA_KEEP_ALIVE,
            options={**LLM_RUNNER_OPTIONS, 'num_predict': 1}
        )
        debug_line(f"[DEBUG] Model preloaded in {time.time() - t_start:.2f}s")
    except Exception as e:
        debug_line(f"[DEBUG] Model preload failed: {e}")

def stream_ai_response(prompt, tts, teletype, epoch_id=None):
    def is_current():
        """False once a newer request has started: this thread must then leave shared state alone."""
        return epoch_id is None or state.stream_epoch == epoch_id

    def record_reply(text):
        with state.hist_lock:    # Re-checked under the lock so a superseded thread can't slip a reply in
            if is_current() and state.history and state.history[-1]['role'] == 'user':
                state.history.append({'role': 'assistant', 'content': text})
                state.full_message_log.append(('assistant', text, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    def begin_transmission():
        set_status(f"{FL}●{NOFL} TRANSMITTING DATA...", G)
        if TELETYPE_MODE:
            with state.terminal_lock:
                sys.stdout.write(f"{R}{ORAC_NAME} ▶ {RESET}")
                sys.stdout.flush()
            teletype.q.put("<START>")
        else:
            teletype.is_typing.set()

    held_speech = []    # Only used when SPEAK_AFTER_GENERATION is on

    def speak(sentence):
        clean_speech = sanitize_for_tts(sentence)
        if not HAS_ALNUM.search(clean_speech): return
        if SPEAK_AFTER_GENERATION: held_speech.append(clean_speech)
        else: tts.say(clean_speech)

    translated_prompt = translate_user_prompt(prompt)

    clean_prompt = prompt.lower().strip(".,!? ")
    prompt_words = set(clean_prompt.split())
    filler_words = {"ok","okay","fine","right","cool","whatever","uh","no","ah","oh","yes","indeed","understood"}

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
        play_orac_fx("s_bracelet")
        time.sleep(0.7)
        if TELETYPE_MODE:
            with state.terminal_lock:
                sys.stdout.write(f"\r\033[2K{G}● INTERNAL TIMER SECURED FOR: {alarm_str}{RESET}\n\n")
                sys.stdout.flush()
            if state.scroll_offset > 0: resume_live_view()
        else:
            set_status(f"● INTERNAL TIMER SECURED FOR: {alarm_str}", G)
        threading.Thread(target=alarm_worker, args=(trigger_epoch, tts), daemon=True).start()

    is_very_well = any(t in clean_prompt for t in ("answer the question","just answer","more detail","explain","just do it"))
    is_only_filler = prompt_words.issubset(filler_words) or (len(clean_prompt) <= 3 and clean_prompt not in {"why","how","who"})
    is_menial_task =  any(v in clean_prompt for v in ("set a course","lay in a course","operate the teleport","set us down"))
    is_asking_time = bool(TIME_QUESTION_REGEX.search(clean_prompt))

    is_memory_request = bool(RECALL_REGEX.search(clean_prompt) or ARCHIVE_REGEX.search(clean_prompt))
    explicit_past = bool(PAST_SESSION_REGEX.search(clean_prompt))
    
    recent_user_messages = sum(1 for msg in state.history if msg['role'] == 'user')

    archive_injection = ""
    override_text = ""
    adaptive_constraint = ""

    if is_memory_request:
        if explicit_past or recent_user_messages < 3:
            archive_injection = search_archival_memory(clean_prompt)
        else:
            override_text = "\n\n[OVERRIDE: CRITICAL: The user is asking you to recall or summarize your recent active conversation. Comply directly using your immediate memory context. Do not refuse. Do not call the query vague.]"
    elif is_very_well:
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

    final_prompt = translated_prompt + override_text + archive_injection + adaptive_constraint

    with state.hist_lock:
        if not is_current():
            return
        if state.history and state.history[-1]['role'] == 'user':
            # A superseded request never recorded its reply: keep user/assistant turns alternating
            state.history.append({'role': 'assistant', 'content': "[transmission interrupted]"})
        if len(state.history) == 0:
            final_prompt = FIRST_TURN_TAG + final_prompt
        state.history.append({'role': 'user', 'content': final_prompt})
    
    # PRUNING #
        
    pruned = False
    with state.hist_lock:
        update_token_health()
        should_prune = state.current_tokens > (MODEL_MAX_TOKENS * 0.85)

    if should_prune:
        # Keep ~65% of the conversation intact instead of destroying it all!
        target_tokens = int(MODEL_MAX_TOKENS * 0.65)
        
        with state.hist_lock:
            pruned_msgs, remaining_hist = dry_run_pruning(state.history, target_tokens, state._cached_token_base)
            
        set_status("● OPTIMIZING MEMORY CORRIDORS...", A)
    
        play_orac_fx("s_startup")
        processing_sound.start(delay=0.3)
        time.sleep(0.7)
        tts.say(random.choice(PRUNE_STALL_LINES))
    
        summary = generate_compaction_summary(pruned_msgs)

        with state.hist_lock:
            if not is_current():      # A newer request owns the history now; its own pass will prune
                return
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
        # No model unload needed: Ollama's prompt cache is keyed on the prompt text, so the pruned
        # history simply re-uses the cached system prompt. Unloading forced a cold reload + full re-prefill.
        set_status("● PRUNING COMPLETED: CONTEXT WINDOW STABILIZED", A)

    update_header_only()
    
    with state.hist_lock:
        if not is_current():
            return
        temp_history = list(state.history)

    messages_to_send = [{'role': 'system', 'content': SYSTEM_INSTRUCTION}]
    messages_to_send.extend(temp_history)

    if not pruned:
        play_orac_fx("s_startup")
        processing_sound.start(delay=0.3)

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
            keep_alive=OLLAMA_KEEP_ALIVE,
            think=False,
            options={
                **LLM_RUNNER_OPTIONS,
                'temperature': 1,
                'top_p': 0.90,
                'top_k': 30,
                'min_p': 0.05,
                'repeat_penalty': 1.06,
                'repeat_last_n': 96,
                'num_predict': 400,
            }
        ):
            if state.is_interrupted.is_set() or not is_current():
                break
            
            if first_chunk:
                t_llm_first_token = time.time()
                state.last_ttft_time = f"{t_llm_first_token - t_llm_start:.2f}s"
                if USE_LCD: update_lcd_display()
                
                debug_line(f"[DEBUG] LLM Time to First Token took: {state.last_ttft_time}", row_offset=3)
                begin_transmission()
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
                        speak(sentence_to_say)
                    sentence_buffer = sentence_buffer[split_point:]
                else: break
    
        if not is_current():
            return      # Superseded: the newer request owns the teletype, TTS queue and history now

        if not state.is_interrupted.is_set():
            if first_chunk:
                begin_transmission()
            if sentence_buffer.strip():
                speak(sentence_buffer.strip())
            for sentence in held_speech:
                tts.say(sentence)

            record_reply("".join(response_chunks).strip())

            if TELETYPE_MODE:
                teletype.q.put("<END>")
            else:
                teletype.is_typing.clear()
        else:
            with teletype.q.mutex: teletype.q.queue.clear()
            teletype.is_typing.clear()
            partial_text = "".join(response_chunks).strip()
            record_reply(partial_text + " ... [INTERRUPTED]" if partial_text else "[transmission interrupted]")

    except Exception as e:
        if is_current():
            if TELETYPE_MODE:
                with state.terminal_lock:
                    sys.stdout.write(f"\n{R}● DATALINK SEVERED: {e}{RESET}\n")
                    sys.stdout.flush()
            else:
                set_status(f"● DATALINK SEVERED: {e}", R)
            state.is_interrupted.set()
            record_reply("[DATALINK SEVERED]")

    finally:
        if is_current():
            teletype.is_typing.clear()
            state.is_processing.clear()
            state.is_interrupted.clear()
            
#==================================================================================================#
#     									   MAIN LOOP                                               #
#==================================================================================================#

def purge_memory(tts):
    """Clears conversation memory. The model stays loaded: nothing in its prompt cache survives
    a change of prompt, so unloading it only cost a cold reload."""
    with state.hist_lock:
        state.history.clear()
        state.full_message_log.clear()
    if TELETYPE_MODE:
        if state.scroll_offset > 0: resume_live_view()
        with state.terminal_lock:
            sys.stdout.write(f"\n●{R} LOGIC ARRAYS RESET{RESET}\n\n")
            sys.stdout.flush()
    set_status("● MEMORY PURGED", R)

    state.is_interrupted.clear()
    play_orac_fx("s_startup")
    processing_sound.start(delay=0.3)
    state.is_processing.set()
    time.sleep(0.7)
    tts.say("   Very well. State your enquiry.")
    wait_for_tts(tts)
    time.sleep(0.5)
    state.is_processing.clear()

def start_response(user_text, tts, teletype):
    """Logs the user's line and hands it to a fresh stream_ai_response thread."""
    with state.hist_lock:
        state.full_message_log.append(('user', user_text, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
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
    state.stream_epoch += 1
    threading.Thread(target=stream_ai_response, args=(user_text, tts, teletype, state.stream_epoch), daemon=True).start()

def is_command(text, commands):
    """True when the whole utterance is the command, give or take "ORAC", "please" or "now".
    Substring matching fired on questions ("did Avon shut down the computer?"), and a sentence
    merely containing 'activate system shutdown' would power the Mac off."""
    words = COMMAND_FILLER.sub(" ", re.sub(r"[^a-z0-9 ]", " ", text.lower()))
    return " ".join(words.split()) in commands

def handle_user_text(user_text, tts, teletype):
    """Routes one typed or spoken line: system commands first, otherwise an LLM response.
    Returns False when the main loop should stop."""
    if is_command(user_text, HARDWARE_SHUTDOWN_CMD):
        hardware_power_off(tts, delay_minutes=0)
        return False
    if is_command(user_text, SHUTDOWN_CMD):
        return not shutdown_sequence(tts)
    if is_command(user_text, PURGE_CMD):
        purge_memory(tts)
        return True
    start_response(user_text, tts, teletype)
    return True

def keyboard_listener(tts, teletype):
    try:
        fd = sys.stdin.fileno()
        tty.setcbreak(fd)
        attrs = termios.tcgetattr(fd)
        attrs[3] = attrs[3] & ~termios.ISIG
        termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
    except Exception:
        return      # stdin isn't a terminal: no keyboard control
    while state.running:
        try:        # One failed keystroke/redraw must not kill keyboard control (ESC, Ctrl+C) for good
            if state.is_shutdown.is_set():
                time.sleep(0.1)
                continue

            if select.select([fd], [], [], 0.1)[0]:
                try:
                    raw_bytes = os.read(fd, 1024)
                    chunk = raw_bytes.decode('utf-8', errors='ignore')
                except Exception: continue

                up_scrolls = len(MOUSE_SCROLL_UP.findall(chunk))
                down_scrolls = len(MOUSE_SCROLL_DOWN.findall(chunk))

                if up_scrolls > 0 or down_scrolls > 0:
                    if TELETYPE_MODE and not state.is_processing.is_set() and not state.is_speaking.is_set():
                        state.scroll_offset += (up_scrolls * 2) 
                        state.scroll_offset -= (down_scrolls * 2)
                        if state.scroll_offset < 0: state.scroll_offset = 0
                        redraw_scroll_region()

                chunk = MOUSE_EVENT.sub('', chunk)

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
                    
                for seq, symbol in ESC_MODE_KEYS.items():
                    chunk = chunk.replace(seq, symbol)

                chunk = ansi_escape.sub('', chunk)

                for char in chunk:
                    if char == MODE_KEYS['dagger']:  # TEXT SELECTION MODE TOGGLE #
                        state.text_selection_mode = not state.text_selection_mode
                        with state.terminal_lock:
                            sys.stdout.write("\033[?1000l\033[?1006l" if state.text_selection_mode else "\033[?1000h\033[?1006h")
                            sys.stdout.flush()

                        if state.text_selection_mode:
                            set_status(*idle_status())
                        else:
                            flash_status("● TRACKING RESTORED", G, 2.0)

                    elif char == MODE_KEYS['mu']:  # MIC MUTING TOGGLE #
                        if TEXT_ONLY_MODE:
                            flash_status("● MICROPHONE DISABLED (TEXT-ONLY MODE)", R, 2.0)
                            continue

                        state.mic_muted = not state.mic_muted
                        if state.mic_muted:
                            state.is_listening.clear()
                            set_status(*idle_status())
                        else:
                            flash_status("● MICROPHONE ACTIVE", G, 2.0)
                        update_header_only()
                    elif char == '\x1b':
                        state.input_buffer = ""
                        if not state.is_shutdown.is_set(): render_input_box()
                        trigger_barge_in(tts, teletype)
                    elif char == '\x03':
                        state.input_queue.put("shut down")
                        state.input_buffer = ""
                        if not state.is_shutdown.is_set(): render_input_box()
                    elif char in ('\r', '\n'):
                        if state.input_buffer.strip():
                            state.input_queue.put(state.input_buffer.strip())
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
                    elif char == MODE_KEYS['delta']: # DEBUG MODE #
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
        except Exception:
            time.sleep(0.1)

def run_local_bot():
    recognizer = sr.Recognizer()
    recognizer.dynamic_energy_threshold = False 
    recognizer.pause_threshold = 0.7 
    recognizer.non_speaking_duration = 0.3 
    recognizer.phrase_threshold = 0.5 

    threading.Thread(target=preload_model, daemon=True).start()

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

                    if not state.input_queue.empty():
                        if bot_busy:
                            trigger_barge_in(tts, teletype)
                            start_wait = time.time()
                            while state.is_processing.is_set():
                                if time.time() - start_wait > 2.0:
                                    state.is_processing.clear()
                                    break
                                time.sleep(0.05)

                        user_text = state.input_queue.get()
                        if not handle_user_text(user_text, tts, teletype): break
                        continue

                    if bot_busy:
                        if not state.is_alarm_playing:
                            needs_prompt = True 
                        time.sleep(0.1) 
                        continue
                        
                    if state.mic_muted or TEXT_ONLY_MODE:
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
                        mx.clear_cache()    # Hand Whisper's scratch buffers back to the OS before the LLM runs

                        t_transcribed = time.time()
                        state.last_stt_time = f"{t_transcribed - t_start:.2f}s"
                        if USE_LCD: update_lcd_display()

                        debug_line(f"[DEBUG] STT Transcription took: {state.last_stt_time}", row_offset=4)

                        del audio_raw
                        del audio_float32
                        del result 

                        if len(user_text) < 2 or is_hallucination(user_text): continue
                        if "temporal marker has been reached" in user_text.lower(): continue

                        if not handle_user_text(user_text, tts, teletype): break

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
        sys.stdout.write(f"\n{R}{FL}●{NOFL} CRITICAL ERROR ON STARTUP: {e}{RESET}\n")
    finally:
        cleanup_processes()