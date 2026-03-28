import argparse
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
    def __init__(self, modifier_mask: int, keycode: int, mode: str) -> None:
        self.modifier_mask = modifier_mask
        self.keycode = keycode
        self.mode = mode

        self.is_recording = False
        self.hotkey_held = False
        self.audio_queue: queue.Queue[np.ndarray] = queue.Queue()
        self.sample_rate = 16000
        self.stream: sd.InputStream | None = None
        self.keyboard = KeyboardController()

        logging.info("Loading Parakeet MLX model (this may take a few seconds)...")
        self.model = parakeet_mlx.from_pretrained('mlx-community/parakeet-tdt-0.6b-v3')
        logging.info("Model loaded successfully!")

    # ── Audio ──────────────────────────────────────────────────────────

    def _audio_callback(self, indata: np.ndarray, frames, time_info, status) -> None:
        if status:
            logging.warning(f"Audio status: {status}")
        if self.is_recording:
            self.audio_queue.put(indata.copy().flatten())

    def start_recording(self) -> None:
        if self.is_recording:
            return
        logging.info("🎙  Recording...")
        self.is_recording = True

        # Drain old data
        while not self.audio_queue.empty():
            self.audio_queue.get()

        self.stream = sd.InputStream(
            samplerate=self.sample_rate, channels=1, callback=self._audio_callback
        )
        self.stream.start()

    def stop_recording(self) -> None:
        if not self.is_recording:
            return
        logging.info("⏹  Stopped recording.")
        self.is_recording = False

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
        wav_path = os.path.join(tempfile.gettempdir(), "dictation_audio.wav")
        sf.write(wav_path, audio, self.sample_rate)
        threading.Thread(target=self._transcribe_and_type, args=(wav_path,), daemon=True).start()

    # ── Transcription ──────────────────────────────────────────────────

    def _transcribe_and_type(self, wav_path: str) -> None:
        logging.info("Transcribing...")
        try:
            result = self.model.transcribe(wav_path)
            text = (result.text if hasattr(result, 'text') else str(result)).strip()
            logging.info(f"Result: '{text}'")
            if text:
                self.keyboard.type(text + ' ')
        except Exception as e:
            logging.error(f"Transcription failed: {e}")

    # ── CGEventTap callback ────────────────────────────────────────────

    def _tap_callback(self, proxy, event_type, event, refcon):
        """Called for every keyboard event. Return None to suppress, event to pass through."""
        if event_type not in (kCGEventKeyDown, kCGEventKeyUp):
            return event

        keycode = CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
        if keycode != self.keycode:
            return event  # not our key

        # On key-up: if we're holding the hotkey, always handle the release
        # (the user may have released the modifier before the main key)
        if event_type == kCGEventKeyUp and self.hotkey_held:
            self.hotkey_held = False
            if self.mode == 'push-to-talk':
                self.stop_recording()
            return None  # suppress

        # On key-down: require modifiers to be held
        flags = CGEventGetFlags(event)
        if (flags & self.modifier_mask) != self.modifier_mask:
            return event  # required modifiers not held

        if event_type == kCGEventKeyDown and not self.hotkey_held:
            self.hotkey_held = True
            if self.mode == 'push-to-talk':
                self.start_recording()
            else:  # toggle
                if self.is_recording:
                    self.stop_recording()
                else:
                    self.start_recording()
            return None  # suppress

        return None  # suppress repeated key-downs while held

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
    args = parser.parse_args()

    modifier_mask, keycode = parse_hotkey(args.hotkey)
    logging.info(f"Hotkey: {args.hotkey} (keycode={keycode}, modifier_mask={modifier_mask:#x})")

    app = DictationApp(modifier_mask, keycode, args.mode)
    app.run()


if __name__ == "__main__":
    main()
