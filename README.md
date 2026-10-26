# Voice assistant

A voice assistant for Ubuntu that controls Spotify and sends Snapchat messages.
Wake word detection ([openWakeWord](https://github.com/dscripka/openWakeWord)) and speech recognition
([faster-whisper](https://github.com/SYSTRAN/faster-whisper)) both run on your computer, so your voice never leaves it.

You can start it two ways:

- **Say "Hey Jarvis"**, then your command.
- **Press Super+Alt+V**. On the Cradio, hold the right thumb key (Backspace / layer 1) and tap the **T** key.

## Things you can say

| Spotify | Snapchat |
|---|---|
| "Play Shape of You by Ed Sheeran" | "Send a message to Sam saying I'm on my way" |
| "Play my gym playlist" / "Play the playlist chill vibes" | "Send Jake a snap saying see you at 5" |
| "Play the album Abbey Road" / "Play some music by Taylor Swift" | "Message mum saying I'll be late" |
| "Pause" / "Resume" / "Skip" / "Go back" | "Tell Jake I'm outside" |
| "Add this song to my gym playlist" | |
| "Add Bohemian Rhapsody to road trip" | |
| "Like this song" | |
| "Set the volume to 50" / "Turn it up" / "Turn it down" | |
| "Shuffle on" / "Shuffle off" | |
| "What's this song?" | |

To check how a sentence will be understood without doing anything: `uv run voice-assistant parse "play my gym playlist"`

## Setup

You need [uv](https://docs.astral.sh/uv/), the Spotify desktop app and Google Chrome (all already installed on this machine).

1. **Install and create your config**
   ```bash
   uv sync
   cp config.example.toml config.toml
   ```

2. **Spotify.** Go to <https://developer.spotify.com/dashboard>, create an app, tick "Web API",
   and add the Redirect URI `http://127.0.0.1:8888/callback`. Put the Client ID and Client Secret
   into `config.toml`, then log in once:
   ```bash
   uv run voice-assistant spotify-login
   ```
   Pause, resume, skip and playing a particular song work on a free account. Changing Spotify's volume and
   shuffle through the Web API needs Premium. Without Premium, volume commands change your system volume instead.

3. **Snapchat.** Log in once in the browser window this opens, then close the window:
   ```bash
   uv run voice-assistant snapchat-login
   ```
   Add nicknames to `[snapchat.contacts]` in `config.toml` if the name you say doesn't match the name in your chat list.

4. **Test your mic:**
   ```bash
   uv run voice-assistant test-mic
   ```

5. **Install the shortcut and start it on login:**
   ```bash
   ./scripts/install.sh            # uses Super+Alt+V
   ./scripts/install.sh "<Super>j" # or pick your own shortcut
   ```
   To watch what it's doing: `journalctl --user -u voice-assistant -f`

   To run it in a terminal instead: `uv run voice-assistant run`

6. **Flash the keyboard.** The Cradio keymap in `../zmk-config-cradio` has an assistant key on layer 1 (the T position)
   that sends Super+Alt+V. Push that repo so GitHub Actions builds the firmware, then flash both halves as usual.

You can also type commands to the running assistant, which is handy for testing: `uv run voice-assistant do "skip"`

## Notes

- **Snapchat** has no public API, so the assistant controls Snapchat for Web in a Chrome window. If Snapchat changes
  its website, sending may break. The selectors to fix are at the top of `src/voice_assistant/snapchat.py`.
  Automating Snapchat Web may go against Snapchat's terms of service. Before sending, the assistant reads the message back
  and waits for you to say "yes". You can turn that off with `confirm = false`.
- **Wake word:** the built-in options are `hey_jarvis`, `alexa`, `hey_mycroft` and `hey_rhasspy`. To use your own word, train a
  model with openWakeWord's [training notebook](https://github.com/dscripka/openWakeWord#training-new-models) and set
  `model = "/path/to/model.onnx"`.
- **Speed:** `small.en` on the CPU should take a second or two per command. `base.en` is faster but less accurate.
  `device = "cuda"` uses your GPU if the CUDA 12 and cuDNN 9 libraries are installed.
