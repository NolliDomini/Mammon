import runpy

from Hippocampus.schema_guard.service import *  # noqa: F401,F403


if __name__ == "__main__":
    runpy.run_module("Hippocampus.schema_guard.service", run_name="__main__")

