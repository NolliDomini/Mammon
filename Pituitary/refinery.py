import runpy

from Pituitary.refinery.service import *  # noqa: F401,F403


if __name__ == "__main__":
    runpy.run_module("Pituitary.refinery.service", run_name="__main__")

