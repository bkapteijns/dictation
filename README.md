# macOS Local Dictation (Parakeet MLX)

A private dictation tool for macOS, as a replacement for Apple's standard dictation. It uses NVIDIA's **Parakeet-TDT** model (running locally via Apple's **MLX** framework) to transcribe your voice instantly into any text field. No data leaves your machine.

## Features

- **100% Local**: All transcription happens on your Mac's GPU/Neural Engine.
- **System-wide**: Works in any app (Chrome, Slack, VS Code, etc.).
- **Push-to-Talk**: Hold `Option + Space` to record, release to transcribe and type.
- **Automatic Setup**: A single script handles environment creation and launcher setup.

## Prerequisites

- macOS (Apple Silicon recommended for best performance).
- [Homebrew](https://brew.sh) for automatic installation of Miniconda.
  - Alternatively, install [Miniconda](https://docs.conda.io/en/latest/miniconda.html) manually.

## Installation

1. **Clone the repository**:

   ```bash
   git clone https://github.com/bramkapteijns/dictation
   cd dictation
   ```

2. **Run the setup script**:
   This will create a Login item in the system.

   ```bash
   ./setup.sh
   ```

   Alternatively, you can manually run the dictation app by running:

   ```bash
   ./run.sh
   ```

3. **Grant Accessibility Permissions**:
   The first time the app runs, your terminal will ask for "Accessibility" permissions. This is required to intercept the hotkey and inject text.
   - Go to **System Settings > Privacy & Security > Accessibility**.
   - Make sure your **Terminal** is enabled.

## Usage

- **Start/Record**: Hold `Option + Space`. Speak your mind.
- **Finish/Type**: Release the keys (ideally release `Space` first). The transcription will appear wherever your cursor is.

## Configuration

You can modify the hotkey or mode by editing `run.sh`. For example, to use "toggle" mode:

```bash
python main.py --mode toggle --hotkey "cmd+shift+d"
```

## Uninstallation

To stop the background app, run:

```bash
./stop.sh
```

Alternatively, you can search the process in Activity Monitor and kill it.

To remove the login item and the compiled app, run:

```bash
./destroy.sh
```
