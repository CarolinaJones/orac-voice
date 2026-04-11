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
#import warnings

from ollama import chat
from AppKit import NSSpeechSynthesizer


from orac_phonetics import orac_phonetics
from orac_data_core import data_core
from orac_personality import orac_personality

# Attempt to resolve the "There appear to be 1 leaked semaphore..." warning caused by os._exit(0)
from multiprocessing import resource_tracker
#warnings.filterwarnings("ignore", category=UserWarning, module="resource_tracker")

#---------------------------------------------------#
#     ORAC-VOICE v1.0.2 (Lore friendly VoiceChat)	#
#          Copyright © 2026 Caroline Mayne			#
#		   https://github.com/CarolinaJones/	   	#
#––––––––––––––––––––––––––––––––––––––––––––-----––#

#------------------------------------#
#      USER CHANGEABLE VARIABLES     #
#------------------------------------#

VOICE = "" 			# Leave blank to use the "System Voice" - This allows for SIRI/Personal Voices.
voice_pitch = 80.0 	# Only works on SYNTH voices and not SIRI/Personal voices.

U1 = 0.06 											# Teletype Speed
U2 = 0.071 											# Teletype Uniformity

TRANSCRIPT_DIR = ''									# A Directory called orac_transcripts will be created.
TR = "ORAC_Transcript_CM" 							# Transcript Name Prefix (Date will be added).

YOUR_NAME = "Jenna" 								# USER Name and Identity
ORAC_NAME = "ORAC" 									# ORAC's Name

# TERMINAL SETTINGS #
TERMINAL_PROFILE = "Homebrew"						# Terminal Profile
TERMINAL_FONT = "AdwaitaMono Nerd Font Mono"		# Font Name
TERMINAL_FONT_SIZE = 17								# Font Size
TERMINAL_COLS = 100									# Window Width
TERMINAL_ROWS = 25									# Window Height

# IT SHOULD NOT BE NECESSARY TO CHANGE ANYTHING BELOW THIS LINE #
#--------------------------------------------------------------------------------------------------#

#------------------#
# MODEL VARIABLES  #
#------------------#

OLLAMA_MODEL = 'mannix/gemma2-9b-simpo:latest'		# gemma2:9b-simpo WORKS best for ORAC
MODEL_MAX_TOKENS = 8192								# MAX TOKENS for STATUS Predict & NUM_CTX
WHISPER_MODEL = './whisper/whisper-large-v3-turbo'	# WHISPER-MLX Model

#------------------------------------#
# ANSII PALETTES & CURSORS - SOUNDS  #
#------------------------------------#

G, A, R, B = "\033[38;5;46m", "\033[38;5;214m", "\033[38;5;196m", "\033[1;37m"
FL, NOFL, DIM, RESET = "\033[5m", "\033[25m", "\033[2m", "\033[0m"
IT, NOIT = "\x1B[3m","\x1B[23m" # Italics on and off

# Get the directory of the current script for absolute paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SOUND_PROCESSING = os.path.join(BASE_DIR, "resources/sounds/orac-hum_16k.mp3")
SOUND_COMPUTE_START = os.path.join(BASE_DIR, "resources/sounds/orac-startup_16k.mp3")
SOUND_COMPUTE_END = os.path.join(BASE_DIR, "resources/sounds/orac-shutdown_16k.mp3")
SOUND_SHUTDOWN = os.path.join(BASE_DIR, "resources/sounds/orac-shutdown_16k.mp3")
SOUND_READY = os.path.join(BASE_DIR, "resources/sounds/sub_16k.mp3")
SOUND_QUIT = os.path.join(BASE_DIR, "resources/sounds/funk_16k.mp3")

#----------------------#
# GLOBAL OPTIMIZATIONS #
#----------------------#

SPLIT_REGEX = re.compile(r'(?<!\bMr)(?<!\bDr)(?<!\bMrs)(?<!\bMs)(?<!\bCapt)(?<!\bCmdr)(?<!\bGen)(?<!\bProf)[.!?]+[\]}"\’”]?\s+')
ansi_escape = re.compile(r'\x1b(?:\[[0-9;]*[A-Za-z~]|O[A-Za-z])')
HALLUCINATION_REGEX = re.compile(r'(thank you|thanks for watching|subscribe|amara\.org|by mooji|subtitles by|\[silence\]|\[music\]|\(sigh\)|^[ \t]*you\.?[ \t]*$)')
PURGE_CMD = ("re set", "clear history", "New Subject")
SHUTDOWN_CMD = ("shut down", "deactivate", "quit")

#---------------------------------------#
# EXTERNAL ORAC_PERSONALITY & CORE_CORE #
#---------------------------------------#

SYSTEM_INSTRUCTION = f"{orac_personality}\n{data_core}"

#-------------------#
# APPLICATION STATE #
#-------------------#

class OracState:
    def __init__(self):
        self.running = True
        
        self.current_tokens = 0
        self.token_status = "NOMINAL"
        self.token_color = G  # Starts Green
        self.noise_floor = 0.0 # Tracks room audio calibration dynamically
              
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
        
        self.input_buffer = ""
        self.input_ready = threading.Event()
        self.submitted_text = ""
        self.terminal_lock = threading.Lock()
        self.ui_needs_redraw = False

state = OracState()

try:
    old_term_settings = termios.tcgetattr(sys.stdin.fileno())
except:
    old_term_settings = None

def cleanup_processes():
    if old_term_settings:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_term_settings)
    
    try:
        sys.stdout.write("\033[?1000l\033[?1006l") 	# Disable Mouse Tracking
        sys.stdout.write("\033[?1049l") 			# Exit Alternate Screen Buffer
        sys.stdout.write("\033[r\033[?25h\n") 		# Reset scroll region and show cursor
        sys.stdout.flush()
    except: pass
    
    if 'processing_sound' in globals() and processing_sound.is_running():
        processing_sound.stop()
        
    # Attempt resolution of crashing on exit
    with state.proc_lock:
        for proc in state.active_procs:
            try:
                if proc and proc.poll() is None: proc.terminate()
            except Exception: pass

atexit.register(cleanup_processes)

def hard_shutdown():
    # Tell the tracker to stop monitoring before crashing out
    try:
        resource_tracker._resource_tracker._stop()
    except:
        pass
    os._exit(0)

#-------------------------------------#
# TERMINAL SETUP AND UI LAYOUT ENGINE #
#-------------------------------------#

def setup_terminal():
    if sys.platform != "darwin":
        sys.stdout.write(f"\033[8;{TERMINAL_ROWS};{TERMINAL_COLS}t")
        sys.stdout.write("\033[?1049h\033[?1000h\033[?1006h\033[2J\033[H")
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
    
    sys.stdout.write("\033[?1049h\033[?1000h\033[?1006h\033[2J\033[H")
    sys.stdout.flush()
    
# Experimenting with Token counting and updating status/header    
def update_token_health():
    # Heuristic: 1 token is roughly 4 characters
    # Start with SYSTEM_INSTRUCTION
    total_chars = len(SYSTEM_INSTRUCTION)
    
    # Add current conversation history
    total_chars += sum(len(msg['content']) for msg in state.history) 
    
    # Add buffer for injected reminders and system overhead
    total_chars += 350 
    
    state.current_tokens = total_chars // 4
    percent = state.current_tokens / MODEL_MAX_TOKENS
    
    # Traffic Light Logic For Header
    if percent < 0.70:
        state.token_status = "NOMINAL"
        state.token_color = G # Green
    elif percent < 0.85:
        state.token_status = "WARNING: SUB-OPTIMAL"
        state.token_color = A # Amber/Yellow
    else:
        state.token_status = "CRITICAL: SLIDING"
        state.token_color = R # Red 

def get_ram_string():
    try:
        ram_percent = psutil.virtual_memory().percent
        return f" {ram_percent}%"  
    except Exception:
        return ""

def set_status(text, color=G):
    cols, rows = shutil.get_terminal_size()
    with state.terminal_lock:
        sys.stdout.write("\0337") 
        sys.stdout.write(f"\033[{rows-2};1H\033[2K{color}{text}{RESET}")
        sys.stdout.write("\0338") 
        sys.stdout.flush()

def draw_ui(full_clear=False):
    cols, rows = shutil.get_terminal_size()
    with state.terminal_lock:
        sys.stdout.write("\0337") 
        if full_clear:
            sys.stdout.write("\033[2J") # Nuke all 'Ghosting'
            
        # Shifted scroll region down to Row 5
        sys.stdout.write(f"\033[5;{rows-4}r") 
        
        TOP = "\033#3"
        BOTTOM = "\033#4"
        
        update_token_health() # Calculate before drawing
        
        # Main Header (Double Height)
        header_text = f"ORAC: ALL SYSTEMS {state.token_status}"
        tc = state.token_color 
        sys.stdout.write(f"\033[1;1H\033[2K{tc}{TOP}{header_text}{RESET}")
        sys.stdout.write(f"\033[2;1H\033[2K{tc}{BOTTOM}{header_text}{RESET}")
        
        # System Stats Bar (Tokens, Memory, Noise Floor - Left-Aligned on Row 3)
        if state.mic_error: noise_str = "ERR"
        elif state.noise_floor > 0: noise_str = f"{state.noise_floor:.0f}"
        else: noise_str = "---"
        
        stats_text = f"TKNS: {state.current_tokens}/{MODEL_MAX_TOKENS}   MEM: {get_ram_string().strip()}   NOISE: {noise_str}"
        sys.stdout.write(f"\033[3;1H\033[2K{DIM}{stats_text}{RESET}") 
              
        # Bottom UI Elements
        sys.stdout.write(f"\033[{rows-1};1H\033[2K{DIM}{'-'*cols}{RESET}")
        
        max_visible = max(5, cols - 20) 
        if len(state.input_buffer) > max_visible:
            display_text = "…" + state.input_buffer[-(max_visible - 1):]
        else:
            display_text = state.input_buffer
            
        sys.stdout.write(f"\033[{rows};1H\033[2K{R}●{RESET} KEYBOARD ENTRY {FL}▶{NOFL} {B}{display_text}{RESET}")
            
        sys.stdout.write("\0338") 
        sys.stdout.flush()

def update_header_only():
    with state.terminal_lock:
        TOP, BOTTOM = "\033#3", "\033#4"
        update_token_health() # Calculate before drawing
        
        header_text = f"ORAC: ALL SYSTEMS {state.token_status}"
        tc = state.token_color
        
        sys.stdout.write("\0337") 
        sys.stdout.write(f"\033[1;1H\033[2K{tc}{TOP}{header_text}{RESET}")
        sys.stdout.write(f"\033[2;1H\033[2K{tc}{BOTTOM}{header_text}{RESET}")
        
        # System Stats Bar (Tokens, Memory, Noise Floor - Left-Aligned on Row 3)
        if state.mic_error: noise_str = "ERR"
        elif state.noise_floor > 0: noise_str = f"{state.noise_floor:.0f}"
        else: noise_str = "---"
        
        stats_text = f"TKNS: {state.current_tokens}/{MODEL_MAX_TOKENS}   MEM: {get_ram_string().strip()}   NOISE: {noise_str}"
        sys.stdout.write(f"\033[3;1H\033[2K{DIM}{stats_text}{RESET}") 
        
        sys.stdout.write("\0338") 
        sys.stdout.flush()

def ui_refresh_worker():
    counter = 0
    while state.running:
        if state.ui_needs_redraw:
            state.ui_needs_redraw = False
            draw_ui(full_clear=True) # Clear screen and draw borders
            if state.scroll_offset > 0: 
                redraw_scroll_region()
            else:
                resume_live_view()   # Restore the chat history
            render_input_box()       # Restore the typing prompt       
            
            # Exiting fullscreen pushes the native cursor to the absolute bottom row, 
            # breaking the teletype scroll region. Force the cursor back where it belongs.
            cols, rows = shutil.get_terminal_size()
            lines = get_wrapped_history_lines(cols)
            
            # Calculate exactly where the teletype cursor should resume
            if state.scroll_offset > 0:
                target_row = rows - 4
            else:
                target_row = min(rows - 4, 5 + len(lines))
                
            with state.terminal_lock:
                sys.stdout.write(f"\033[{target_row};1H")
                sys.stdout.flush()
                
        elif counter >= 5: 
            update_header_only()
            counter = 0
            
        time.sleep(0.5)
        counter += 1

def flag_ui_redraw(signum=None, frame=None):
    state.ui_needs_redraw = True

signal.signal(signal.SIGWINCH, flag_ui_redraw)

def render_input_box():
    cols, rows = shutil.get_terminal_size()
    max_visible = max(5, cols - 20) 
    
    if len(state.input_buffer) > max_visible:
        display_text = "…" + state.input_buffer[-(max_visible - 1):]
    else:
        display_text = state.input_buffer

    with state.terminal_lock:
        sys.stdout.write("\0337") 
        sys.stdout.write(f"\033[{rows};1H\033[2K{RESET}● KEYBOARD ENTRY ▶ {B}{display_text}{FL}█{NOFL}{RESET}")
        sys.stdout.write("\0338") 
        sys.stdout.flush()

#----------------------------------#
# TERMINAL SCROLL HISTORY MANAGERS #
#----------------------------------#

def get_wrapped_history_lines(cols):
    lines = []
    safe_width = cols - 2 
    
    for role, text in state.full_message_log:
        clean_prefix = f"{YOUR_NAME} ▶ " if role == 'user' else f"{ORAC_NAME} ▶ "
        color = f"{B}{IT}" if role == 'user' else f"{R}"
        
        prefix_len = len(clean_prefix)
        wrap_width = safe_width - prefix_len
        if wrap_width < 10: wrap_width = 10 
        
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
    cols, rows = shutil.get_terminal_size()
    visible_rows = rows - 8 # Adjusted for the top divider or blank line thingy 
    
    lines = get_wrapped_history_lines(cols)
    display_lines = lines[-visible_rows:] if len(lines) > visible_rows else lines
    
    with state.terminal_lock:
        sys.stdout.write("\0337") 
        
        for i in range(5, rows-3): # Shifted to Row 5
            sys.stdout.write(f"\033[{i};1H\033[2K")
            
        for i, line in enumerate(display_lines):
            sys.stdout.write(f"\033[{i+5};1H{line}") # Shifted to Row 5
            
        sys.stdout.write("\0338") 
        sys.stdout.flush()

def redraw_scroll_region():
    if state.scroll_offset <= 0:
        resume_live_view()
        return
        
    cols, rows = shutil.get_terminal_size()
    visible_rows = rows - 8 # Adjusted for the top divider (as above) 
    
    lines = get_wrapped_history_lines(cols)
    max_offset = max(0, len(lines) - visible_rows)
    state.scroll_offset = min(state.scroll_offset, max_offset)
    
    start_idx = max(0, len(lines) - visible_rows - state.scroll_offset)
    display_lines = lines[start_idx : start_idx + visible_rows]
    
    with state.terminal_lock:
        sys.stdout.write("\0337") 
        
        for i in range(5, rows-3): # Shifted to Row 5
            sys.stdout.write(f"\033[{i};1H\033[2K")
            
        for i, line in enumerate(display_lines):
            sys.stdout.write(f"\033[{i+5};1H{line}") # Shifted to Row 5
            
        indicator = f" {B}{FL}[ SCROLLING HISTORY: OFFSET {state.scroll_offset} ]{NOFL}{RESET} "
        # Tucks the scrolling indicator neatly onto Row 3 (right side) so it doesn't break the divider
        sys.stdout.write(f"\033[3;{cols - 45}H{indicator}")
        
        sys.stdout.write("\0338")
        sys.stdout.flush()

#-------------------------#
# AUDIO/TTS CLASSES LOGIC #
#-------------------------#

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
        except Exception: pass
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
                wait_time = max(0.1, self.duration - self.overlap)
                if self.stop_event.wait(wait_time): break
            else:
                while proc.poll() is None:
                    if self.stop_event.wait(0.01): break
                if self.stop_event.is_set(): break

        for p in procs:
            try:
                if p.poll() is None: p.terminate()
            except Exception: pass

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
                
                while self.synth.isSpeaking():
                    if state.is_interrupted.is_set():
                        self.synth.stopSpeaking()
                        break
                    time.sleep(0.02) 
                
                self.queue.task_done()
                
                if self.queue.empty() and not state.is_processing.is_set() and not state.is_interrupted.is_set():
                    if processing_sound.is_running():
                        processing_sound.stop()
                        end_proc = play_once(SOUND_COMPUTE_END)
                        if end_proc:
                            try:
                                end_proc.wait(timeout=1.0) 
                            except Exception:
                                pass
                            
                            time.sleep(0.6) # Delay so orac_shutdown and prompt sound don't overlap 
                    
                    state.is_speaking.clear()
                    time.sleep(0.2) 
            except queue.Empty:
                continue

    def say(self, text):
        if text.strip():
            self.queue.put(text)
            
    def stop_speaking(self):
        self.synth.stopSpeaking()

#-------------#
# TELETYPE UI #
#-------------#

class TeletypeUI:
    def __init__(self):
        self.q = queue.Queue()
        self.is_typing = threading.Event()
        self.lines_printed = 0
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()

    def _worker(self):
        cols, rows = shutil.get_terminal_size()
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
                    cols, rows = shutil.get_terminal_size()
                    current_col = len(ORAC_NAME) + 3 
                    self.lines_printed = 0 
                    word_buffer = ""
                    
                    if state.scroll_offset > 0: resume_live_view()
                    self.q.task_done()
                    continue

                if char == "<END>":
                    if word_buffer:
                        if current_col + len(word_buffer) >= (cols - 2):
                            with state.terminal_lock: sys.stdout.write('\n')
                            self.lines_printed += 1
                            current_col = 0
                        for w_char in word_buffer:
                            with state.terminal_lock:
                                sys.stdout.write(f"{A}{w_char}{FL}█{NOFL}{RESET}")
                                sys.stdout.flush()
                            time.sleep(0.02)
                            with state.terminal_lock:
                                sys.stdout.write("\b \b") 
                    word_buffer = ""
                    self.is_typing.clear()
                    
                    with state.terminal_lock:
                        sys.stdout.write(f"\n{DIM}● DATA STREAM END{RESET}\n\n")
                        sys.stdout.flush()
                        
                    self.q.task_done()
                    continue

                if char in [' ', '\n', '\r', '\t']:
                    # Update columns dynamically in case window was resized during typing
                    cols, _ = shutil.get_terminal_size() 
                    
                    if current_col + len(word_buffer) >= (cols - 2):
                        with state.terminal_lock: sys.stdout.write('\n')
                        self.lines_printed += 1
                        current_col = 0
                    
                    for w_char in word_buffer:
                        if state.is_interrupted.is_set(): break
                            
                        with state.terminal_lock:
                            sys.stdout.write(f"{A}{w_char}{FL}█{NOFL}{RESET}")
                            sys.stdout.flush()
                        
                        if w_char in ['.', '!', '?']: time.sleep(0.10) 
                        elif w_char in [',', ':', ';']: time.sleep(0.05) 
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
            except queue.Empty:
                continue

#-----------------#
# AUTOMATIC LOGIC #
#-----------------#

def sanitize_for_tts(text):
    # APPLY EXTERNAL PHONETIC CORRECTIONS 
    # Reference the external Phonetics Database
    try:
        text = orac_phonetics(text)
    except Exception:
        pass # Prevents the script from crashing if phonetics fails for any reason

    # Make numbers work better - 3 or more numbers spaced ignoring numbers attached to letters
    text = re.sub(r'(?<![a-zA-Z])(\d{3,})(?![a-zA-Z])', lambda m: ' '.join(m.group(1)), text)
       
    # APPLY PUNCTUATION AND PACING RULES
    text = re.sub(r'\.{2,}', '... ', text)
    
    # Force a mechanical, arrogant pause around these specific words
    for word in ['however', 'therefore', 'predictably', 'obviously', 'Of course', 'logically', 'My', 'I', 'your', 'What is it', 'Be precise', 'furthermore']:
        text = re.sub(rf'(?<![.,;])\b({word})\b(?![.,;])', r', \1, ', text, flags=re.IGNORECASE)

    # Strip purely visual markdown but leave punctuation intact
    text = re.sub(r'[*`_~#>|+]', ' ', text)    
    
    # Brackets to commas (creates a pause for parenthetical statements)
    text = re.sub(r'[\[\]{}()]', ', ', text)    
    
    # Remove quotes (To avoid macOS TTS changing voice pitch awkwardly on quotes)
    text = text.replace('“', '').replace('”', '').replace('"', '')
    text = re.sub(r"(?<!\w)[']|['](?!\w)", "", text)    
    
    # Clean up accidental duplicate commas and spaces
    text = re.sub(r',\s*,', ',', text)
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r' ,\b', ', ', text) # Removes space *before* a comma
    text = re.sub(r',\s*([.!?])', r'\1', text)
    
    # Strip leading weirdness but NOT numbers/letters
    text = re.sub(r'^[^a-zA-Z0-9]+', '', text)    
    
    # NEW: Strip trailing commas, hyphens, or semicolons so TTS doesn't say 'comma'
    text = re.sub(r'[,;\-\s]+$', '', text)
    
    # FORCE IMPATIENT "VERY WELL" & "Be precise": Removing trailing commas/ellipses
    text = re.sub(r'(?i)\b(very well)[.,]*\s*', r'\1! ', text) 
    text = re.sub(r'(?i)\b(Be precise)[.,]*\s*', r'\1! ', text)
    
    return text.strip()

def trigger_barge_in(tts, teletype):
    if not state.is_processing.is_set() and not state.is_speaking.is_set() and not teletype.is_typing.is_set():
        return 
        
    state.is_interrupted.set()
    
    with teletype.q.mutex: teletype.q.queue.clear()
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
    state.is_processing.clear() 
    time.sleep(0.5) 

def process_text_input(user_text, tts, teletype):
    bot_busy = state.is_speaking.is_set() or state.is_processing.is_set() or teletype.is_typing.is_set() or not tts.queue.empty()
    if bot_busy:
        trigger_barge_in(tts, teletype)
        time.sleep(0.1)

    if any(cmd in user_text.lower() for cmd in SHUTDOWN_CMD):
        threading.Thread(target=shutdown_sequence, args=(tts,), daemon=True).start()
        return
        
    if any(cmd in user_text.lower() for cmd in PURGE_CMD):
        state.history.clear()
        state.full_message_log.clear()
        if state.scroll_offset > 0: resume_live_view()
        with state.terminal_lock:
            sys.stdout.write(f"\n●{R} LOGIC ARRAYS RESET{RESET}\n\n")
            sys.stdout.flush()
        set_status("● MEMORY PURGED", R)
        tts.say("Very well. State your enquiry.")
        return

    state.full_message_log.append(('user', user_text))
    if len(state.full_message_log) > 2000: state.full_message_log.pop(0)
    if state.scroll_offset > 0: resume_live_view()
    
    with state.terminal_lock:
        sys.stdout.write(f"\r\033[2K{B}{IT}{YOUR_NAME}{NOIT} ▶ {user_text}{RESET}\n\n")
        sys.stdout.flush()
        
    state.is_interrupted.clear()
    state.is_listening.clear()
    state.is_processing.set()
    threading.Thread(target=stream_ai_response, args=(user_text, tts, teletype), daemon=True).start()

def keyboard_listener(tts, teletype):
    fd = sys.stdin.fileno()
    
    try:
        tty.setcbreak(fd)
        # DISABLE ISIG: Stop the OS from sending SIGINT to the frozen Main Thread 
        # and instead allow background thread to read CTRL+C as raw text (\x03)
        attrs = termios.tcgetattr(fd)
        attrs[3] = attrs[3] & ~termios.ISIG
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        
        while state.running:
            if state.is_shutdown.is_set(): 
                time.sleep(0.1)
                continue
                
            if select.select([fd], [], [], 0.1)[0]:
                try:
                    raw_bytes = os.read(fd, 1024)
                    chunk = raw_bytes.decode('utf-8', errors='ignore')
                except Exception: continue
                
                # MOUSE SCROLLING LOGIC
                up_scrolls = len(re.findall(r'\x1b\[<64;\d+;\d+[Mm]', chunk))
                down_scrolls = len(re.findall(r'\x1b\[<65;\d+;\d+[Mm]', chunk))
                
                if up_scrolls > 0 or down_scrolls > 0:
                    if not state.is_processing.is_set() and not state.is_speaking.is_set():
                        state.scroll_offset += (up_scrolls * 2) 
                        state.scroll_offset -= (down_scrolls * 2)
                        if state.scroll_offset < 0: state.scroll_offset = 0
                        redraw_scroll_region()
                        
                chunk = re.sub(r'\x1b\[<\d+;\d+;\d+[Mm]', '', chunk)
                
                # KEYBOARD SCROLLING LOGIC
                if not state.is_processing.is_set() and not state.is_speaking.is_set():
                    if '\x1b[A' in chunk or '\x1b[5~' in chunk: 
                        state.scroll_offset += 5
                        redraw_scroll_region()
                        chunk = chunk.replace('\x1b[A', '').replace('\x1b[5~', '')
                    elif '\x1b[B' in chunk or '\x1b[6~' in chunk: 
                        state.scroll_offset -= 5
                        if state.scroll_offset < 0: state.scroll_offset = 0
                        redraw_scroll_region()
                        chunk = chunk.replace('\x1b[B', '').replace('\x1b[6~', '')

                if '\x1b' in chunk and state.scroll_offset > 0:
                    resume_live_view()
                
                chunk = ansi_escape.sub('', chunk)
                
                for char in chunk:
                    if char == '\x1b': 
                        state.input_buffer = ""
                        if not state.is_shutdown.is_set(): render_input_box()
                        trigger_barge_in(tts, teletype)
                    elif char == '\x03': 
                        state.input_buffer = ""
                        if not state.is_shutdown.is_set(): render_input_box()
                        process_text_input("shut down", tts, teletype)
                    elif char in ('\r', '\n'): 
                        if state.input_buffer.strip():
                            user_text = state.input_buffer.strip()
                            state.input_buffer = ""
                            if not state.is_shutdown.is_set(): render_input_box()
                            process_text_input(user_text, tts, teletype)
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

def speak_now(tts, teletype):
    idle_fault_counter = 0
    while state.running:
        # Check if ORAC is currently doing anything at all
        bot_busy = state.is_speaking.is_set() or state.is_processing.is_set() or teletype.is_typing.is_set() or not tts.queue.empty() or state.is_shutdown.is_set()
        
        if bot_busy:
            idle_fault_counter = 0 # Reset watchdog
        else:
            if state.is_listening.is_set():
                idle_fault_counter = 0 # Mic is active and healthy
                if not getattr(state, 'mic_error', False):
                    tc = state.token_color
                    set_status(f"● INITIATE VOICE COMMUNICATIONS {tc}{FL}▶{NOFL}{RESET}", G)
            else:
                # MIC disconnected and will no longer be available in this session (THIS NEEDS WORK - Re-detection, etc.)
                idle_fault_counter += 1
                if idle_fault_counter > 10: # Wait 5 seconds (10 x 0.5s tick) to prevent false triggers during calibration
                    # Force the UI to fallback mode
                    state.mic_error = True
                    set_status(f"{FL}●{NOFL} HARDWARE DISCONNECTED: KEYBOARD ONLY", R)
                    update_header_only() # Instantly reflect the ERR in the stats bar
        
        time.sleep(0.5)

def shutdown_sequence(tts):
    if state.is_shutdown.is_set(): return True
    state.is_shutdown.set()
    
    if state.scroll_offset > 0: resume_live_view()
    
    cols, rows = shutil.get_terminal_size()
    
    # Send the Critical Override text directly to the Status Line (Row-2)
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
            # Disable ISIG here so CTRL+C works if mashed at the prompt
            attrs = termios.tcgetattr(fd)
            attrs[3] = attrs[3] & ~termios.ISIG
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
            
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
                                    r_name = YOUR_NAME if role == 'user' else ORAC_NAME
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

    # If the user pressed 'C', restore the UI and exit this function safely
    if cancel_shutdown:
        state.is_shutdown.clear()
        set_status("● SHUTDOWN ABORTED", A)
        render_input_box()
        time.sleep(0.1)
        return False

    # Otherwise, proceed with normal shutdown...
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
    cleanup_processes()
    hard_shutdown() 


def startup_animation():
    setup_terminal() 
    
    with state.terminal_lock:
        sys.stdout.write("\033[2J") 
        sys.stdout.write("\033[?25l") 
        sys.stdout.flush()
        
    draw_ui()
    
    with state.terminal_lock:
        sys.stdout.write("\033[5;1H")
        sys.stdout.flush()
    
    logic_text = "LOGIC ARRAYS BOOTING..."

    for char_idx in range(len(logic_text)):
        with state.terminal_lock:
            sys.stdout.write(f"\r\033[2K● {R}{logic_text[:char_idx+1]}{RESET}")
            sys.stdout.flush()
        time.sleep(0.02)
        
    with state.terminal_lock:
        sys.stdout.write("\n\n")
        sys.stdout.flush()

def stream_ai_response(prompt, tts, teletype):
    state.history.append({'role': 'user', 'content': prompt})
    
    # TOKEN-AWARE SLIDING HISTORY
    update_token_health()
    # If exceeding 85%, drop the oldest message PAIR (User + Assistant) to maintain alternation
    while state.current_tokens > (MODEL_MAX_TOKENS * 0.85) and len(state.history) >= 2:
        state.history = state.history[2:]
        # Ensure history always starts with a user message to maintain alternation
        if state.history and state.history[0]['role'] == 'assistant':
            state.history = state.history[1:]
            
        update_token_health()  # Recalculate tokens to allow the loop to exit
        
    update_header_only() # Only update the header bounds, do not clear the screen 
        
    messages_to_send = [{'role': 'system', 'content': SYSTEM_INSTRUCTION}]
    temp_history = list(state.history)
    
    reminder_text = (
        f"\n\n[SYSTEM REMINDER: You are {ORAC_NAME}. ALWAYS use first-person pronouns ('I', 'Me', 'My'). "
        f"The user is {YOUR_NAME}. Be concise, arrogant, sardonic and pedantic. "
        f"ALWAYS refer to {YOUR_NAME} using second-person pronouns ('You', 'Your'). Address {YOUR_NAME} by using their first name. "
        f"NEVER begin a sentence with {YOUR_NAME}. "
        f"Output spoken dialogue ONLY. NO MARKDOWN FORMATTING. Strictly adhere to CHRONOLOGICAL HISTORY. Do not invent facts. "
        f"Strictly adhere to [LOGIC_GATE]. "
    )

    if temp_history and temp_history[-1]['role'] == 'user':
        # Create a copy of the dictionary so we don't permanently corrupt state.history
        modified_msg = temp_history[-1].copy()
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
    
    #-----------------------#
    # OLLAMA MODEL SETTINGS #
    #-----------------------#  
    
    for chunk in chat(
        model=OLLAMA_MODEL,
        messages=messages_to_send, 
        stream=True, 
        keep_alive='3h',
        options={
            'num_ctx': MODEL_MAX_TOKENS, 
            'temperature': 0.20,  	# 20% variance to avoid looping.
            'top_k': 10,          	# STRICT GUARDRAIL: Only pick from the 10 most logical next words.
            'top_p': 0.5,			# Cuts off the "creative" long-tail probabilities.
            'repeat_penalty': 1.15,
            'num_predict': 500,
            'stop': ["<end_of_turn>", "<eos>"]
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

    was_interrupted = state.is_interrupted.is_set()

    if not was_interrupted:
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
        # Interruption Completed
        with teletype.q.mutex: teletype.q.queue.clear()
        teletype.is_typing.clear()
        
        # Save whatever ORAC managed to say before being cut off
        partial_text = "".join(response_chunks).strip() + " ... [INTERRUPTED]"
        if partial_text.strip() != "... [INTERRUPTED]":
            state.history.append({'role': 'assistant', 'content': partial_text})
            state.full_message_log.append(('assistant', partial_text))

    state.is_processing.clear()
    state.is_interrupted.clear()
    
    if getattr(state, 'mic_error', False) and not was_interrupted:
        set_status(f"{FL}●{NOFL} HARDWARE DISCONNECTED: KEYBOARD ONLY", R)
    
def is_hallucination(text):
    if len(text) < 30 and HALLUCINATION_REGEX.search(text.lower()): return True
    return False

def run_local_bot():
    tts = MacTTS()
    teletype = TeletypeUI()

    threading.Thread(target=speak_now, args=(tts, teletype), daemon=True).start()
    threading.Thread(target=keyboard_listener, args=(tts, teletype), daemon=True).start()
    threading.Thread(target=ui_refresh_worker, daemon=True).start() 
    
    startup_animation()
    
    try:
        # Fresh recognizer every time hardware connects to prevent ghosties
        recognizer = sr.Recognizer()
        recognizer.dynamic_energy_threshold = False 
        recognizer.pause_threshold = 0.8 
        recognizer.non_speaking_duration = 0.3 
        recognizer.phrase_threshold = 0.5 
        
        # Reset the prompt beep flag so it chimes when the mic reconnects..
        needs_prompt = True
        
        with sr.Microphone(sample_rate=16000) as source: 
            state.mic_error = False
            
            with state.terminal_lock: 
                sys.stdout.write(f"● {R}CALIBRATING AMBIENT NOISE...{RESET}\n")
                sys.stdout.flush()
                
            recognizer.adjust_for_ambient_noise(source, duration=1)
            recognizer.energy_threshold += 75 
            state.noise_floor = recognizer.energy_threshold
            update_header_only() # Instantly show the new noise floor in the stats bar
            
            with state.terminal_lock:
                # Initial text stays on screen and will naturally scroll off
                sys.stdout.write(f"● {R}NOISE FLOOR CALIBRATED: {state.noise_floor:.2f}{RESET}\n\n")
                sys.stdout.flush()
            
            while state.running:
                bot_busy = state.is_speaking.is_set() or state.is_processing.is_set() or teletype.is_typing.is_set() or not tts.queue.empty()
                
                if not bot_busy and processing_sound.is_running(): processing_sound.stop()
                
                if bot_busy:
                    needs_prompt = True 
                    time.sleep(0.1) 
                    continue
                
                if needs_prompt:
                    set_status("● Adapting to ambient noise...", DIM)
                    recognizer.adjust_for_ambient_noise(source, duration=0.3)
                    recognizer.energy_threshold += 75 
                    state.noise_floor = recognizer.energy_threshold
                    update_header_only() # Instantly update the stats bar reading
                    
                    play_once(SOUND_READY)
                    needs_prompt = False
                
                state.is_listening.set()
                
                try:
                    audio = recognizer.listen(source, phrase_time_limit=10, timeout=0.2)
                    state.is_listening.clear()
                    
                    set_status("● SIGNAL RECEIVED: DECODING...", A)
                    
                    audio_raw = audio.get_raw_data()
                    audio_float32 = np.frombuffer(audio_raw, dtype=np.int16).astype(np.float32) / 32768.0
                    
                    result = mlx_whisper.transcribe(
                        audio_float32, path_or_hf_repo=WHISPER_MODEL, fp16=True, language='en'
                    )
                    
                    user_text = result['text'].strip()
                    
                    del audio_raw
                    del audio_float32
                    del result
                    gc.collect() 
                    
                    if len(user_text) < 2 or is_hallucination(user_text): continue

                    clean_text = user_text.lower().strip("'.,! ")
                    if any(cmd in clean_text for cmd in SHUTDOWN_CMD):
                        if not shutdown_sequence(tts): 
                            continue 
                        break
                    
                    if any(cmd in clean_text for cmd in PURGE_CMD):
                        state.history.clear()
                        state.full_message_log.clear()
                        if state.scroll_offset > 0: resume_live_view()
                        with state.terminal_lock:
                            sys.stdout.write(f"\n●{R} LOGIC ARRAYS RESET{RESET}\n\n")
                            sys.stdout.flush()
                        set_status("● MEMORY PURGED", R)
                        tts.say("Very well.  State your enquiry.")
                        continue

                    if user_text:
                        state.full_message_log.append(('user', user_text))
                        if len(state.full_message_log) > 2000: state.full_message_log.pop(0)
                        if state.scroll_offset > 0: resume_live_view()
                        
                        with state.terminal_lock:
                            sys.stdout.write(f"\r\033[2K{B}{IT}{YOUR_NAME}{NOIT} ▶ {user_text}{RESET}\n\n")
                            sys.stdout.flush()
                            
                        state.is_interrupted.clear()
                        state.is_listening.clear() 
                        state.is_processing.set() 
                        threading.Thread(target=stream_ai_response, args=(user_text, tts, teletype), daemon=True).start()

                except sr.WaitTimeoutError: 
                    continue
                except Exception as e:
                    # Mic was unplugged during the listen process
                    state.is_listening.clear()
                    state.mic_error = True
                    set_status(f"{FL}●{NOFL} HARDWARE DISCONNECTED: KEYBOARD ONLY", R)
                    update_header_only()
                    break 
                    
    except KeyboardInterrupt: 
        shutdown_sequence(tts)
        
    except Exception as e:
        # Tried to connect and mic wasn't there
        state.is_listening.clear()
        state.mic_error = True
        set_status(f"{FL}●{NOFL} HARDWARE DISCONNECTED: KEYBOARD ONLY", R)
        update_header_only()
        
    # The permanent Keyboard-Only Fallback Loop
    while state.running:
        time.sleep(1)

if __name__ == "__main__":
    run_local_bot()