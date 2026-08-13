"""App identity and (in later phases) persisted user settings.

Phase 0 keeps only static identity constants. User settings — folder path,
player choice, autostart toggle, server address, group membership — land with
the first-run wizard (Phase 3). All settings are managed from the GUI; users
never edit files by hand (AGENTS.md §2).
"""

APP_NAME = "groupwatch"
