import argparse
import gc
import sys
import threading
import queue
import logging
import os
import tempfile
import numpy as np
import sounddevice as sd
import soundfile as sf
from pynput.keyboard import Controller as KeyboardController
import parakeet_mlx
import mlx.core as mx

from Quartz import (
    CGEventGetFlags,
    CGEventGetIntegerValueField,
    CGEventMaskBit,
    CGEventTapCreate,
    CGEventTapEnable,
    CFMachPortCreateRunLoopSource,
    CFRunLoopAddSource,
    CFRunLoopGetCurrent,
    CFRunLoopRunInMode,
    kCFRunLoopDefaultMode,
    kCGEventKeyDown,
    kCGEventKeyUp,
    kCGEventFlagMaskAlternate,
    kCGEventFlagMaskCommand,
    kCGEventFlagMaskControl,
    kCGEventFlagMaskShift,
    kCGHeadInsertEventTap,
    kCGKeyboardEventKeycode,
    kCGSessionEventTap,
    kCGEventTapOptionDefault,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


# ── Hotkey parsing tables ──────────────────────────────────────────────

MODIFIER_NAMES: dict[str, int] = {
    'alt':     int(kCGEventFlagMaskAlternate),
    'option':  int(kCGEventFlagMaskAlternate),
    'opt':     int(kCGEventFlagMaskAlternate),
    'cmd':     int(kCGEventFlagMaskCommand),
    'command': int(kCGEventFlagMaskCommand),
    'ctrl':    int(kCGEventFlagMaskControl),
    'control': int(kCGEventFlagMaskControl),
    'shift':   int(kCGEventFlagMaskShift),
}

KEY_NAMES: dict[str, int] = {
    'space': 49, 'return': 36, 'enter': 36, 'tab': 48,
    'escape': 53, 'esc': 53, 'delete': 51, 'backspace': 51,
    'up': 126, 'down': 125, 'left': 123, 'right': 124,
    'f1': 122, 'f2': 120, 'f3': 99, 'f4': 118, 'f5': 96,
    'f6': 97, 'f7': 98, 'f8': 100, 'f9': 101, 'f10': 109,
    'f11': 103, 'f12': 111,
    # Characters (ANSI layout virtual keycodes)
    'a': 0, 'b': 11, 'c': 8, 'd': 2, 'e': 14, 'f': 3, 'g': 5,
    'h': 4, 'i': 34, 'j': 38, 'k': 40, 'l': 37, 'm': 46, 'n': 45,
    'o': 31, 'p': 35, 'q': 12, 'r': 15, 's': 1, 't': 17, 'u': 32,
    'v': 9, 'w': 13, 'x': 7, 'y': 16, 'z': 6,
    '0': 29, '1': 18, '2': 19, '3': 20, '4': 21, '5': 23,
    '6': 22, '7': 26, '8': 28, '9': 25,
}

def parse_hotkey(hotkey_str: str) -> tuple[int, int]:
    """Parse a hotkey string like 'option+space' into (modifier_mask, keycode)."""
    modifier_mask: int = 0
    keycode = None

    for part in hotkey_str.lower().split('+'):
        part = part.strip()
        if part in MODIFIER_NAMES:
            # pyre-ignore[16]
            modifier_mask = modifier_mask | int(MODIFIER_NAMES[part])
        elif part in KEY_NAMES:
            if keycode is not None:
                raise ValueError(
                    f"Hotkey cannot include multiple primary keys! "
                    f"Found '{part}' but already parsed another key."
                )
            keycode = KEY_NAMES[part]
        else:
            raise ValueError(
                f"Unknown key '{part}'. "
                f"Valid modifiers: {list(MODIFIER_NAMES)}. "
                f"Valid keys: {list(KEY_NAMES)}."
            )

    if keycode is None:
        raise ValueError("Hotkey must include a non-modifier key (e.g. 'space', 'd').")
    if modifier_mask == 0:
        raise ValueError("Hotkey must include at least one modifier (e.g. 'option', 'ctrl').")

    # pyre-ignore[7]
    return modifier_mask, keycode


# ── Dictation app ──────────────────────────────────────────────────────

class DictationApp:
    UNLOAD_TIMEOUT_SECONDS = 300  # 5 minutes

    def __init__(self, modifier_mask: int, keycode: int, mode: str, low_memory: bool = False) -> None:
        self.modifier_mask = modifier_mask
        self.keycode = keycode
        self.mode = mode
        self.low_memory = low_memory

        self.is_recording = threading.Event()
        self.hotkey_held = False
        self.audio_queue: queue.Queue[np.ndarray] = queue.Queue()
        self.sample_rate = 16000
        self.stream: sd.InputStream | None = None
        self.keyboard = KeyboardController()

        self._timer_lock = threading.Lock()
        self._unload_timer: threading.Timer | None = None
        self._unload_token = 0
        
        self.mic_task_queue: queue.Queue = queue.Queue()
        threading.Thread(target=self._mic_worker, daemon=True).start()

        self.model_task_queue: queue.Queue = queue.Queue()
        threading.Thread(target=self._model_worker, daemon=True).start()

        self.model_name = os.environ.get("MODEL_NAME", "mlx-community/parakeet-tdt-0.6b-v3")
        self.model = None
        self._load_model()
        self._reset_unload_timer()

    # –– Background workers –––––––––––––––––––––––––––––––––––––––––––––

    def _model_worker(self) -> None:
        """Background thread executing all MLX model operations sequentially."""
        while True:
            task = self.model_task_queue.get()
            try:
                task()
            except Exception as e:
                logging.error(f"Model worker failed: {e}")
            finally:
                self.model_task_queue.task_done()

    def _mic_worker(self) -> None:
        """Background thread executing microphone start/stop safely off the UI thread."""
        while True:
            task = self.mic_task_queue.get()
            try:
                task()
            except Exception as e:
                logging.error(f"Mic worker failed: {e}")
            finally:
                self.mic_task_queue.task_done()

    # ── Model lifecycle ────────────────────────────────────────────────

    def _load_model(self) -> None:
        """Load the transcription model into memory (no-op if already loaded)."""
        if self.model is not None:
            return
        logging.info(f"Loading transcription model '{self.model_name}' (this may take a few seconds)...")
        self.model = parakeet_mlx.from_pretrained(self.model_name)
        logging.info("Model loaded successfully!")

    def _unload_model(self, token: int) -> None:
        """Unload the model from memory to free resources."""
        with self._timer_lock:
            if token != self._unload_token:
                return

        if self.model is None:
            return
        logging.info("Unloading model due to inactivity...")
        self.model = None
        gc.collect()
        mx.clear_cache()
        logging.info("Model unloaded. A cold start will be required on next dictation.")

    def _time_unload(self, token: int) -> None:
        self.model_task_queue.put(lambda: self._unload_model(token))

    def _reset_unload_timer(self) -> None:
        """(Re)start the inactivity timer that unloads the model. Only active in low-memory mode."""
        if not self.low_memory:
            return
        with self._timer_lock:
            if self._unload_timer is not None:
                self._unload_timer.cancel()
            self._unload_token += 1
            token = self._unload_token
            # Use _time_unload to push the unload task to the model queue
            self._unload_timer = threading.Timer(self.UNLOAD_TIMEOUT_SECONDS, self._time_unload, args=(token,))
            self._unload_timer.daemon = True
            self._unload_timer.start()

    # ── Audio ──────────────────────────────────────────────────────────

    def _audio_callback(self, indata: np.ndarray, frames, time_info, status) -> None:
        if status:
            logging.warning(f"Audio status: {status}")
        if self.is_recording.is_set():
            self.audio_queue.put(indata.copy().flatten())

    def start_recording(self) -> None:
        if self.is_recording.is_set():
            return
        logging.info("🎙  Recording...")

        # Cancel the inactivity timer while the user is actively recording
        with self._timer_lock:
            if self._unload_timer is not None:
                self._unload_timer.cancel()
                self._unload_timer = None
            # Increment the token to invalidate any already-queued unloads
            self._unload_token += 1

        # Preload model in background so it's ready by the time the user stops speaking
        self.model_task_queue.put(self._load_model)
        self.is_recording.set()

        while not self.audio_queue.empty():
            self.audio_queue.get()

        try:
            self.stream = sd.InputStream(
                samplerate=self.sample_rate, channels=1, callback=self._audio_callback
            )
            self.stream.start()
        except Exception as e:
            self.is_recording.clear()
            logging.error(f"Failed to start hardware microphone stream: {e}")
            raise  # Let the worker thread log it normally

    def toggle_recording(self) -> None:
        """Helper to synchronously toggle state on the mic worker thread."""
        if self.is_recording.is_set():
            self.stop_recording()
        else:
            self.start_recording()

    def stop_recording(self) -> None:
        if not self.is_recording.is_set():
            return
        logging.info("⏹  Stopped recording.")
        self.is_recording.clear()

        if self.stream is not None:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        chunks = []
        while not self.audio_queue.empty():
            chunks.append(self.audio_queue.get())

        if not chunks:
            logging.warning("No audio captured.")
            return

        audio = np.concatenate(chunks)
        
        # Pad with silence if the audio is exceedingly short
        min_length = int(self.sample_rate * 0.1)
        if len(audio) < min_length:
            padding = np.zeros(min_length - len(audio), dtype=audio.dtype)
            audio = np.concatenate([audio, padding])

        tmp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        wav_path = tmp_file.name
        tmp_file.close()

        thread_started = False
        try:
            sf.write(wav_path, audio, self.sample_rate)
            self.model_task_queue.put(lambda p=wav_path: self._transcribe_and_type(p))
            thread_started = True
        except Exception as e:
            logging.error(f"Failed to write audio to file: {e}")
        finally:
            if not thread_started and os.path.exists(wav_path):
                try:
                    os.remove(wav_path)
                except Exception as e:
                    logging.warning(f"Failed to delete temp file {wav_path}: {e}")

    # ── Transcription ──────────────────────────────────────────────────

    def _transcribe_and_type(self, wav_path: str) -> None:
        logging.info("Transcribing...")
        try:
            self._load_model()  # no-op if already loaded; cold start if unloaded
            result = self.model.transcribe(wav_path)
            text = (result.text if hasattr(result, 'text') else str(result)).strip()
            logging.info(f"Result: '{text}'")
            if text:
                self.keyboard.type(text + ' ')
        except Exception as e:
            logging.error(f"Transcription failed: {e}")
        finally:
            if 'result' in locals():
                del result
            if 'text' in locals():
                del text

            gc.collect()
            try:
                mx.clear_cache()
            except Exception as e:
                logging.error(f"Failed to clear MLX cache: {e}")

            if os.path.exists(wav_path):
                try:
                    os.remove(wav_path)
                except Exception as e:
                    logging.warning(f"Failed to delete temp file {wav_path}: {e}")

            self._reset_unload_timer()

    # ── CGEventTap callback ────────────────────────────────────────────

    def _tap_callback(self, proxy, event_type, event, refcon):
        """Called for every keyboard event. Return None to suppress, event to pass through."""
        if event_type not in (kCGEventKeyDown, kCGEventKeyUp):
            return event

        keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
        if keycode != self.keycode:
            return event

        if event_type == kCGEventKeyUp and self.hotkey_held:
            self.hotkey_held = False
            if self.mode == 'push-to-talk':
                self.mic_task_queue.put(self.stop_recording)
            return None

        flags = CGEventGetFlags(event)
        primary_mask = kCGEventFlagMaskShift | kCGEventFlagMaskControl | kCGEventFlagMaskAlternate | kCGEventFlagMaskCommand
        if (flags & primary_mask) != self.modifier_mask:
            return event

        if event_type == kCGEventKeyDown and not self.hotkey_held:
            self.hotkey_held = True
            if self.mode == 'push-to-talk':
                self.mic_task_queue.put(self.start_recording)
            else:
                self.mic_task_queue.put(self.toggle_recording)
            return None

        return None

    # ── Run loop ───────────────────────────────────────────────────────

    def run(self) -> None:
        mask = CGEventMaskBit(kCGEventKeyDown) | CGEventMaskBit(kCGEventKeyUp)

        tap = CGEventTapCreate(
            kCGSessionEventTap,
            kCGHeadInsertEventTap,
            kCGEventTapOptionDefault,
            mask,
            self._tap_callback,
            None,
        )

        if tap is None:
            logging.error(
                "Failed to create event tap! "
                "Grant Accessibility permissions to your terminal in "
                "System Settings > Privacy & Security > Accessibility."
            )
            sys.exit(1)

        source = CFMachPortCreateRunLoopSource(None, tap, 0)
        loop = CFRunLoopGetCurrent()
        CFRunLoopAddSource(loop, source, kCFRunLoopDefaultMode)
        CGEventTapEnable(tap, True)

        logging.info("Ready — listening for hotkey. Press Ctrl+C to quit.")

        try:
            while True:
                CFRunLoopRunInMode(kCFRunLoopDefaultMode, 1, False)
        except KeyboardInterrupt:
            logging.info("Bye!")


# ── CLI ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Dictation App using Parakeet MLX")
    parser.add_argument(
        "--hotkey",
        default="option+space",
        help="Hotkey combination, e.g. 'option+space', 'ctrl+shift+d'. Default: option+space",
    )
    parser.add_argument(
        "--mode",
        choices=["push-to-talk", "toggle"],
        default="push-to-talk",
        help="'push-to-talk' (hold to record) or 'toggle' (press to start/stop). Default: push-to-talk",
    )
    parser.add_argument(
        "--low-memory",
        action="store_true",
        default=False,
        help="Enable low-memory mode: unload the model after 5 minutes of inactivity (cold start on next use).",
    )
    args = parser.parse_args()

    try:
        modifier_mask, keycode = parse_hotkey(args.hotkey)
        logging.info(f"Hotkey: {args.hotkey} (keycode={keycode}, modifier_mask={modifier_mask:#x})")
    except ValueError as e:
        logging.error(f"Invalid hotkey configuration: {e}")
        sys.exit(1)

    app = DictationApp(modifier_mask, keycode, args.mode, low_memory=args.low_memory)
    app.run()


if __name__ == "__main__":
    main()
