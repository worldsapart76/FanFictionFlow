"""
FanFictionFlow configuration.

All system paths and user-tunable settings live here.
Logic modules must import from this file — never hardcode paths.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# System paths
# ---------------------------------------------------------------------------

CALIBREDB_PATH = Path(r"C:\Program Files\Calibre2\calibredb.exe")
LIBRARY_PATH = Path(r"F:\Dropbox\Reading\Ebooks\FanFiction")

# Set at runtime via the GUI; these are defaults that can be overridden.
EPUB_DOWNLOAD_DIR: Path = Path.home() / "Downloads" / "FanFicDownloads"

# ---------------------------------------------------------------------------
# Boox Palma — ADB transfer settings
#
# The Palma connects via MTP (not as a drive letter), so file transfer uses
# ADB push. USB debugging must be enabled on the device.
# ---------------------------------------------------------------------------

BOOX_ADB_CMD: str = "adb"          # "adb" if on PATH; else full path to adb.exe
BOOX_DEVICE_SERIAL: str = ""       # empty = use the only connected device
BOOX_DEVICE_PATH: str = "/sdcard/Books"  # destination directory on the Palma

# ---------------------------------------------------------------------------
# Input file names (resolved relative to a user-selected working directory)
# ---------------------------------------------------------------------------

MARKED_FOR_LATER_FILENAME = "marked_for_later.csv"
READ_STATUS_EXPORT_FILENAME = "read_status_export.csv"

# ---------------------------------------------------------------------------
# Output file names
# ---------------------------------------------------------------------------

LIBRARY_CSV_FILENAME = "library_csv.csv"

# ---------------------------------------------------------------------------
# FanFicFare — download settings
# ---------------------------------------------------------------------------

# AO3 credentials file — FanFicFare reads this automatically from this path.
# The app writes to this file when the user updates credentials via the GUI.
AO3_PERSONAL_INI_PATH: Path = (
    Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    / "fanficfare"
    / "personal.ini"
)

# Command used to invoke FanFicFare. Uses the full path to fanficfare.exe so
# that subprocess.run finds it regardless of the calling process's PATH.
# Installed via: pip install fanficfare
FANFICFARE_CMD: str = r"C:\Users\world\AppData\Local\Programs\Python\Python312\Scripts\fanficfare.exe"

# Extra -o key=value options passed to every FanFicFare invocation.
# is_adult=true is required to download Mature/Explicit-rated AO3 stories.
FANFICFARE_EXTRA_OPTIONS: list[str] = ["is_adult=true"]

FANFICFARE_BATCH_SIZE: int = 5       # stories per batch
FANFICFARE_BATCH_DELAY: int = 10     # seconds to pause between batches
FANFICFARE_STORY_DELAY: int = 30     # seconds to pause between every individual story
FANFICFARE_TIMEOUT: int = 120        # seconds before a single download is killed

# Cloudflare transient error retry settings.
# AO3 sits behind Cloudflare, which can return 525 (SSL handshake timeout)
# and similar transient errors. These usually clear on a retry after a wait.
FANFICFARE_RETRY_COUNT: int = 3      # max retries per story after a CF error
FANFICFARE_RETRY_DELAY: int = 60     # seconds to wait before each retry

# ---------------------------------------------------------------------------
# Read status
# ---------------------------------------------------------------------------

# Default #readstatus written to Calibre for newly imported stories.
DEFAULT_READ_STATUS: str = "unread"

# ---------------------------------------------------------------------------
# Ship normalization — shortname override table (user-editable)
#
# Maps cleaned AO3 ship string → preferred Calibre #primaryship value.
# Add entries here for ships where the full name differs from what is stored
# in your Calibre library.
# ---------------------------------------------------------------------------

SHIP_SHORTNAME_OVERRIDES: dict[str, str] = {
    "Katniss Everdeen/Peeta Mellark": "Katniss/Peeta",
    "Elizabeth Bennet/Fitzwilliam Darcy": "Darcy/Elizabeth",
    'James "Bucky" Barnes/Clint Barton': "Bucky/Clint",
    "Jason Todd/Tim Drake": "Tim Drake/Jason Todd",
    "Regulus Black/James Potter": "Regulus/James",
}

# ---------------------------------------------------------------------------
# Collection keyword table (user-editable)
#
# Ordered list of (keyword, collection_name) pairs. First match wins.
# Keywords are matched case-insensitively against the AO3 fandoms field.
# ---------------------------------------------------------------------------

COLLECTION_KEYWORDS: list[tuple[str, str]] = [
    ("Stray Kids", "Stray Kids"),
    ("ATEEZ", "ATEEZ"),
    ("Hunger Games", "Hunger Games"),
    ("Harry Potter", "Harry Potter"),
    ("Batman", "DCU"),
    ("DCU", "DCU"),
    ("DC Comics", "DCU"),
    ("Marvel", "Marvel"),
    ("Avengers", "Marvel"),
    ("Pride and Prejudice", "Jane Austen"),
    ("Jane Austen", "Jane Austen"),
    ("Roswell New Mexico", "Roswell"),
    ("Mass Effect", "Mass Effect"),
    ("Dragon Age", "Dragon Age"),
    ("Shadowhunters", "Shadowhunters"),
    ("Mortal Instruments", "Shadowhunters"),
    ("Star Wars", "Star Wars"),
    ("Teen Wolf", "Teen Wolf"),
    ("Witcher", "Witcher"),
    ("Skyrim", "Skyrim"),
    ("Elder Scrolls", "Skyrim"),
]
