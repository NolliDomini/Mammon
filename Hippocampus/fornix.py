import runpy

from Hippocampus.fornix.service import *  # noqa: F401,F403


if __name__ == "__main__":
    runpy.run_module("Hippocampus.fornix.service", run_name="__main__")

