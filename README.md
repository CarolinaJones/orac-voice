# ORAC: 'In-Universe' AI Voice & Terminal Chat V2


https://github.com/user-attachments/assets/4facb2c3-2e08-482a-b78a-a84be58301b2



**ORAC-Voice** is a fully autonomous, lore-accurate, voice-interactive AI, based on ORAC from the classic British Sci-Fi series *Blake's 7*.

I have always loved this show and have fond memories of watching it with my dad, when I was a kid. Jenna was always my favorite, with Avon taking second place. I always wanted my own ORAC, and this project is the first step in creating the brains, which hopefully, I will then put into a perspex chassis..

This project transforms a base model, **Apple M4 Mac Mini** into *'the'* standalone, sentient super-computer. It listens continuously, processes speech locally using hardware acceleration, and responds strictly in the sardonic, impatient persona of ORAC, complete with an authentic sounding voice. (Subject to a little extra work and version of MacOS).

## Features

* **Authentic ORAC Voice:** Using a "Custom" Apple Personal Voice, spoken through `AVSpeechSynthesizer` and tuned with SSML *(rate, pitch, volume and emphasis)*. *(Covered in Installation Steps 5 and 7, below.)*
* **Lore-Accurate Persona:** 8K of Personality and Lore, covering important plot points from Season 1 of Blake's 7.
**ORAC** is "in-universe" and will interpret the lore using second-person pronouns based on the character you choose. *(Example, `Q:` 'How did we acquire the Liberator?' `A:` 'Following the failed mutiny aboard The London, You, Blake and Avon boarded the DSV-1....)*
* **Local Processing (No Cloud):** Runs entirely locally on Apple Silicon for maximum privacy and low latency.
* **Continuous Ambient Listening:** Uses dynamic 'noise-floor' calibration to listen for voice commands without requiring a push-to-talk button.
* **Barge-in Support:** You can interrupt ORAC mid-sentence *(via keyboard only by choice)*, and he will immediately halt his response and react.
* **Operating Sounds:** ORAC remains silent until you speak, which initiates the familiar 'key insertion' sound, a continuous 'hum/whirring' sound and finally when ORAC stops speak, the 'key removal' sound.
* **Teletype UI:** Custom ANSI terminal interface featuring live token tracking, memory monitoring, dynamic status lines, and scrolling history. (Independent control of teletype and voice speed.)
* **Custom Phonetics Engine:** A dedicated regex pipeline ensures ORAC pronounces the terminology (e.g., *Servalan, Mutoids, DSV-2*) with an appropriate RP accent.
* **Debug Mode:** OPT+D outputs to screen the Speech To Text (STT) and Time to First Token (TTFT) times. (Typically ~1 sec STT and between 0.7 - 2 second TTFT.
* **Mute Mic:** OPT+M allows toggling microphohe muting. (With visible indication.)
* **Text Mode:** OPT+T allows to scroll back and copy text to clipboard. (With visible indication.)

## Tech Stack & Hardware

This project is specifically designed to run on a dedicated **Mac Mini M4 (16GB Unified Memory)**. 

* **LLM Backend:** [Ollama](https://ollama.ai/) running the `gemma4:12b` model *(or `gemma4:12b-mlx`, chosen with `OLLAMA_MODEL`)*, providing excellent reasoning and adherence to system prompts. *(V2 WIP code has been revised to work optimally with gemma4 LLM)*
* **Speech-to-Text (STT):** [MLX-Whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) (`whisper-turbo-q4`) optimized natively for Apple Silicon GPUs, paired with Python's `SpeechRecognition` library.
* **Text-to-Speech (TTS):** macOS native `AVSpeechSynthesizer` (AVFoundation), speaking an Apple Personal Voice clone chosen by name. Each sentence is wrapped in SSML, so ORAC's rate, pitch, volume and emphasis can be tuned in `orac_chat.py`. *(If you'd rather not create a Personal Voice, set `USE_PERSONAL_VOICE = False`: ORAC then speaks through `NSSpeechSynthesizer` with a standard voice named in `VOICE`, or your System Voice, e.g. a SIRI voice, if `VOICE` is empty.)*
* **Audio Processing:** Native MacOS `NSSound` for non-blocking UI sound effects. *(Key and hum/whirring sounds.)*

## Project Structure

* `orac_chat.py`: The main asynchronous loop handling audio listening, the ANSI UI engine, subprocess sound loops, and Ollama inferencing.
* `orac_data_core.py`: The chronological history, lore parameters, and operational rules governing ORAC's knowledge base.
* `orac_personality.py`: Strict system prompts governing ORAC's arrogant tone, refusal to use filler words, and sardonic sign-offs.
* `orac_phonetics.py`: Regex dictionary that manipulates text strings before they hit the TTS engine to ensure proper sci-fi nomenclature and British intonations *(e.g., Trap-Bath split: *asking* -> *arsking*).*
* `orac_trigger_phrases.py`: The phrases that steer ORAC's replies: "Very Well" requests, menial tasks, memory recall, filler words and his topics of interest.
* `extras/tts_probe.py`: A voice diagnostic. It times the speech synthesizer *(cold and warm, spoken live and rendered, with or without the model running)* and saves the results to a text file. *(Instructions at the top of the file.)*
* `ORAC-VOICE_User_Manual.md`: Every voice command, keyboard shortcut and mode, in one place.
* `CHANGELOG.md`: What changed in each version.


## Installation & Setup

Due to strict audio and accessibility sandboxing in recent macOS updates, this project relies on **pyenv** to manage a specific Python version, *(3.12 Recommended)*, to ensure microphone and `AppKit` permissions function correctly.

**1. Install System Dependencies:**
You will need Homebrew installed to grab `portaudio`(required for PyAudio/microphone access) & `pyenv`. *(To use version 3.12 of Python in your venv).*

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
# (Follow the instructions after install, to add Homebrew to your path.)

brew install portaudio pyenv
```
Instructions for setting up `pyenv` can be found here:
```bash
https://github.com/pyenv/pyenv?tab=readme-ov-file
```
*(Follow the installation very carefully!)*

**2. Install Ollama and the model:**
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull gemma4:12b
```
*(`orac_chat.py` uses `gemma4:12b` by default. To try the MLX version, `ollama pull gemma4:12b-mlx` and change `OLLAMA_MODEL`.)*
**3. Git Clone Project and enter Project Directory:**
```bash
git clone https://github.com/CarolinaJones/orac-voice.git
cd orac-voice 
```
**IMPORTANT: Stay in this directory for entire installation.**

```bash
# Download python 3.12 using Pyenv and set it active locally:
pyenv install 3.12
pyenv local 3.12

# Create & Activate oral-venv
python3 -m venv orac-venv
source orac-venv/bin/activate
```
**Ensure you are using pyenv to install and set Python 3.12. Do not use the default macOS system Python.**

**4. Install Required Python Libraries:**
```bash
pip install mlx-whisper hf_transfer SpeechRecognition PyAudio ollama numpy PyObjC psutil tokenizers requests
```
... next
```bash
curl -LsSf https://hf.co/cli/install.sh | bash
hf download mlx-community/whisper-large-v3-turbo-q4 --local-dir ./whisper/whisper-turbo-q4
```

**5. 'Hack' to allow Terminal to use Apple Personal Voice:**

To authenicate Personal Voice in Terminal, paste this code in to your Terminal shell and press `Return`.
```bash
echo '#import <AVFoundation/AVFoundation.h>
int main(){ 
[AVSpeechSynthesizer requestPersonalVoiceAuthorizationWithCompletionHandler:^(AVSpeechSynthesisPersonalVoiceAuthorizationStatus status){ 
printf("Status: %ld\\n", (long)status); }]; 
[[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:2.0]]; 
return 0; }' > auth_check.m && gcc -framework AVFoundation -framework Foundation auth_check.m -o auth_check && ./auth_check
```
You'll get an `authorization` pop-up to agree to, and in MacOS settings, *(under Personal Voice)*, you should now see that Terminal is authorized to use it.

**6. OPTIONAL: Shutdown MAC with voice command**

I have added the option to say or type, "Activate System Shutdown" *(or "Activate System Reboot")*, specifically for my battery powered/headless, ORAC.

**"CAUTION: In order for this to work, root priveledges for shutdown will need to be set."**

If you choose to continue, from Terminal type:
```
sudo visudo -f /etc/sudoers.d/orac_shutdown
````
Add this line (replace your_username with your Mac user account name):
```
your_username ALL=(ALL) NOPASSWD: /sbin/shutdown
````
Save and exit (:wq in vim). Test it in Terminal by running sudo -n /sbin/shutdown -k now (the -k sends a mock warning without actually shutting down; if it asks for no password, it works).

**7. Using Voicebox to train Apple Personal Voice:**

Download latest **Apple ARM** release of `Voicebox` from:
```bash
https://voicebox.sh/#download
```
- Import the ORAC voice profile that I have included, in extras.
- In MacOS Settings, Accessibily, select `Personal Voice` to create a personal voice.
- You will be prompted to say ten phrase; Typically the first is, **"I am creating a personal voice on my Mac."**
- Generate the phrase in Voicebox with the ORAC voice profile, until you're happy with the result and play it back to `Apple Personal Voice`, create wizard.
- Repeat for subsequent phrases. *(It might take a few goes!)*
- In 'orac_chat.py', set `VOICE` to your Personal Voice's name, as shown in MacOS Settings, Accessibility, Personal Voice *(e.g. `VOICE = "ORAC Personal Voice"`)*. There's no need to change your Mac's `System Voice`.
- If you have more than one Personal Voice, use the full name. `python3 extras/tts_probe.py --list-voices` lists the exact names.

**8. ...and now to configure some variables & test:**

Ensuring you're in the directory, 'orac-voice',
open 'orac_chat.py' in an editor, such as BBEdit and change these variables **(ONLY)** to suit. *(They're all at the top of the file, under `U S E R  S E T T I N G S`.)*

`USE_PERSONAL_VOICE = True` 	# Speak with your Apple Personal Voice.

`VOICE = "ORAC Personal Voice"` 	# Your Personal Voice's name. *(Or a standard voice's name, if `USE_PERSONAL_VOICE = False`.)*

`SSML_RATE = 114`, `SSML_PITCH = "x-high"`, `SSML_VOLUME = "loud"`, `SSML_EMPHASIS = "strong"` 	# Tune ORAC's delivery. *(The options are listed beside each one.)*

`voice_pitch = 72`, `S_RATE = 188` 	# Only used with a standard voice (`USE_PERSONAL_VOICE = False`).

`USE_LCD = False`, `USE_ACTIVATOR = False` 	# Unless you've built the Raspberry Pi Pico LCD and activator key. *(With `USE_ACTIVATOR = True` and no Pico connected, ORAC starts up locked.)*

`U1 = 0.038`  (Teletype Speed)
`U2 = 0.052` (Teletype Uniformity)

`TRANSCRIPT_DIR = /Users/Caroline/Desktop/` (A Directory called transcripts will be created.)
TR = "ORAC_Transcript_CM" # Transcript Name Prefix (Date will be added).

`USER_NAME = "Jenna"` # USER Name and Identity

`ORAC_NAME = "ORAC"` 	# ORAC's Name

TERMINAL SETTINGS:

`TERMINAL_PROFILE` = "Homebrew" # Terminal Profile

`TERMINAL_FONT` = "AdwaitaMono Nerd Font Mono" # Font Name (This font is in extras)

`TERMINAL_FONT_SIZE` = 17 # Font Size

`TERMINAL_COLS = 100` # Window Width

`TERMINAL_ROWS = 35` # Window Height

**..and then (From orac-voice Folder):**
```bash
source orac-venv/bin/activate
python3 orac_chat.py
```    
- Boot Sequence: The Terminal will resize, display a booting animation, and calibrate to your room's ambient noise floor. *(Updates dynamically throughout conversation.)*

- Interacting: Address ORAC naturally. The system is voice-activated but ignores background noise. Press ESC to interrupt. *(The model loads into RAM in the background while ORAC boots; the status line shows "LOADING LANGUAGE MODEL" until it's ready. Once loaded you should hear a response within 1-2 seconds. The model stays loaded in memory for 4 hours while ORAC runs, and is freed when ORAC closes; set `UNLOAD_ON_EXIT = False` to keep it loaded, so a restart is quick.)*

- Keyboard Entry: You can manually type text into the bottom UI bar. *(Typing and entering text while ORAC is talking, will "barge-in".)* While ORAC is not actively talking, you can use arrow keys or mouse scroll to review your session. Use `FN` key + `CMD+ C & V` as usual, for copy and paste.

- Purge Memory: Say or type "Clear memory" *(or "Clear history" / "New subject")* and your available tokens will refresh. Keep in mind, the relative low context window of this model - I have set a "sliding" option: when around 90% of your tokens are used, ORAC summarises the oldest part of the conversation *(down to about 65%)*, to allow continuous conversation.

- Header Status: The Header is colour-coded in a traffic light scheme, with status, to let you know how many tokens you've used.. Below is a TKNS: xxxx/16384 and MEM: xx% (Tokens used out of 16384 and memory usage of your Mac.)

- Shut Down: Say "exit interface" or press `Ctrl+C` *(Ctrl+C works even with the activator key removed)*. ORAC will prompt you to save a transcript of the conversation before powering off, or to cancel and return to your conversation. *(In `HEADLESS_MODE` the transcript is saved automatically.)*

- Everything else: every voice command, keyboard shortcut and mode is in the [User Manual](ORAC-VOICE_User_Manual.md).

## Acknowledgements

- The estate of Terry Nation and the BBC for the enduring legacy of Blake's 7.
- Peter Tuddenham, for providing the unforgettable original voice of ORAC.

I hope you enjoy! Caroline xo
