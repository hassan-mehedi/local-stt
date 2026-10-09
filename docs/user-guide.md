# local-stt user guide

local-stt turns your voice into text on your Mac. Hold a key, talk, let go, and the words appear in whatever app you are typing in. Speech recognition runs on your Mac, so your audio never leaves it.

This guide is for the Mac app. For Linux, or the `stt` command line, see the [README](../README.md).

## What you need

- A Mac with Apple Silicon (M1 or later) on macOS 14.2 or later
- About 3 GB of free space for the app and the speech model

## Install

There is no download yet, so you build the app once from the source code.

1. Install the tools:
   ```bash
   xcode-select --install
   curl -LsSf https://astral.sh/uv/install.sh | sh
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
   brew install pnpm
   ```
2. Make a signing certificate. Without it, macOS will not let the app type for you. Open Keychain Access, then Keychain Access > Certificate Assistant > Create a Certificate. Name it `local-stt Dev`, set Identity Type to Self Signed Root and Certificate Type to Code Signing, then click Create.
3. Build it:
   ```bash
   git clone https://github.com/hassan-mehedi/local-stt.git
   cd local-stt
   ./packaging/macos/build.sh
   ```
4. Open `dist/local-stt-0.2.0.dmg` and drag local-stt into Applications.

## First launch

A setup window walks you through four steps:

1. Download the speech model (about 2.5 GB, once).
2. Allow the microphone.
3. Allow Input Monitoring, so the app sees your shortcut, and Accessibility, so it can type into other apps. macOS applies these two only after a restart, so click Restart local-stt once both are on. Setup continues where you left it.
4. Try a dictation in the test box.

If you skip the keyboard step, Settings > Permissions shows what is missing, with a button that opens the right page in System Settings.

## Dictate

The default shortcut is Option+Shift+T. Press it once to start, talk, and press it again to stop. The text appears where your cursor is.

While you talk, a small pill at the bottom of the screen shows your voice level. Press Esc or click the X on the pill to throw the recording away.

You can change how the shortcut works in Settings > Dictation:

- **Shortcut**: click the keys and press a new combination. One modifier on its own works too, such as Right Option.
- **How the shortcut works**: press to start and press to stop, or hold while you talk, like a walkie-talkie.
- **Put the text in**: type it key by key, which leaves your clipboard alone, or paste it, which is faster for long text.

## Clean up what you said

Spoken text is messy: "um so can you send me the the uh report". Cleanup sends the text (never the audio) to an AI model, which returns "Can you send me the report?". It removes filler words and false starts, fixes punctuation, and writes a numbered list when you dictate one.

Cleanup needs an API key from a provider. DeepSeek is cheap and fast.

1. Get an API key from the provider's website.
2. Open Settings > Cleanup and click the provider's name, for example DeepSeek. That fills in the URL and model.
3. Paste the key and click Save. Cleanup turns on.
4. Click Test. You should see the cleaned test sentence.

The key is stored in your macOS Keychain. Each provider keeps its own key, so you can switch back and forth. Ollama runs on your own Mac and needs no key.

If the provider fails or is slow, local-stt types your words without cleanup and tells you why. History always keeps what you actually said.

## History, dictionary and insights

- **Home** lists every dictation with its recording. Search it, play a recording, copy the text, or paste it again.
- **Dictionary** fixes words the model gets wrong:
  - **Words**: spellings to keep exactly, like "Kubernetes" or a colleague's name.
  - **Replacements**: when you say one thing, type another.
  - **Snippets**: say a short trigger and get a whole block of text, like your address.
- **Insights** counts your words per day, your speed, and which apps you dictate into.

## Meetings

Meetings records two tracks: your microphone as "Me" and your Mac's sound as "Them". Press Record when a call starts and Stop and transcribe when it ends. You can then search the transcript, play it, or export it as `.md` or `.srt`.

The "Them" track needs one more permission: System Settings > Privacy & Security > Screen & System Audio Recording > System Audio Recording Only. Use headphones, or the other side's voice also lands in your microphone track.

## When something goes wrong

| What you see | What to do |
|---|---|
| The shortcut does nothing | Turn on Input Monitoring for local-stt, then quit and reopen it. |
| It records but no text appears | Turn on Accessibility for local-stt, then quit and reopen it. If it is on already, remove it with the minus button and add it again. |
| Cleanup failed | Click Test in Settings > Cleanup to see the provider's error, such as a wrong key or no credit. |
| The "Them" track is silent | Turn on System Audio Recording Only (see Meetings). |

The app writes a log to `~/Library/Logs/io.github.hassan-mehedi.local-stt/engine.log`. Attach it when you report a problem.
