import runpy

from Hippocampus.duck_pond.service import *  # noqa: F401,F403


if __name__ == "__main__":
    runpy.run_module("Hippocampus.duck_pond.service", run_name="__main__")

