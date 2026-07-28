#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Авто-рестарт bot.py для запуска на ПК/VPS.
На Render/Koyeb/Amvera лучше запускать напрямую: python bot.py
"""

import subprocess
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
BOT = BASE_DIR / "bot.py"

# Must match bot.py
EXIT_TELEGRAM_CONFLICT = 75
EXIT_ALREADY_RUNNING = 76


def main() -> None:
    while True:
        print("[run_forever] starting bot.py", flush=True)
        proc = subprocess.Popen([sys.executable, str(BOT)], cwd=str(BASE_DIR))
        code = proc.wait()

        if code in (EXIT_TELEGRAM_CONFLICT, EXIT_ALREADY_RUNNING):
            print(
                "[run_forever] duplicate bot instance detected. "
                "Auto-restart stopped to prevent Conflict getUpdates.",
                flush=True,
            )
            return

        print(f"[run_forever] bot.py exited with code {code}; restart in 3 sec", flush=True)
        time.sleep(3)


if __name__ == "__main__":
    main()
