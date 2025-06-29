# skygen_constants.py

# --- Executables and Files ---
XEDIT_EXECUTABLE_NAME = "SSEEdit.exe" # Or FO4Edit.exe, TES5Edit.exe depending on game
                                      # This should ideally be configurable by the user in the UI,
                                      # but this provides a default for the plugin's internal logic.

# --- Plugin Data Paths and Names ---
# These define where the plugin stores its settings and where generated output goes.
SKYGEN_ORGANIZER_INI_FILE = "skygen_organizer.ini" # For MO2-specific settings
SKYGEN_OUTPUT_SUBFOLDER = "SkyGen Output" # Subfolder within the chosen output path for generated files
SKYGEN_OUTPUT_FILENAME_PREFIX = "skygen_generated" # Prefix for the generated output JSON/data file

# --- Logging ---
# You might add more specific logging constants here if needed,
# but general logging is handled in __init__.py and skygen_file_utilities.py

# Example: Default log level for file logging
# DEFAULT_FILE_LOG_LEVEL = "DEBUG"