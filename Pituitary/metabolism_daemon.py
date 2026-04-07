import runpy

from Pituitary.daemon.metabolism import *  # noqa: F401,F403


if __name__ == "__main__":
    runpy.run_module("Pituitary.daemon.metabolism", run_name="__main__")

