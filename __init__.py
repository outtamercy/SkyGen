# __init__.py

import mobase

from .plugin import SkyGenPlugin # Changed SkyGenGeneratorTool to SkyGenPlugin

def createPlugin() -> mobase.IPluginTool:
    return SkyGenPlugin() # Changed SkyGenGeneratorTool to SkyGenPlugin
