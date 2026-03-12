"""
Entry point for running nanobot as a module: python -m nanobot
"""

import sys, os
sys.path.append(os.path.dirname(os.getcwd()))

from nanobot.cli.commands import app

if __name__ == "__main__":
    app()
