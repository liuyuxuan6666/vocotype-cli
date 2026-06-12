"""Command-line entry for the speak-keyboard prototype."""

from __future__ import annotations

import argparse
import logging
import os
import signal
import threading
import time
import sys as _sys

from app import TranscriptionResult, TranscriptionWorker, load_config, type_text
from app.plugins.dataset_recorder import wrap_result_handler
from app.logging_config import setup_logging
from app.text_postprocess import postprocess as pp_text


logger = logging.getLogger(__name__)

PID_FILE = "/tmp/vocotype.pid"

_TOGGLE_DEBOUNCE_SECONDS = 0.2
_toggle_lock = threading.Lock()
_last_toggle_time = 0.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Speak Keyboard prototype")
    parser.add_argument("--config", help="Path to config JSON")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single transcription cycle for debugging",
    )
    parser.add_argument("--save-dataset", action="store_true", help="Persist audio/text pairs")
    parser.add_argument("--dataset-dir", default="dataset", help="Dataset output directory")
    return parser.parse_args()


# Module-level state for signal handler access
_worker = None  # type: TranscriptionWorker | None
_worker_ready = threading.Event()


def main() -> None:
    global _worker

    args = parse_args()
    config = load_config(args.config)

    from app.config import ensure_logging_dir
    log_dir_abs = ensure_logging_dir(config)
    setup_logging(
        level=config["logging"].get("level", "INFO"),
        log_dir=log_dir_abs,
    )

    # Register signal handler and write PID early, before slow model init.
    # This prevents SIGUSR1 from killing the process during model download.
    signal.signal(signal.SIGUSR1, _signal_toggle)
    _write_pid_file()

    output_cfg = config.get("output", {})
    output_method = output_cfg.get("method", "auto")
    append_newline = output_cfg.get("append_newline", False)
    pp_cfg = config.get("text_postprocess", {})

    _worker = TranscriptionWorker(
        config_path=args.config,
        on_result=None,
    )

    _worker.on_result = _make_result_handler(output_method, append_newline, pp_cfg, _worker)
    if args.save_dataset:
        _worker.on_result = wrap_result_handler(_worker.on_result, _worker, args.dataset_dir)

    _worker_ready.set()

    try:
        if args.once:
            logger.info("Speak Keyboard --once 模式启动，开始录音...")
            _toggle(_worker)
            input("按 Enter 停止并退出...")
            _toggle(_worker)
        else:
            toggle_combo = config["hotkeys"].get("toggle", "f2")
            logger.info(
                "Speak Keyboard 启动完成，PID=%s。向进程发送 SIGUSR1 开始/停止录音，按 Ctrl+C 退出",
                os.getpid(),
            )
            logger.info("当前快捷键绑定: %s (通过 WM 或信号触发)", toggle_combo)
            # signal.pause() returns after each handled signal, so loop forever
            while True:
                signal.pause()
    except KeyboardInterrupt:
        logger.info("用户中断，正在退出...")
    finally:
        _worker_ready.clear()
        _cleanup_pid_file()

        try:
            _worker.stop()
        except Exception as exc:
            logger.debug("停止 worker 时出错: %s", exc)

        try:
            _worker.cleanup()
        except Exception as exc:
            logger.debug("清理 worker 时出错: %s", exc)

        logger.info("所有资源已清理，正常退出")
        _sys.exit(0)


def _signal_toggle(signum: int, frame: object) -> None:
    """SIGUSR1 handler — safe to call before worker is ready."""
    if not _worker_ready.is_set() or _worker is None:
        logger.debug("收到 toggle 信号但 worker 尚未就绪，忽略")
        return
    _toggle(_worker)


def _write_pid_file() -> None:
    try:
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))
        logger.debug("PID 文件已写入: %s", PID_FILE)
    except OSError as exc:
        logger.warning("无法写入 PID 文件 %s: %s", PID_FILE, exc)


def _cleanup_pid_file() -> None:
    try:
        if os.path.exists(PID_FILE):
            os.remove(PID_FILE)
            logger.debug("PID 文件已清理: %s", PID_FILE)
    except OSError as exc:
        logger.warning("无法清理 PID 文件 %s: %s", PID_FILE, exc)


def _make_result_handler(output_method: str, append_newline: bool, pp_cfg: dict, worker: TranscriptionWorker):
    def _handle_result(result: TranscriptionResult) -> None:
        if result.error:
            logger.error("转写失败: %s", result.error)
            return

        text = result.text

        # Text post-processing: remove fillers + fix retractions
        remove_fillers = pp_cfg.get("remove_fillers", True)
        fix_retractions = pp_cfg.get("fix_retractions", True)
        cleaned = pp_text(text, remove_fillers_flag=remove_fillers, fix_retractions_flag=fix_retractions)
        if cleaned != text:
            logger.info("后处理: '%s' → '%s'", text, cleaned)
            text = cleaned

        stats = worker.transcription_stats

        logger.info(
            "转写成功: %s (推理 %.2fs) [已完成 %d/%d，队列剩余 %d]",
            text,
            result.inference_latency,
            stats["completed"],
            stats["submitted"],
            stats["pending"],
        )
        type_text(
            text,
            append_newline=append_newline,
            method=output_method,
        )

    return _handle_result


def _toggle(worker: TranscriptionWorker) -> None:
    global _last_toggle_time
    now = time.monotonic()
    with _toggle_lock:
        if now - _last_toggle_time < _TOGGLE_DEBOUNCE_SECONDS:
            logger.debug("忽略快速重复的录音切换请求 (%.3fs)", now - _last_toggle_time)
            return
        _last_toggle_time = now

    if worker.is_running:
        worker.stop()
        stats = worker.transcription_stats
        if stats["pending"] > 0:
            logger.info(
                "录音已停止并提交转录，队列中还有 %d 个任务等待处理",
                stats["pending"],
            )
    else:
        stats = worker.transcription_stats
        if stats["pending"] > 0:
            logger.info(
                "开始录音（后台还有 %d 个转录任务正在处理）",
                stats["pending"],
            )
        worker.start()


if __name__ == "__main__":
    main()
