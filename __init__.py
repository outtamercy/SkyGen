# __init__.py

import mobase

from .plugin import SkyGenGeneratorTool

def createPlugin() -> mobase.IPluginTool:
    return SkyGenGeneratorTool()