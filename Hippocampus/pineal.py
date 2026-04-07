import runpy

from Hippocampus.pineal.service import *  # noqa: F401,F403


if __name__ == "__main__":
    runpy.run_module("Hippocampus.pineal.service", run_name="__main__")

