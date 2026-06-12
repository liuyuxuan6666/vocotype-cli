"""Text injection utilities — Windows and Linux/Wayland."""

from __future__ import annotations

import logging
import os
import subprocess
import sys


logger = logging.getLogger(__name__)


# ---- Windows ---------------------------------------------------------------
if sys.platform == "win32":
    import ctypes
    import ctypes.wintypes as wintypes

    SendInput = ctypes.windll.user32.SendInput
    GetMessageExtraInfo = ctypes.windll.user32.GetMessageExtraInfo

    INPUT_KEYBOARD = 1
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004
    VK_CONTROL = 0x11
    VK_V = 0x56

    if hasattr(wintypes, "ULONG_PTR"):
        ULONG_PTR = wintypes.ULONG_PTR
    else:
        if ctypes.sizeof(ctypes.c_void_p) == ctypes.sizeof(ctypes.c_uint64):
            ULONG_PTR = ctypes.c_uint64
        else:
            ULONG_PTR = ctypes.c_uint32

    class KeyboardInput(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ULONG_PTR),
        ]

    class InputUnion(ctypes.Union):
        _fields_ = [("ki", KeyboardInput)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("union", InputUnion)]

    def _emit_unicode_char(char: str) -> bool:
        code_point = ord(char)
        input_array_type = INPUT * 2
        inputs = input_array_type(
            INPUT(
                type=INPUT_KEYBOARD,
                union=InputUnion(
                    ki=KeyboardInput(
                        wVk=0,
                        wScan=code_point,
                        dwFlags=KEYEVENTF_UNICODE,
                        time=0,
                        dwExtraInfo=GetMessageExtraInfo(),
                    )
                ),
            ),
            INPUT(
                type=INPUT_KEYBOARD,
                union=InputUnion(
                    ki=KeyboardInput(
                        wVk=0,
                        wScan=code_point,
                        dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
                        time=0,
                        dwExtraInfo=GetMessageExtraInfo(),
                    )
                ),
            ),
        )
        pointer = ctypes.byref(inputs[0])
        sent = SendInput(len(inputs), pointer, ctypes.sizeof(INPUT))
        if sent != len(inputs):
            logger.warning("SendInput 发送字符失败，char=%s，返回值=%s", char, sent)
            return False
        return True

    def _type_with_keyboard(payload: str) -> bool:
        try:
            import keyboard

            keyboard.write(payload, delay=0)
            return True
        except Exception as exc:
            logger.warning("keyboard.write 失败: %s", exc)
            return False

    def _type_with_unicode(payload: str) -> bool:
        success = True
        for char in payload:
            if not _emit_unicode_char(char):
                success = False
                break
        return success

    def _try_clipboard_injection(payload: str) -> bool:
        try:
            import pyperclip
        except ImportError:
            return False

        try:
            prev_clip = pyperclip.paste()
        except Exception:
            prev_clip = None

        try:
            pyperclip.copy(payload)
            success = _emit_ctrl_v()
        except Exception as exc:
            logger.debug("剪贴板注入失败，退回逐字符输入: %s", exc)
            success = False
        finally:
            if prev_clip is not None:
                try:
                    pyperclip.copy(prev_clip)
                except Exception:
                    pass

        return success

    def _emit_ctrl_v() -> bool:
        input_array_type = INPUT * 4
        inputs = input_array_type(
            INPUT(
                type=INPUT_KEYBOARD,
                union=InputUnion(
                    ki=KeyboardInput(
                        wVk=VK_CONTROL,
                        wScan=0,
                        dwFlags=0,
                        time=0,
                        dwExtraInfo=GetMessageExtraInfo(),
                    )
                ),
            ),
            INPUT(
                type=INPUT_KEYBOARD,
                union=InputUnion(
                    ki=KeyboardInput(
                        wVk=VK_V,
                        wScan=0,
                        dwFlags=0,
                        time=0,
                        dwExtraInfo=GetMessageExtraInfo(),
                    )
                ),
            ),
            INPUT(
                type=INPUT_KEYBOARD,
                union=InputUnion(
                    ki=KeyboardInput(
                        wVk=VK_V,
                        wScan=0,
                        dwFlags=KEYEVENTF_KEYUP,
                        time=0,
                        dwExtraInfo=GetMessageExtraInfo(),
                    )
                ),
            ),
            INPUT(
                type=INPUT_KEYBOARD,
                union=InputUnion(
                    ki=KeyboardInput(
                        wVk=VK_CONTROL,
                        wScan=0,
                        dwFlags=KEYEVENTF_KEYUP,
                        time=0,
                        dwExtraInfo=GetMessageExtraInfo(),
                    )
                ),
            ),
        )
        pointer = ctypes.byref(inputs[0])
        sent = SendInput(len(inputs), pointer, ctypes.sizeof(INPUT))
        if sent != len(inputs):
            logger.warning("SendInput Ctrl+V 失败，返回值=%s", sent)
            sent_retry = SendInput(len(inputs), pointer, ctypes.sizeof(INPUT))
            if sent_retry != len(inputs):
                logger.warning("SendInput Ctrl+V 第二次重试失败，返回值=%s", sent_retry)
                return False
        return True

    _WIN_METHOD_ORDER = {
        "type": ["type", "clipboard", "unicode"],
        "clipboard": ["clipboard", "type", "unicode"],
        "unicode": ["unicode"],
        "auto": ["type", "clipboard", "unicode"],
    }

# ---- Linux -----------------------------------------------------------------
else:
    _WIN_METHOD_ORDER = {}  # unused on Linux; silences linters

    def _is_wayland() -> bool:
        return bool(os.environ.get("WAYLAND_DISPLAY"))

    def _type_with_wtype(payload: str) -> bool:
        """Simulate keyboard input via wtype (Wayland native)."""
        try:
            subprocess.run(
                ["wtype", "--", payload],
                check=True,
                timeout=10,
                capture_output=True,
            )
            return True
        except FileNotFoundError:
            logger.debug("wtype 未安装")
            return False
        except subprocess.CalledProcessError as exc:
            logger.warning("wtype 执行失败: %s", exc)
            return False
        except Exception as exc:
            logger.warning("wtype 调用异常: %s", exc)
            return False

    def _type_with_linux_clipboard(payload: str) -> bool:
        """Copy to clipboard then simulate Ctrl+V via wtype."""
        if not _is_wayland():
            return _type_with_xdotool_clipboard(payload)

        try:
            prev = subprocess.run(
                ["wl-paste"], capture_output=True, timeout=2
            )
            prev_clip = prev.stdout if prev.returncode == 0 else None
        except Exception:
            prev_clip = None

        try:
            subprocess.run(
                ["wl-copy"], input=payload.encode(), check=True, timeout=5
            )
            subprocess.run(
                ["wtype", "-M", "ctrl", "v", "-m", "ctrl"],
                check=True, timeout=5, capture_output=True,
            )
            return True
        except FileNotFoundError:
            logger.debug("wl-copy 或 wtype 未安装")
            return False
        except Exception as exc:
            logger.warning("剪贴板注入失败: %s", exc)
            return False
        finally:
            if prev_clip is not None:
                try:
                    subprocess.run(
                        ["wl-copy"], input=prev_clip, timeout=2
                    )
                except Exception:
                    pass

    def _type_with_xdotool_clipboard(payload: str) -> bool:
        """X11 fallback: clipboard paste via xdotool."""
        try:
            prev = subprocess.run(
                ["xclip", "-selection", "clipboard", "-o"],
                capture_output=True, timeout=2,
            )
            prev_clip = prev.stdout if prev.returncode == 0 else None
        except Exception:
            prev_clip = None

        try:
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=payload.encode(), check=True, timeout=5,
            )
            subprocess.run(
                ["xdotool", "key", "ctrl+v"],
                check=True, timeout=5, capture_output=True,
            )
            return True
        except Exception as exc:
            logger.warning("xdotool 剪贴板注入失败: %s", exc)
            return False
        finally:
            if prev_clip is not None:
                try:
                    subprocess.run(
                        ["xclip", "-selection", "clipboard"],
                        input=prev_clip, timeout=2,
                    )
                except Exception:
                    pass

    def _type_with_xdotool(payload: str) -> bool:
        """X11 fallback: direct typing via xdotool."""
        try:
            subprocess.run(
                ["xdotool", "type", "--", payload],
                check=True, timeout=10, capture_output=True,
            )
            return True
        except Exception as exc:
            logger.warning("xdotool type 失败: %s", exc)
            return False

    _LINUX_METHOD_ORDER = {
        "wtype": ["wtype", "clipboard"],
        "clipboard": ["clipboard", "wtype"],
        "auto": ["wtype", "clipboard"],
    }


# ---- Shared entry point ---------------------------------------------------


def type_text(text: str, append_newline: bool = False, method: str = "auto") -> None:
    if not text:
        return

    # Resolve method — per-app override > explicit method > auto
    if method == "auto" and sys.platform != "win32":
        app_method = _detect_window_method(_app_methods_config)
        if app_method:
            method = app_method

    newline = "\r\n" if sys.platform == "win32" else "\n"
    payload = text + (newline if append_newline else "")
    logger.debug("注入文本: %s", payload)

    if sys.platform == "win32":
        _type_text_windows(payload, method)
    else:
        _type_text_linux(payload, method)


# Per-app method overrides (set by set_app_methods_config)
_app_methods_config: dict | None = None


def set_app_methods_config(cfg: dict | None) -> None:
    """Set per-application injection method mapping (called from main.py)."""
    global _app_methods_config
    _app_methods_config = cfg


def _detect_window_method(app_map: dict | None) -> str | None:
    """Return injection method for the currently focused window, or None."""
    if not app_map:
        return None
    try:
        import json as _json
        info = _json.loads(
            subprocess.run(
                ["hyprctl", "activewindow", "-j"],
                capture_output=True, timeout=2, text=True,
            ).stdout
        )
        wclass = info.get("class", "") or ""
        for pattern, method in app_map.items():
            if pattern and method and pattern.lower() in wclass.lower():
                logger.debug("按窗口 %s 选择方式: %s", wclass, method)
                return method
    except Exception as exc:
        logger.debug("检测当前窗口失败: %s", exc)
    return None


def _type_text_windows(payload: str, method: str) -> None:
    method = (method or "auto").lower()
    order = _WIN_METHOD_ORDER.get(method, _WIN_METHOD_ORDER["auto"])

    for mode in order:
        if mode == "type" and _type_with_keyboard(payload):
            return
        if mode == "clipboard" and _try_clipboard_injection(payload):
            return
        if mode == "unicode" and _type_with_unicode(payload):
            return

    logger.error("所有文本注入方式均失败: %s", payload)


def _type_text_linux(payload: str, method: str) -> None:
    method = (method or "auto").lower()
    order = _LINUX_METHOD_ORDER.get(method, _LINUX_METHOD_ORDER["auto"])

    for mode in order:
        if mode == "wtype" and _type_with_wtype(payload):
            return
        if mode == "clipboard" and _type_with_linux_clipboard(payload):
            return

    # Last resort: try xdotool on X11
    if not _is_wayland() and _type_with_xdotool(payload):
        return

    logger.error("所有文本注入方式均失败: %s", payload)
