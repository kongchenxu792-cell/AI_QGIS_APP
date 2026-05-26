"""
应用级日志系统 — 文件 + 控制台双通道，自动捕获未处理异常。
"""

from __future__ import annotations

import logging
import os
import sys
import traceback
from pathlib import Path

_log_initialized = False


def _get_log_dir() -> Path:
    """获取日志目录（项目根下的 logs/）。"""
    # 从当前模块路径向上找到项目根（src/core/logger.py → 项目根）
    module_dir = Path(__file__).resolve().parent  # core/
    src_dir = module_dir.parent                    # src/
    project_root = src_dir.parent                  # 项目根
    log_dir = project_root / "logs"
    log_dir.mkdir(exist_ok=True)
    return log_dir


def init_logging(verbose: bool = False) -> None:
    """
    初始化全局日志系统（幂等，多次调用只生效一次）。

    Parameters
    ----------
    verbose : bool
        True 时控制台也输出 DEBUG 级别日志，默认只写文件。
    """
    global _log_initialized
    if _log_initialized:
        return
    _log_initialized = True

    log_dir = _get_log_dir()
    log_file = log_dir / "aiqgis.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # 文件 handler — 记录完整 DEBUG 及以上日志
    file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root_logger.addHandler(file_handler)

    # 控制台 handler — 默认只输出 WARNING+
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG if verbose else logging.WARNING)
    console_handler.setFormatter(logging.Formatter(
        "[%(levelname)s] %(name)s: %(message)s"
    ))
    root_logger.addHandler(console_handler)

    # 全局异常钩子
    _install_excepthook(log_file)

    root_logger.info("=" * 60)
    root_logger.info("AIQGIS 日志系统已启动")
    root_logger.info(f"日志文件：{log_file}")
    root_logger.info(f"Python {sys.version}")
    root_logger.info("=" * 60)


def _install_excepthook(log_file: Path) -> None:
    """安装全局未处理异常钩子，将完整 traceback 写入日志。"""
    original_hook = sys.excepthook

    def _aiqgis_excepthook(exc_type, exc_value, exc_tb):
        tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logging.getLogger("UNHANDLED").critical(f"\n{tb_text}")

        # 也写一份独立的 crash 日志
        crash_file = log_file.with_suffix(".crash.txt")
        try:
            with open(crash_file, "a", encoding="utf-8") as f:
                f.write(f"\n{'=' * 60}\n")
                f.write(tb_text)
        except Exception:
            pass

        # 调回原始钩子（Qt 弹窗等）
        original_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = _aiqgis_excepthook


def get_logger(name: str) -> logging.Logger:
    """获取模块级 logger（自动确保已初始化）。"""
    if not _log_initialized:
        init_logging()
    return logging.getLogger(name)