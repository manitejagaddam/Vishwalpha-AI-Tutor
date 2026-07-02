"""
core/logging_config.py
──────────────────────
Centralized logging configuration for the application.
"""

import sys
import logging

def configure_logging():
    """
    Configures basic logging for the application.
    Sets the log level to INFO and formats the output.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        stream=sys.stdout,
    )
    sys.stdout.reconfigure(encoding="utf-8")
