# ORAC: 'In-Universe' AI Voice & Terminal Chat

![ORAC Terminal Interface](resources/misc/orac-voice.png?text=ORAC+Terminal+UI)

**ORAC-Voice** is a fully autonomous, lore-accurate, voice-interactive AI, based on ORAC from the classic British Sci-Fi series *Blake's 7*.

I have always loved this show and have fond memories of watching it with my dad, when I was a kid. Jenna was always my favorite, with Avon taking second place. I always wanted my own ORAC, and this project is the first step in creating the brains, which hopefully, I will then put into a perspex chassis..

This project transforms a base model, **Apple M4 Mac Mini** into *'the'* standalone, sentient super-computer. It listens continuously, processes speech locally using hardware acceleration, and responds strictly in the sardonic, impatient persona of ORAC, complete with an authentic sounding voice. (Subject to a little extra work and version of MacOS).

## Features

* **Authentic ORAC Voice:** Using a "Custom" Apple Personal Voice. *(Covered in Installation Steps 5 and 6, below.)*
* **Lore-Accurate Persona:** 8K of Personality and Lore, covering important plot points from Season 1 of Blake's 7.
**ORAC** is "in-universe" and will interpret the lore using second-person pronouns based on the character you choose. *(Example, `Q:` 'How did we acquire the Liberator?' `A:` 'Following the failed mutiny aboard The London, You, Blake and Avon boarded the DSV-1....)*
* **Local Processing (No Cloud):** Runs entirely locally on Apple Silicon for maximum privacy and low latency.
* **Continuous Ambient Listening:** Uses dynamic 'noise-floor' calibration to listen for voice commands without requiring a push-to-talk button.
* **Barge-in Support:** You can interrupt ORAC mid-sentence *(via keyboard only by choice)*, and he will immediately halt his response and react.
* **Operating Sounds:** ORAC remains silent until you speak, which initiates the familiar 'key insertion' sound, a continuous 'hum/whirring' sound and finally when ORAC stops speak, the 'key removal' sound.
* **Teletype UI:** Custom ANSI terminal interface featuring live token tracking, memory monitoring, dynamic status lines, and scrolling history. (Independent control of teletype and voice speed.)
* **Custom Phonetics Engine:** A dedicated regex pipeline ensures ORAC pronounces the terminology (e.g., *Servalan, Mutoids, DSV-2*) with an appropriate RP accent.

## Tech Stack & Hardware

This project is specifically designed to run on a dedicated **Mac Mini M4 (16GB Unified Memory)**. 

* **LLM Backend:** [Ollama](https://ollama.ai/) running the `gemma2:9b-simpo` model, providing excellent reasoning and adherence to system prompts. *(Gemma3:4b seemed to hallucinate too much and other models are just too helpful!)*
* **Speech-to-Text (STT):** [MLX-Whisper](https://github.com/ml-explore/mlx-examples/tree/main/whisper) (`whisper-large-v3-turbo`) optimized natively for Apple Silicon GPUs, paired with Python's `SpeechRecognition` library.
* **Text-to-Speech (TTS):** macOS native `NSSpeechSynthesizer` via `PyObjC`, utilizing an Apple Personal Voice clone. *(Or SIRI voices if you don't wish to go through the Apple Personal Voice process.)*
* **Audio Processing:** Native MacOS `afplay` for non-blocking UI sound effects. *(Key and hum/whirring sounds.)*

## Project Structure

* `orac_chat.py`: The main asynchronous loop handling audio listening, the ANSI UI engine, subprocess sound loops, and Ollama inferencing.
* `orac_data_core.py`: The chronological history, lore parameters, and operational rules governing ORAC's knowledge base.
* `orac_personality.py`: Strict system prompts governing ORAC's arrogant tone, refusal to use filler words, and sardonic sign-offs.
* `orac_phonetics.py`: Regex dictionary that manipulates text strings before they hit the TTS engine to ensure proper sci-fi nomenclature and British intonations *(e.g., Trap-Bath split: *asking* -> *arsking*).*


## Installation & Setup

Due to strict audio and accessibility sandboxing in recent macOS updates, this project relies on **pyenv** to manage a specific Python version, *(3.12 Recommended)*, to ensure microphone and `AppKit` permissions function correctly.

**1. Install System Dependencies:**
You will need Homebrew installed to grab `portaudio`(required for PyAudio/microphone access) & `pyenv`. *(To use version 3.12 of Python in your venv).*

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
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
ollama pull gemma2:9b-simco
```
**3. Git Clone Project and enter Project Directory:**
```bash
git clone https://github.com/CarolinaJones/Orac-Voice.git
cd Orac-Voice 
```
**IMPORTANT: Stay in this directory for entire installation.**

```bash
# Create & Activate oral-venv
python3 -m venv orac-venv
source orac-venv/bin/activate

# Download python 3.12 using Pyenv and activate it locally:
pyenv install 3.12
pyenv local 3.12
```
**Ensure you are using pyenv to install and set Python 3.12. Do not use the default macOS system Python.**

**4. Install Required Python Libraries:**
```bash
pip install sounddevice==0.4.3 mlx-whisper hf_transfer SpeechRecognition PyAudio ollama numpy python-vlc pip-review PyObjC psutil
```
`sounddevice` `and python-vlc` are not strictly required at this time.
```bash
curl -LsSf https://hf.co/cli/install.sh | bash
hf download mlx-community/whisper-large-v3-turbo --local-dir ./whisper/whisper-large-v3-turbo
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

**6. Using Voicebox to train Apple Personal Voice:**

Download latest **Apple ARM** release of `Voicebox` from:
```bash
https://voicebox.sh/#download
```
- Import the ORAC voice profile that I have included, in extras.
- In MacOS Settings, Accessibily, select `Personal Voice` to create a personal voice.
- You will be prompted to say ten phrase; Typically the first is, **"I am creating a personal voice on my Mac."**
- Generate the phrase in Voicebox with the ORAC voice profile, until you're happy with the result and play it back to `Apple Personal Voice`, create wizard.
- Repeat for subsequent phrases. *(It might take a few goes!)*
- Set your Mac's `System Voice` to your personal voice and make sure in the 'orac_chat.py', `VOICE = ""`.

**7. ...and now to configure some variables & test:**

Ensuring you're in the directory, 'Orac-Voice',
open 'orac_chat.py' in an editor, such as BBEdit and change these variables **(ONLY)** to suit.

`VOICE = ""` 	# Leave blank to use the "System Voice" - This allows for SIRI/Personal Voices.
`voice_pitch = 80.0` 	# Only works on SYNTH voices and not SIRI/Personal voices.

`U1 = 0.06`  (Teletype Speed)
`U2 = 0.071` (Teletype Uniformity)

`TRANSCRIPT_DIR = /Users/Caroline/Desktop/` (A Directory called transcripts will be created.)
TR = "ORAC_Transcript_CM" # Transcript Name Prefix (Date will be added).

`YOUR_NAME = "Jenna"` # USER Name and Identity

`ORAC_NAME = "ORAC"` 	# ORAC's Name

TERMINAL SETTINGS:

`TERMINAL_PROFILE` = "Homebrew" # Terminal Profile

`TERMINAL_FONT` = "AdwaitaMono Nerd Font Mono" # Font Name (This font is in extras)

`TERMINAL_FONT_SIZE` = 17 # Font Size

`TERMINAL_COLS = 100` # Window Width

`TERMINAL_ROWS = 35` # Window Height

**..and then (From Orac-Voice Folder):**
```bash
source orac-venv/bin/activate
python3 orac_voice.py
```    
- Boot Sequence: The Terminal will resize, display a booting animation, and calibrate to your room's ambient noise floor. *(Updates dynamically throughout conversation.)*

- Interacting: Address ORAC naturally. The system is voice-activated but ignores background noise. Press ESC to interrupt. *(Give him 9-10 seconds after start-up to load the model to RAM. Once loaded you should hear a response within 1-2 seconds. The model stays loaded in memory for 3 hours.)*

- Keyboard Entry: You can manually type text into the bottom UI bar. *(Typing and entering text while ORAC is talking, will "barge-in".)* While ORAC is not actively talking, you can use arrow keys or mouse scroll to review your session. Use `FN` key + `CMD+ C & V` as usual, for copy and paste.

- Purge Memory: Say or type  "Clear memory" and your available tokens will refresh. Keep in mind, the relative low context window of this model - I have set a "sliding" option, when around 85% of your tokens are used.. By default hisrory is set to twelve, this will remove two from the top to allow continuous conversation.

- Header Status: The Header is colour-coded in a traffice light scheme, with status, to let you know how many tokens you've used.. Below is a TKNS: xxxx/8192 and RAM: xx% (Tokens available out of 8192 and RAM useage of your Mac.)

- Shut Down: Say "shut down" or press `Ctrl+C`. ORAC will prompt you to save a transcript of the conversation before powering off, or to cancel and return to your conversation.

## Acknowledgements

- The estate of Terry Nation and the BBC for the enduring legacy of Blake's 7.
- Peter Tuddenham, for providing the unforgettable original voice of ORAC.

I hope you enjoy! Caroline xo
