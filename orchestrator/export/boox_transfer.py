"""
export/boox_transfer.py — Milestone 9: Boox Palma ADB transfer.

Copies epub files and the library CSV to the Boox Palma via ADB push.
The Palma connects as an MTP device (no drive letter), so standard file
copy is not possible — ADB is used instead.

USB debugging must be enabled on the device (Settings → Security →
Developer options → USB debugging).

Per-file push failures are captured in TransferResult.failed and do not
abort the transfer of remaining files.

Raises BooxNotConnectedError if ADB cannot reach the device.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

from orchestrator import config


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class BooxNotConnectedError(Exception):
    """Raised when ADB cannot reach the Boox Palma."""


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class TransferResult:
    """Outcome of a transfer_to_boox() call."""

    device_path: str                                       # remote directory
    copied: list[str] = field(default_factory=list)       # remote paths pushed
    failed: list[tuple[Path, str]] = field(default_factory=list)  # (src, error)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def transfer_to_boox(
    epub_paths: list[Path],
    csv_path: Path | None = None,
    rename_map: dict[Path, str] | None = None,
) -> TransferResult:
    """
    Push epub files and an optional library CSV to the Boox Palma via ADB.

    Files are pushed to config.BOOX_DEVICE_PATH on the device. If a file
    with the same name already exists it is overwritten. Per-file failures
    are captured in TransferResult.failed rather than raised, so one bad
    file does not abort the rest.

    Args:
        epub_paths:  Local epub files to push.
        csv_path:    Optional library CSV file to push alongside the epubs.
        rename_map:  Optional mapping of local epub Path → desired remote
                     filename (basename only). When provided, epub files found
                     in the map are pushed under the mapped name instead of
                     their local filename. The CSV is never renamed. Files not
                     in the map fall back to their local filename.

    Returns:
        TransferResult with device_path, pushed remote paths, and any
        per-file failures.

    Raises:
        BooxNotConnectedError: if ADB cannot reach the device.
    """
    adb = _adb_base()
    _check_connected(adb)

    device_path = config.BOOX_DEVICE_PATH
    result = TransferResult(device_path=device_path)

    sources: list[Path] = list(epub_paths)
    if csv_path is not None:
        sources.append(csv_path)

    for src in sources:
        dest_name = (rename_map or {}).get(src, src.name)
        remote = f"{device_path}/{dest_name}"
        try:
            _push_file(adb, src, remote)
            result.copied.append(remote)
        except OSError as exc:
            result.failed.append((src, str(exc)))

    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _adb_base() -> list[str]:
    """Return the base ADB command, with -s serial if configured."""
    cmd = [config.BOOX_ADB_CMD]
    if config.BOOX_DEVICE_SERIAL:
        cmd += ["-s", config.BOOX_DEVICE_SERIAL]
    return cmd


def _check_connected(adb: list[str]) -> None:
    """
    Verify the device is reachable via ADB.

    Raises BooxNotConnectedError if `adb get-state` does not return "device".
    """
    try:
        proc = subprocess.run(
            adb + ["get-state"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=_NO_WINDOW,
        )
    except subprocess.TimeoutExpired:
        raise BooxNotConnectedError(
            "ADB timed out checking device state. "
            "Ensure the device is connected and USB debugging is authorized."
        )
    except FileNotFoundError:
        raise BooxNotConnectedError(
            f"ADB executable not found: {config.BOOX_ADB_CMD!r}. "
            "Ensure ADB is installed and BOOX_ADB_CMD is correct."
        )

    if proc.returncode != 0 or proc.stdout.strip() != "device":
        detail = (proc.stderr or proc.stdout).strip()
        raise BooxNotConnectedError(
            f"Boox Palma not detected via ADB. "
            f"Check USB connection and that USB debugging is enabled. "
            f"ADB output: {detail!r}"
        )


def _push_file(adb: list[str], src: Path, remote: str) -> None:
    """
    Push a single local file to the device.

    Raises OSError on non-zero ADB exit so the caller can capture it.
    """
    proc = subprocess.run(
        adb + ["push", str(src), remote],
        capture_output=True,
        text=True,
        timeout=60,
        creationflags=_NO_WINDOW,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip()
        raise OSError(f"adb push failed: {detail}")
