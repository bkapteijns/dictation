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

You can configure the app using command-line arguments or environment variables.

### Command-Line Arguments

| Argument       | Default        | Description                                                        |
| :------------- | :------------- | :----------------------------------------------------------------- |
| `--hotkey`     | `option+space` | The hotkey combination (e.g., `cmd+shift+d`, `ctrl+opt+space`).    |
| `--mode`       | `push-to-talk` | `push-to-talk` (hold to record) or `toggle` (press to start/stop). |
| `--low-memory` | `False`        | Enables auto-unloading of the model after 5 minutes of inactivity. |

### Environment Variables

| Variable     | Default                              | Description                                             |
| :----------- | :----------------------------------- | :------------------------------------------------------ |
| `MODEL_NAME` | `mlx-community/parakeet-tdt-0.6b-v3` | The Hugging Face ID of the MLX-compatible model to use. |

### Example Usage

To use "toggle" mode with a custom hotkey:

```bash
python main.py --mode toggle --hotkey "cmd+shift+d" --low-memory
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

## Version Log

- **v1.2.1** – Fixed issue where model caused delay in starting recording.
- **v1.2.0** – Low-memory mode: Automatic model unloading after 5 minutes of inactivity.
- **v1.1.0** – Memory optimizations: Transcription cache clearing and resource cleanup.
- **v1.0.0** – Initial release: Local ASR using Parakeet-TDT with system-wide hotkeys.
