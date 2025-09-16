from __future__ import annotations
import pathlib, os
from init_oauth import main as init_main  # reuse the same flow

if __name__ == "__main__":
    token = pathlib.Path("secrets/token.json")
    if token.exists():
        os.remove(token)
        print("Removed old token.json")
    init_main()
