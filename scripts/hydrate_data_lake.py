import runpy
from scripts.tools.hydrate_data_lake import *  # noqa: F401,F403
if __name__ == "__main__":
    runpy.run_module("scripts.tools.hydrate_data_lake", run_name="__main__")
