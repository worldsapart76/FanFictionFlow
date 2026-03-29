"""
main.py — FanFictionFlow GUI (Milestone 10)

Entry point for the FanFictionFlow desktop application.

Design principle: the user clicks a button. Everything else is invisible.

Usage (Windows PowerShell):
    python main.py
"""

from __future__ import annotations

import datetime
import json
import re
import sys
import threading
import traceback
from pathlib import Path
from typing import Callable

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# ---------------------------------------------------------------------------
# Path bootstrap — ensure the project root is on sys.path when run as a
# top-level script (python main.py from the project root).
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from orchestrator import config
from orchestrator import credentials
from orchestrator.sync import calibre, diff, ao3
from orchestrator.normalize import ship as ship_module
from orchestrator.normalize import rules as rules_module
from orchestrator.normalize import review as review_module
from orchestrator.sync import metadata, readstatus as readstatus_module
from orchestrator.sync import browser as browser_module
from orchestrator.export import library_csv, boox_transfer


# ---------------------------------------------------------------------------
# Settings persistence
#
# A small JSON file stores user-adjustable runtime paths so the user doesn't
# have to re-select them on every launch.  Values override config.py defaults.
# ---------------------------------------------------------------------------

_SETTINGS_PATH = Path.home() / ".fanficflow" / "settings.json"
_LOG_PATH = Path.home() / ".fanficflow" / "last_run.log"
_STATE_PATH = Path.home() / ".fanficflow" / "sync_state.json"

_INVALID_FILENAME_CHARS = re.compile(r'[/\x00]')


def _calibre_epub_name(calibre_id: int, title: str) -> str:
    """Return the Calibre-style epub filename: '{calibre_id}-{title}.epub'.

    Matches the naming convention used by calibredb save-to-disk, which the
    CalibreFanFicBrowser Android app relies on to match epub files to library
    CSV rows by Calibre ID.
    """
    safe_title = _INVALID_FILENAME_CHARS.sub('-', title).strip()
    return f"{calibre_id}-{safe_title}.epub"


def _load_settings() -> dict:
    if _SETTINGS_PATH.exists():
        try:
            return json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_settings(settings: dict) -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_text(json.dumps(settings, indent=2), encoding="utf-8")


def _apply_settings(settings: dict) -> None:
    """Override config module attributes from saved settings at startup."""
    if "epub_download_dir" in settings:
        config.EPUB_DOWNLOAD_DIR = Path(settings["epub_download_dir"])


def _load_state() -> dict:
    if _STATE_PATH.exists():
        try:
            return json.loads(_STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_state(data: dict) -> None:
    # fresh_calibre_ids must be saved as a list (sets are not JSON-serialisable).
    _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main application window
# ---------------------------------------------------------------------------


class FanFictionFlowApp:
    """Main application window."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("FanFictionFlow")
        self.root.resizable(True, True)
        self.root.minsize(620, 420)

        self._settings = _load_settings()
        _apply_settings(self._settings)
        self._sync_running = False
        self._cancel_event = threading.Event()
        self._log_file: "open[str] | None" = None
        self._cancel_btns: list[ttk.Button] = []
        self._step_btns: list[ttk.Button] = []

        self._build_ui()

        # Route all unhandled tkinter callback exceptions to the log file so
        # they are not silently swallowed when running under pythonw.exe.
        self.root.report_callback_exception = self._report_tk_exception

    def _report_tk_exception(self, exc_type, exc_val, exc_tb) -> None:
        """Log unhandled tkinter callback exceptions to the log file."""
        msg = "".join(traceback.format_exception(exc_type, exc_val, exc_tb))
        self._log_line(f"[ERROR] Unhandled exception in UI callback:\n{msg}")
        messagebox.showerror(
            "FanFictionFlow Error",
            f"An unexpected error occurred:\n\n{exc_val}\n\n"
            "Full details written to last_run.log.",
        )

    # -----------------------------------------------------------------------
    # UI construction
    # -----------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        # Header: title + Settings button + status
        header = ttk.Frame(self.root, padding=(12, 10, 12, 4))
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(1, weight=1)

        ttk.Label(
            header, text="FanFictionFlow", font=("TkDefaultFont", 13, "bold")
        ).grid(row=0, column=0, sticky="w")

        ttk.Button(
            header, text="Settings…", command=self._on_settings
        ).grid(row=0, column=1, sticky="e", padx=(0, 10))

        self._status_var = tk.StringVar(value="Ready")
        self._status_label = ttk.Label(
            header, textvariable=self._status_var, foreground="gray"
        )
        self._status_label.grid(row=0, column=2, sticky="e")

        # Log area
        log_frame = ttk.Frame(self.root, padding=(12, 4, 12, 0))
        log_frame.grid(row=1, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self._log = scrolledtext.ScrolledText(
            log_frame,
            state="disabled",
            wrap="word",
            height=18,
            font=("Courier", 9),
        )
        self._log.grid(row=0, column=0, sticky="nsew")

        # Action area — notebook with Sync and Steps tabs
        notebook = ttk.Notebook(self.root)
        notebook.grid(row=2, column=0, sticky="ew", padx=12, pady=(8, 12))

        # --- Sync tab ---
        sync_tab = ttk.Frame(notebook, padding=(4, 6, 4, 6))
        notebook.add(sync_tab, text="Sync")

        self._sync_btn = ttk.Button(
            sync_tab, text="Start Sync", command=self._on_sync, width=18
        )
        self._sync_btn.grid(row=0, column=0, sticky="w")

        cancel_sync = ttk.Button(
            sync_tab, text="Cancel", command=self._on_cancel, state="disabled"
        )
        cancel_sync.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self._cancel_btns.append(cancel_sync)

        # --- Steps tab ---
        steps_tab = ttk.Frame(notebook, padding=(4, 6, 4, 6))
        notebook.add(steps_tab, text="Steps")

        step_defs = [
            ("Fetch & Diff",      self._on_step_fetch_diff),
            ("Download",          self._on_step_download),
            ("Import & Review",   self._on_step_import_review),
            ("Export CSV",        self._on_step_export_csv),
            ("Transfer to Boox",  self._on_step_boox_transfer),
            ("Sync Read Status",  self._on_step_sync_readstatus),
        ]
        for col, (label, cmd) in enumerate(step_defs):
            btn = ttk.Button(steps_tab, text=label, command=cmd)
            btn.grid(row=0, column=col, padx=(0 if col == 0 else 6, 0))
            self._step_btns.append(btn)

        cancel_steps = ttk.Button(
            steps_tab, text="Cancel", command=self._on_cancel, state="disabled"
        )
        cancel_steps.grid(row=0, column=len(step_defs), padx=(14, 0))
        self._cancel_btns.append(cancel_steps)

    # -----------------------------------------------------------------------
    # Logging / status helpers (thread-safe)
    # -----------------------------------------------------------------------

    def _log_line(self, text: str) -> None:
        """Append a line to the log and to the persistent log file."""
        if self._log_file is not None:
            try:
                self._log_file.write(text + "\n")
                self._log_file.flush()
            except Exception:
                pass

        def _append() -> None:
            self._log.configure(state="normal")
            self._log.insert("end", text + "\n")
            self._log.configure(state="disabled")
            self._log.see("end")
        self.root.after(0, _append)

    def _set_status(self, text: str, color: str = "gray") -> None:
        """Update the status label. Safe to call from any thread."""
        def _update() -> None:
            self._status_var.set(text)
            self._status_label.configure(foreground=color)
        self.root.after(0, _update)

    def _start_operation(
        self, status: str, *, clear_log: bool = False, truncate_log: bool = False
    ) -> None:
        """
        Common startup for any sync or step operation.
        Must be called from the main thread (button handler).
        """
        if clear_log:
            self._log.configure(state="normal")
            self._log.delete("1.0", "end")
            self._log.configure(state="disabled")

        self._sync_running = True
        self._cancel_event.clear()
        self._sync_btn.configure(state="disabled")
        for btn in self._step_btns:
            btn.configure(state="disabled")
        for btn in self._cancel_btns:
            btn.configure(state="normal")
        self._set_status(status, "steelblue")

        try:
            _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            mode = "w" if truncate_log else "a"
            self._log_file = _LOG_PATH.open(mode, encoding="utf-8")
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if truncate_log:
                self._log_file.write(f"FanFictionFlow — {ts}\n{'-' * 60}\n")
            else:
                self._log_file.write(f"\n--- {ts} ---\n")
            self._log_file.flush()
        except Exception:
            self._log_file = None

    # -----------------------------------------------------------------------
    # Settings dialog
    # -----------------------------------------------------------------------

    def _on_settings(self) -> None:
        SettingsDialog(
            self.root,
            settings=self._settings,
            on_save=self._on_settings_saved,
        )

    def _on_settings_saved(self, settings: dict) -> None:
        self._settings = settings
        _save_settings(settings)
        _apply_settings(settings)
        self._log_line("[Settings saved]")

    # -----------------------------------------------------------------------
    # Sync — entry point
    # -----------------------------------------------------------------------

    def _on_sync(self) -> None:
        if self._sync_running:
            return

        marked_csv = self._resolve_marked_for_later()
        if marked_csv is None:
            return

        self._start_operation("Syncing…", clear_log=True, truncate_log=True)

        threading.Thread(
            target=self._phase1_background,
            args=(marked_csv,),
            daemon=True,
        ).start()

    def _resolve_marked_for_later(self) -> Path | None:
        """
        Return the path to marked_for_later.csv.

        Uses the saved setting if the file still exists there; otherwise
        opens a file-picker so the user can locate the export.
        """
        saved = self._settings.get("marked_for_later_path")
        if saved and Path(saved).exists():
            return Path(saved)

        path_str = filedialog.askopenfilename(
            title="Select marked_for_later.csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path_str:
            self._log_line("Sync cancelled: no CSV selected.")
            return None

        p = Path(path_str)
        self._settings["marked_for_later_path"] = str(p)
        _save_settings(self._settings)
        return p

    def _on_cancel(self) -> None:
        """Signal the background thread to stop after the current download."""
        self._cancel_event.set()
        for btn in self._cancel_btns:
            btn.configure(state="disabled")
        self._set_status("Cancelling…", "orange")
        self._log_line("Cancel requested — finishing current download then stopping.")

    def _finish_sync(self, success: bool = False) -> None:
        """Re-enable all action buttons. Called from any thread."""
        if self._log_file is not None:
            try:
                self._log_file.close()
            except Exception:
                pass
            self._log_file = None

        def _reset() -> None:
            self._sync_btn.configure(state="normal")
            for btn in self._step_btns:
                btn.configure(state="normal")
            for btn in self._cancel_btns:
                btn.configure(state="disabled")
            self._sync_running = False
            if not success:
                self._set_status("Ready", "gray")
        self.root.after(0, _reset)

    # -----------------------------------------------------------------------
    # Phase 1 (background thread): fetch → diff → download → import → normalise
    # -----------------------------------------------------------------------

    def _phase1_background(self, marked_csv: Path) -> None:
        try:
            # Step 1 — Calibre GUI check
            self._log_line("Checking Calibre status…")
            if calibre.is_gui_open():
                self.root.after(0, lambda: messagebox.showwarning(
                    "Calibre Is Open",
                    "Calibre GUI is running. Close it before syncing.\n\n"
                    "calibredb cannot run while the Calibre GUI is open.",
                ))
                self._log_line("Aborted: Calibre GUI is open.")
                self._finish_sync()
                return

            # Step 2 — Credentials check (warn only; downloads will fail later if missing)
            if not credentials.has_ao3_credentials():
                self._log_line(
                    "Warning: No AO3 credentials found. "
                    "Downloads requiring login will fail. "
                    "Add credentials in Settings."
                )

            # Step 3 — Fetch Calibre library
            self._log_line("Fetching Calibre library…")
            library = calibre.fetch_library()
            self._log_line(f"  {len(library)} books in library.")

            # Step 4 — Diff
            self._log_line(f"Parsing {marked_csv.name}…")
            new_stories = diff.get_new_stories(marked_csv, library)
            if not new_stories:
                self._log_line("No new stories. Library is up to date.")
                self._set_status("Up to date", "green")
                self._finish_sync(success=True)
                return
            self._log_line(f"Found {len(new_stories)} new story/stories to import.")
            _save_state({"new_stories": new_stories})

            # Step 5 — Download epubs
            epub_dir = config.EPUB_DOWNLOAD_DIR
            epub_dir.mkdir(parents=True, exist_ok=True)

            # Pre-check: identify stories whose epubs are already in the folder.
            already_present: list[ao3.DownloadResult] = []
            need_download: list[dict] = []
            for story in new_stories:
                existing = ao3.find_existing_epub(story["ao3_work_id"], epub_dir)
                if existing is not None:
                    already_present.append(
                        ao3.DownloadResult(story=story, epub_path=existing, skipped=True)
                    )
                else:
                    need_download.append(story)

            if already_present:
                self._log_line(
                    f"  {len(already_present)} epub(s) already in download folder:"
                )
                for r in already_present:
                    title = r.story.get("title") or r.story["ao3_work_id"]
                    self._log_line(f"    Already downloaded: {title!r}")

            n_to_dl = len(need_download)
            fresh_results: list[ao3.DownloadResult] = []

            if n_to_dl:
                self._log_line(f"  Downloading {n_to_dl} new epub(s) to: {epub_dir}")
                self._set_status(f"Downloading 0/{n_to_dl}…", "steelblue")

                _dl_ok = [0]
                _dl_fail = [0]

                def _dl_status(msg: str) -> None:
                    self._log_line(msg)

                def _dl_progress(result: ao3.DownloadResult) -> None:
                    if result.success:
                        _dl_ok[0] += 1
                    else:
                        _dl_fail[0] += 1
                    done = _dl_ok[0] + _dl_fail[0]
                    self._set_status(
                        f"Downloading {done}/{n_to_dl}"
                        f" — {_dl_ok[0]} ok, {_dl_fail[0]} failed",
                        "steelblue",
                    )
                    self._on_download_progress(result)

                fresh_results = ao3.download_stories(
                    need_download,
                    output_dir=epub_dir,
                    progress_callback=_dl_progress,
                    cancel_event=self._cancel_event,
                    status_callback=_dl_status,
                )
            else:
                self._log_line("  All epubs already present — skipping download step.")

            download_results = already_present + fresh_results
            successful_dl = ao3.successful_downloads(download_results)
            failed_dl = ao3.failed_downloads(download_results)

            # Summary line.
            fresh_ok = [r for r in fresh_results if r.success]
            summary = (
                f"Downloads complete: {len(fresh_ok)} downloaded, "
                f"{len(already_present)} already present, "
                f"{len(failed_dl)} failed"
            )
            if self._cancel_event.is_set() and len(fresh_results) < n_to_dl:
                summary += f" ({n_to_dl - len(fresh_results)} skipped by cancel)"
            self._log_line(summary)

            if failed_dl:
                self._log_line("  Failed downloads:")
                for r in failed_dl:
                    title = r.story.get("title") or r.story["ao3_work_id"]
                    self._log_line(f"    - {title!r}: {r.error}")

            if self._cancel_event.is_set() and not successful_dl:
                self._log_line("Cancelled with no successful downloads. Nothing imported.")
                self._set_status("Cancelled", "orange")
                self._finish_sync()
                return

            if not successful_dl:
                self._log_line("No stories downloaded successfully. Nothing to import.")
                self._finish_sync()
                return

            # Step 6 — Import to Calibre
            self._log_line(f"Importing {len(successful_dl)} epub(s) to Calibre…")
            imports: list[tuple[int, dict]] = []
            fresh_calibre_ids: set[int] = set()  # IDs where calibredb created a new record
            for result in successful_dl:
                try:
                    calibre_id, is_fresh = calibre.add_book(result.epub_path)
                    imports.append((calibre_id, result.story))
                    if is_fresh:
                        fresh_calibre_ids.add(calibre_id)
                    title = result.story.get("title") or result.story["ao3_work_id"]
                    verb = "Imported" if is_fresh else "Found existing"
                    self._log_line(f"  {verb}: {title!r} → Calibre ID {calibre_id}")
                except Exception as exc:
                    self._log_line(
                        f"  Import failed for {result.epub_path.name}: {exc}"
                    )

            if not imports:
                self._log_line("No books imported successfully.")
                self._finish_sync()
                return

            _save_state({
                "new_stories": new_stories,
                "imports": [[cid, s] for cid, s in imports],
                "fresh_calibre_ids": list(fresh_calibre_ids),
            })

            # Step 7 — Normalise metadata
            self._log_line("Normalising metadata…")
            existing_ships = calibre.fetch_existing_ship_values()
            existing_collections = sorted({
                (book.get("#collection") or "").strip()
                for book in library
                if (book.get("#collection") or "").strip()
            })

            stories_only = [story for _, story in imports]
            ship_results = ship_module.normalize_stories(
                stories_only, existing_ships=existing_ships
            )
            collection_results = rules_module.normalize_stories_collection(stories_only)

            queue = review_module.build_review_queue(ship_results, collection_results)

            n_auto = len(review_module.auto_rows(queue))
            n_flagged = len(review_module.flagged_rows(queue))
            self._log_line(
                f"  Normalisation: {n_auto} auto-resolved, "
                f"{n_flagged} flagged for review."
            )

            epub_paths = [r.epub_path for r in successful_dl]

            # Hand off to main thread.  If there were failed downloads, show
            # the browser opener dialog first, then proceed to the review queue.
            def _show_rq() -> None:
                self._show_review_queue(
                    queue, imports, epub_paths, existing_ships, existing_collections,
                    fresh_calibre_ids,
                )

            if failed_dl:
                self.root.after(
                    0, lambda: self._show_failed_downloads(failed_dl, on_done=_show_rq)
                )
            else:
                self.root.after(0, _show_rq)

        except Exception as exc:
            self._log_line(f"Error during sync: {exc}")
            self._log_line(traceback.format_exc())
            self._set_status("Error", "red")
            self._finish_sync()

    def _on_download_progress(self, result: ao3.DownloadResult) -> None:
        title = result.story.get("title") or result.story["ao3_work_id"]
        if result.skipped:
            self._log_line(f"  Skipped (already downloaded): {title!r}")
        elif result.success:
            self._log_line(f"  Downloaded: {title!r}")
        else:
            self._log_line(f"  Failed:     {title!r} — {result.error}")

    # -----------------------------------------------------------------------
    # Steps tab — individual step handlers
    # -----------------------------------------------------------------------

    def _on_step_fetch_diff(self) -> None:
        if self._sync_running:
            return
        marked_csv = self._resolve_marked_for_later()
        if marked_csv is None:
            return
        self._start_operation("Fetching & diffing…")
        threading.Thread(
            target=self._step_fetch_diff_bg, args=(marked_csv,), daemon=True
        ).start()

    def _step_fetch_diff_bg(self, marked_csv: Path) -> None:
        try:
            self._log_line("Checking Calibre status…")
            if calibre.is_gui_open():
                self.root.after(0, lambda: messagebox.showwarning(
                    "Calibre Is Open",
                    "Calibre GUI is running. Close it before syncing.\n\n"
                    "calibredb cannot run while the Calibre GUI is open.",
                ))
                self._log_line("Aborted: Calibre GUI is open.")
                self._finish_sync()
                return

            self._log_line("Fetching Calibre library…")
            library = calibre.fetch_library()
            self._log_line(f"  {len(library)} books in library.")

            self._log_line(f"Parsing {marked_csv.name}…")
            new_stories = diff.get_new_stories(marked_csv, library)
            if not new_stories:
                self._log_line("No new stories. Library is up to date.")
                self._set_status("Up to date", "green")
                self._finish_sync(success=True)
                return

            self._log_line(f"Found {len(new_stories)} new story/stories to import.")
            _save_state({"new_stories": new_stories})
            self._log_line("  State saved — run 'Download' to fetch epubs.")
            self._set_status("Fetch complete", "green")
            self._finish_sync(success=True)

        except Exception as exc:
            self._log_line(f"Error during fetch & diff: {exc}")
            self._log_line(traceback.format_exc())
            self._set_status("Error", "red")
            self._finish_sync()

    def _on_step_download(self) -> None:
        if self._sync_running:
            return
        state = _load_state()
        if not state.get("new_stories"):
            messagebox.showinfo(
                "No Stories Queued",
                "Run 'Fetch & Diff' first to identify new stories.",
            )
            return
        self._start_operation("Downloading…")
        threading.Thread(
            target=self._step_download_bg,
            args=(state["new_stories"],),
            daemon=True,
        ).start()

    def _step_download_bg(self, new_stories: list) -> None:
        try:
            epub_dir = config.EPUB_DOWNLOAD_DIR
            epub_dir.mkdir(parents=True, exist_ok=True)

            already_present: list[ao3.DownloadResult] = []
            need_download: list[dict] = []
            for story in new_stories:
                existing = ao3.find_existing_epub(story["ao3_work_id"], epub_dir)
                if existing is not None:
                    already_present.append(
                        ao3.DownloadResult(story=story, epub_path=existing, skipped=True)
                    )
                else:
                    need_download.append(story)

            if already_present:
                self._log_line(
                    f"  {len(already_present)} epub(s) already in download folder:"
                )
                for r in already_present:
                    title = r.story.get("title") or r.story["ao3_work_id"]
                    self._log_line(f"    Already downloaded: {title!r}")

            n_to_dl = len(need_download)
            fresh_results: list[ao3.DownloadResult] = []

            if n_to_dl:
                self._log_line(f"  Downloading {n_to_dl} new epub(s) to: {epub_dir}")
                self._set_status(f"Downloading 0/{n_to_dl}…", "steelblue")

                _dl_ok = [0]
                _dl_fail = [0]

                def _dl_status(msg: str) -> None:
                    self._log_line(msg)

                def _dl_progress(result: ao3.DownloadResult) -> None:
                    if result.success:
                        _dl_ok[0] += 1
                    else:
                        _dl_fail[0] += 1
                    done = _dl_ok[0] + _dl_fail[0]
                    self._set_status(
                        f"Downloading {done}/{n_to_dl}"
                        f" — {_dl_ok[0]} ok, {_dl_fail[0]} failed",
                        "steelblue",
                    )
                    self._on_download_progress(result)

                fresh_results = ao3.download_stories(
                    need_download,
                    output_dir=epub_dir,
                    progress_callback=_dl_progress,
                    cancel_event=self._cancel_event,
                    status_callback=_dl_status,
                )
            else:
                self._log_line("  All epubs already present — skipping download step.")

            download_results = already_present + fresh_results
            failed_dl = ao3.failed_downloads(download_results)
            fresh_ok = [r for r in fresh_results if r.success]

            summary = (
                f"Downloads complete: {len(fresh_ok)} downloaded, "
                f"{len(already_present)} already present, "
                f"{len(failed_dl)} failed"
            )
            if self._cancel_event.is_set() and len(fresh_results) < n_to_dl:
                summary += f" ({n_to_dl - len(fresh_results)} skipped by cancel)"
            self._log_line(summary)

            if failed_dl:
                self._log_line("  Failed downloads:")
                for r in failed_dl:
                    title = r.story.get("title") or r.story["ao3_work_id"]
                    self._log_line(f"    - {title!r}: {r.error}")

            # Capture cancel state now — before any dialog interaction changes it.
            cancelled = self._cancel_event.is_set()

            def _after_dialog() -> None:
                self._set_status("Cancelled" if cancelled else "Download complete",
                                 "orange" if cancelled else "green")
                self._finish_sync(success=not cancelled)

            if failed_dl:
                self.root.after(
                    0, lambda: self._show_failed_downloads(failed_dl, on_done=_after_dialog)
                )
            else:
                self.root.after(0, _after_dialog)

        except Exception as exc:
            self._log_line(f"Error during download: {exc}")
            self._log_line(traceback.format_exc())
            self._set_status("Error", "red")
            self._finish_sync()

    def _on_step_import_review(self) -> None:
        if self._sync_running:
            return
        state = _load_state()
        if not state.get("new_stories"):
            messagebox.showinfo(
                "No Stories Queued",
                "Run 'Fetch & Diff' first to identify new stories.",
            )
            return
        self._start_operation("Importing…")
        threading.Thread(
            target=self._step_import_review_bg,
            args=(state["new_stories"],),
            daemon=True,
        ).start()

    def _step_import_review_bg(self, new_stories: list) -> None:
        try:
            epub_dir = config.EPUB_DOWNLOAD_DIR

            # Find epubs already in the download folder for each story.
            successful_dl: list[ao3.DownloadResult] = []
            for story in new_stories:
                epub = ao3.find_existing_epub(story["ao3_work_id"], epub_dir)
                if epub is not None:
                    successful_dl.append(ao3.DownloadResult(story=story, epub_path=epub))
                else:
                    title = story.get("title") or story["ao3_work_id"]
                    self._log_line(f"  No epub found for {title!r} — skipping import")

            if not successful_dl:
                self._log_line(
                    "No epubs found in download directory. Run 'Download' first."
                )
                self._finish_sync()
                return

            # Fetch fresh library data for normalisation.
            library = calibre.fetch_library()
            existing_ships = calibre.fetch_existing_ship_values()
            existing_collections = sorted({
                (book.get("#collection") or "").strip()
                for book in library
                if (book.get("#collection") or "").strip()
            })

            # Import epubs to Calibre.
            self._log_line(f"Importing {len(successful_dl)} epub(s) to Calibre…")
            imports: list[tuple[int, dict]] = []
            fresh_calibre_ids: set[int] = set()
            for result in successful_dl:
                try:
                    calibre_id, is_fresh = calibre.add_book(result.epub_path)
                    imports.append((calibre_id, result.story))
                    if is_fresh:
                        fresh_calibre_ids.add(calibre_id)
                    title = result.story.get("title") or result.story["ao3_work_id"]
                    verb = "Imported" if is_fresh else "Found existing"
                    self._log_line(f"  {verb}: {title!r} → Calibre ID {calibre_id}")
                except Exception as exc:
                    self._log_line(
                        f"  Import failed for {result.epub_path.name}: {exc}"
                    )

            if not imports:
                self._log_line("No books imported successfully.")
                self._finish_sync()
                return

            _save_state({
                "new_stories": new_stories,
                "imports": [[cid, s] for cid, s in imports],
                "fresh_calibre_ids": list(fresh_calibre_ids),
            })

            # Normalise metadata.
            self._log_line("Normalising metadata…")
            stories_only = [story for _, story in imports]
            ship_results = ship_module.normalize_stories(
                stories_only, existing_ships=existing_ships
            )
            collection_results = rules_module.normalize_stories_collection(stories_only)
            queue = review_module.build_review_queue(ship_results, collection_results)

            n_auto = len(review_module.auto_rows(queue))
            n_flagged = len(review_module.flagged_rows(queue))
            self._log_line(
                f"  Normalisation: {n_auto} auto-resolved, "
                f"{n_flagged} flagged for review."
            )

            epub_paths = [r.epub_path for r in successful_dl]

            # Hand off to the review queue dialog (same as full sync).
            self.root.after(
                0,
                lambda: self._show_review_queue(
                    queue, imports, epub_paths, existing_ships, existing_collections,
                    fresh_calibre_ids,
                ),
            )

        except Exception as exc:
            self._log_line(f"Error during import: {exc}")
            self._log_line(traceback.format_exc())
            self._set_status("Error", "red")
            self._finish_sync()

    def _on_step_export_csv(self) -> None:
        if self._sync_running:
            return
        self._start_operation("Exporting CSV…")
        threading.Thread(target=self._step_export_csv_bg, daemon=True).start()

    def _step_export_csv_bg(self) -> None:
        try:
            self._log_line("Exporting library CSV…")
            csv_path = library_csv.export_library_csv()
            self._log_line(f"  CSV exported: {csv_path}")
            self._set_status("CSV exported", "green")
            self._finish_sync(success=True)
        except Exception as exc:
            self._log_line(f"  CSV export failed: {exc}")
            self._log_line(traceback.format_exc())
            self._set_status("Error", "red")
            self._finish_sync()

    def _on_step_boox_transfer(self) -> None:
        if self._sync_running:
            return
        self._start_operation("Transferring to Boox…")
        threading.Thread(target=self._step_boox_transfer_bg, daemon=True).start()

    def _step_boox_transfer_bg(self) -> None:
        try:
            self._log_line("Checking for Boox Palma…")
            epub_dir = config.EPUB_DOWNLOAD_DIR
            epub_paths = sorted(epub_dir.glob("*.epub")) if epub_dir.exists() else []
            csv_path = library_csv.find_latest_csv()
            if not epub_paths and csv_path is None:
                self._log_line(
                    "  Nothing to transfer (no epubs in download dir, no CSV found)."
                )
                self._finish_sync()
                return

            # Build rename map: FanFicFare names → Calibre names so the
            # Android app can match files to the library CSV by Calibre ID.
            rename_map: dict[Path, str] = {}
            if epub_paths:
                self._log_line("  Looking up Calibre IDs for epub rename…")
                try:
                    library = calibre.fetch_library()
                    ao3_to_book = {
                        str(book["#ao3_work_id"]): book
                        for book in library
                        if book.get("#ao3_work_id")
                    }
                    for epub_path in epub_paths:
                        m = re.search(r'ao3_(\d+)', epub_path.stem)
                        if m:
                            book = ao3_to_book.get(m.group(1))
                            if book and book.get("id"):
                                rename_map[epub_path] = _calibre_epub_name(
                                    int(book["id"]),
                                    book.get("title") or str(book["id"]),
                                )
                except Exception as exc:
                    self._log_line(
                        f"  Warning: Calibre lookup failed, using original filenames: {exc}"
                    )

            transfer_result = boox_transfer.transfer_to_boox(
                epub_paths, csv_path=csv_path, rename_map=rename_map
            )
            self._log_line(
                f"  Boox: {len(transfer_result.copied)} file(s) pushed."
            )
            for src, err in transfer_result.failed:
                self._log_line(f"  Transfer failed: {src} — {err}")
            self._set_status("Transfer complete", "green")
            self._finish_sync(success=True)
        except boox_transfer.BooxNotConnectedError:
            self._log_line("  Boox not connected — device not found.")
            self._finish_sync()
        except Exception as exc:
            self._log_line(f"  Boox transfer error: {exc}")
            self._log_line(traceback.format_exc())
            self._set_status("Error", "red")
            self._finish_sync()

    def _on_step_sync_readstatus(self) -> None:
        if self._sync_running:
            return
        path = self._resolve_palma_readstatus()
        if path is None:
            return
        self._start_operation("Syncing read status…")
        threading.Thread(
            target=self._step_sync_readstatus_bg, args=(path,), daemon=True
        ).start()

    def _step_sync_readstatus_bg(self, path: Path) -> None:
        try:
            self._log_line(f"Applying Palma read status overrides from: {path.name}")
            rs_result = readstatus_module.sync_readstatus_from_palma(path)
            self._log_line(
                f"  {len(rs_result.updated)} updated, "
                f"{len(rs_result.skipped)} already matched, "
                f"{len(rs_result.failed)} failed."
            )
            for cid, err in rs_result.failed:
                self._log_line(f"  Failed id={cid}: {err}")
            self._set_status("Read status sync complete", "green")
            curation = browser_module.curation_needed(rs_result)
            if curation:
                self.root.after(
                    0,
                    lambda: self._show_curation_dialog(
                        rs_result, on_done=lambda: self._finish_sync(success=True)
                    ),
                )
            else:
                self._finish_sync(success=True)
        except Exception as exc:
            self._log_line(f"Read status sync error: {exc}")
            self._log_line(traceback.format_exc())
            self._set_status("Error", "red")
            self._finish_sync()

    def _resolve_palma_readstatus(self) -> Path | None:
        """
        Return the path to the Palma read status override CSV.

        Uses the saved setting if the file still exists there; otherwise
        opens a file-picker so the user can locate the export.
        """
        saved = self._settings.get("palma_readstatus_path")
        if saved and Path(saved).exists():
            return Path(saved)

        path_str = filedialog.askopenfilename(
            title="Select Palma read status CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path_str:
            self._log_line("Read status sync cancelled: no file selected.")
            return None

        p = Path(path_str)
        self._settings["palma_readstatus_path"] = str(p)
        _save_settings(self._settings)
        return p

    # -----------------------------------------------------------------------
    # Browser opener helpers (main thread)
    # -----------------------------------------------------------------------

    def _show_failed_downloads(self, failed_dl: list, on_done: Callable) -> None:
        """Show the FailedDownloadsDialog on the main thread, then call on_done."""
        try:
            def _on_open() -> None:
                self._log_line(
                    f"Opening {len(failed_dl)} "
                    f"{'story' if len(failed_dl) == 1 else 'stories'} in browser…"
                )
                browser_module.open_failed_in_browser(failed_dl)
                on_done()

            def _on_skip() -> None:
                self._log_line("Skipped browser opener for failed downloads.")
                on_done()

            FailedDownloadsDialog(
                self.root, failed=failed_dl, on_open=_on_open, on_skip=_on_skip,
            )
        except Exception as exc:
            self._log_line(f"[ERROR] Failed downloads dialog error: {exc}")
            self._log_line(traceback.format_exc())
            on_done()

    def _show_curation_dialog(self, rs_result, on_done: Callable) -> None:
        """Show the AO3CurationDialog on the main thread, then call on_done."""
        try:
            n = len(browser_module.curation_needed(rs_result))

            def _on_open() -> None:
                self._log_line(
                    f"Opening {n} {'story' if n == 1 else 'stories'} "
                    "in browser for AO3 curation…"
                )
                browser_module.open_curation_in_browser(rs_result)
                on_done()

            def _on_skip() -> None:
                self._log_line("Skipped AO3 curation browser opener.")
                on_done()

            AO3CurationDialog(
                self.root, rs_result=rs_result, on_open=_on_open, on_skip=_on_skip,
            )
        except Exception as exc:
            self._log_line(f"[ERROR] AO3 curation dialog error: {exc}")
            self._log_line(traceback.format_exc())
            on_done()

    # -----------------------------------------------------------------------
    # Review queue (main thread)
    # -----------------------------------------------------------------------

    def _show_review_queue(
        self,
        queue: list,
        imports: list[tuple[int, dict]],
        epub_paths: list[Path],
        existing_ships: list[str],
        existing_collections: list[str],
        fresh_calibre_ids: set[int],
    ) -> None:
        try:
            ReviewQueueDialog(
                self.root,
                queue=queue,
                existing_ships=existing_ships,
                existing_collections=existing_collections,
                on_confirm=lambda q: self._on_review_confirmed(
                    q, imports, epub_paths, fresh_calibre_ids
                ),
                on_cancel=self._on_review_cancelled,
            )
        except Exception as exc:
            self._log_line(f"[ERROR] Failed to open review queue: {exc}")
            self._log_line(traceback.format_exc())
            messagebox.showerror(
                "Review Queue Error",
                f"Failed to open the review queue:\n\n{exc}\n\n"
                "Full details written to last_run.log.",
            )
            self._finish_sync()

    def _on_review_cancelled(self) -> None:
        self._log_line("Review cancelled. No changes written to Calibre.")
        self._set_status("Cancelled", "orange")
        self._finish_sync()

    def _on_review_confirmed(
        self,
        queue: list,
        imports: list[tuple[int, dict]],
        epub_paths: list[Path],
        fresh_calibre_ids: set[int],
    ) -> None:
        self._log_line("Review confirmed. Writing metadata to Calibre…")
        threading.Thread(
            target=self._phase2_background,
            args=(queue, imports, epub_paths, fresh_calibre_ids),
            daemon=True,
        ).start()

    # -----------------------------------------------------------------------
    # Phase 2 (background thread): write metadata → export CSV → Boox transfer
    # -----------------------------------------------------------------------

    def _phase2_background(
        self,
        queue: list,
        imports: list[tuple[int, dict]],
        epub_paths: list[Path],
        fresh_calibre_ids: set[int],
    ) -> None:
        try:
            confirmed = review_module.get_confirmed_stories(queue)

            # Step 8 — Write metadata to Calibre.
            # Only write #readstatus for genuinely new books (fresh_calibre_ids)
            # to avoid overwriting statuses on books that already existed.
            confirmed_imports = [
                (calibre_id, confirmed_story)
                for (calibre_id, _), confirmed_story in zip(imports, confirmed)
            ]
            meta_results = metadata.write_all_metadata(
                confirmed_imports, fresh_ids=fresh_calibre_ids
            )
            ok_meta = metadata.successful_writes(meta_results)
            failed_meta = metadata.failed_writes(meta_results)
            self._log_line(
                f"Metadata written: {len(ok_meta)} ok, {len(failed_meta)} failed."
            )
            for r in failed_meta:
                title = r.story.get("title") or "?"
                self._log_line(f"  Metadata failed for {title!r}: {r.error}")

            # Step 7 — Apply Palma read status overrides (if file is configured)
            rs_result = None
            palma_csv_path = self._settings.get("palma_readstatus_path")
            if palma_csv_path and Path(palma_csv_path).exists():
                self._log_line("Applying Palma read status overrides…")
                try:
                    rs_result = readstatus_module.sync_readstatus_from_palma(
                        Path(palma_csv_path)
                    )
                    self._log_line(
                        f"  Read status: {len(rs_result.updated)} updated, "
                        f"{len(rs_result.skipped)} already matched, "
                        f"{len(rs_result.failed)} failed."
                    )
                    for cid, err in rs_result.failed:
                        self._log_line(f"  Failed id={cid}: {err}")
                except Exception as exc:
                    self._log_line(f"  Read status override error: {exc}")

            # Step 9 — Export library CSV
            self._log_line("Exporting library CSV…")
            csv_path: Path | None = None
            try:
                csv_path = library_csv.export_library_csv()
                self._log_line(f"  CSV exported: {csv_path}")
            except Exception as exc:
                self._log_line(f"  CSV export failed: {exc}")

            # Step 10 — Transfer to Boox Palma (skip gracefully if not connected)
            # Build rename map: FanFicFare names (title-ao3_NNNN.epub) →
            # Calibre names ({calibre_id}-{title}.epub) so the Android app
            # can match files to the library CSV by Calibre ID.
            _work_id_to_import = {
                story.get("ao3_work_id"): (cid, story)
                for cid, story in imports
                if story.get("ao3_work_id")
            }
            rename_map: dict[Path, str] = {}
            for epub_path in epub_paths:
                m = re.search(r'ao3_(\d+)', epub_path.stem)
                if m:
                    entry = _work_id_to_import.get(m.group(1))
                    if entry:
                        cid, story = entry
                        rename_map[epub_path] = _calibre_epub_name(
                            cid, story.get("title") or str(cid)
                        )

            self._log_line("Checking for Boox Palma…")
            try:
                transfer_result = boox_transfer.transfer_to_boox(
                    epub_paths,
                    csv_path=csv_path,
                    rename_map=rename_map,
                )
                self._log_line(
                    f"  Boox: {len(transfer_result.copied)} file(s) pushed."
                )
                for src, err in transfer_result.failed:
                    self._log_line(f"  Transfer failed: {src.name} — {err}")
            except boox_transfer.BooxNotConnectedError:
                self._log_line("  Boox not connected — skipping device transfer.")
            except Exception as exc:
                self._log_line(f"  Boox transfer error: {exc}")

            self._log_line("")
            self._log_line("Sync complete.")
            self._set_status("Sync complete", "green")
            curation = browser_module.curation_needed(rs_result) if rs_result else []
            if curation:
                self.root.after(
                    0,
                    lambda: self._show_curation_dialog(
                        rs_result, on_done=lambda: self._finish_sync(success=True)
                    ),
                )
            else:
                self._finish_sync(success=True)

        except Exception as exc:
            self._log_line(f"Error writing metadata: {exc}")
            self._log_line(traceback.format_exc())
            self._set_status("Error", "red")
            self._finish_sync()


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------


class SettingsDialog(tk.Toplevel):
    """Settings dialog: AO3 credentials and runtime paths."""

    def __init__(
        self,
        parent: tk.Tk,
        settings: dict,
        on_save: Callable[[dict], None],
    ) -> None:
        super().__init__(parent)
        self.title("Settings")
        self.resizable(False, False)
        self.grab_set()
        self.transient(parent)

        self._settings = dict(settings)
        self._on_save = on_save
        self._build_ui()
        self._load_values()
        self.wait_visibility()
        self.focus_set()

    def _build_ui(self) -> None:
        frame = ttk.Frame(self, padding=16)
        frame.grid(sticky="nsew")
        frame.columnconfigure(1, weight=1)
        row = 0

        # AO3 Credentials
        ttk.Label(
            frame, text="AO3 Credentials", font=("TkDefaultFont", 10, "bold")
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 6))
        row += 1

        ttk.Label(frame, text="Username:").grid(row=row, column=0, sticky="w", pady=3)
        self._username_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self._username_var, width=32).grid(
            row=row, column=1, columnspan=2, sticky="ew", padx=(8, 0)
        )
        row += 1

        ttk.Label(frame, text="Password:").grid(row=row, column=0, sticky="w", pady=3)
        self._password_var = tk.StringVar()
        ttk.Entry(
            frame, textvariable=self._password_var, show="•", width=32
        ).grid(row=row, column=1, columnspan=2, sticky="ew", padx=(8, 0))
        row += 1

        ttk.Separator(frame, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=10
        )
        row += 1

        # Paths
        ttk.Label(
            frame, text="Paths", font=("TkDefaultFont", 10, "bold")
        ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 6))
        row += 1

        ttk.Label(frame, text="Marked for Later CSV:").grid(
            row=row, column=0, sticky="w", pady=3
        )
        self._csv_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self._csv_var, width=38).grid(
            row=row, column=1, sticky="ew", padx=(8, 4)
        )
        ttk.Button(frame, text="Browse…", command=self._browse_csv).grid(
            row=row, column=2, sticky="w"
        )
        row += 1

        ttk.Label(frame, text="Epub Download Dir:").grid(
            row=row, column=0, sticky="w", pady=3
        )
        self._epub_dir_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self._epub_dir_var, width=38).grid(
            row=row, column=1, sticky="ew", padx=(8, 4)
        )
        ttk.Button(frame, text="Browse…", command=self._browse_epub_dir).grid(
            row=row, column=2, sticky="w"
        )
        row += 1

        ttk.Label(frame, text="Palma Read Status CSV:").grid(
            row=row, column=0, sticky="w", pady=3
        )
        self._palma_csv_var = tk.StringVar()
        ttk.Entry(frame, textvariable=self._palma_csv_var, width=38).grid(
            row=row, column=1, sticky="ew", padx=(8, 4)
        )
        ttk.Button(frame, text="Browse…", command=self._browse_palma_csv).grid(
            row=row, column=2, sticky="w"
        )
        row += 1

        ttk.Separator(frame, orient="horizontal").grid(
            row=row, column=0, columnspan=3, sticky="ew", pady=10
        )
        row += 1

        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=row, column=0, columnspan=3, sticky="e")
        ttk.Button(btn_frame, text="Cancel", command=self.destroy).grid(
            row=0, column=0, padx=(0, 8)
        )
        ttk.Button(btn_frame, text="Save", command=self._save).grid(row=0, column=1)

    def _load_values(self) -> None:
        creds = credentials.read_ao3_credentials()
        if creds:
            self._username_var.set(creds[0])
            self._password_var.set(creds[1])
        if "marked_for_later_path" in self._settings:
            self._csv_var.set(self._settings["marked_for_later_path"])
        epub_dir = self._settings.get(
            "epub_download_dir", str(config.EPUB_DOWNLOAD_DIR)
        )
        self._epub_dir_var.set(epub_dir)
        if "palma_readstatus_path" in self._settings:
            self._palma_csv_var.set(self._settings["palma_readstatus_path"])

    def _browse_csv(self) -> None:
        path = filedialog.askopenfilename(
            title="Select marked_for_later.csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            parent=self,
        )
        if path:
            self._csv_var.set(path)

    def _browse_palma_csv(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Palma read status CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            parent=self,
        )
        if path:
            self._palma_csv_var.set(path)

    def _browse_epub_dir(self) -> None:
        path = filedialog.askdirectory(
            title="Select epub download directory",
            parent=self,
        )
        if path:
            self._epub_dir_var.set(path)

    def _save(self) -> None:
        username = self._username_var.get().strip()
        password = self._password_var.get().strip()
        if username and password:
            credentials.write_ao3_credentials(username, password)
        elif username or password:
            messagebox.showwarning(
                "Incomplete Credentials",
                "Both username and password are required. Credentials not saved.",
                parent=self,
            )

        csv_path = self._csv_var.get().strip()
        if csv_path:
            self._settings["marked_for_later_path"] = csv_path

        epub_dir = self._epub_dir_var.get().strip()
        if epub_dir:
            self._settings["epub_download_dir"] = epub_dir

        palma_csv = self._palma_csv_var.get().strip()
        if palma_csv:
            self._settings["palma_readstatus_path"] = palma_csv
        else:
            self._settings.pop("palma_readstatus_path", None)

        self._on_save(self._settings)
        self.destroy()


# ---------------------------------------------------------------------------
# Failed downloads dialog
# ---------------------------------------------------------------------------


class FailedDownloadsDialog(tk.Toplevel):
    """
    Modal dialog listing stories that failed to download.

    Shown after FanFicFare downloads complete (before the review queue) when
    one or more stories could not be fetched.  The user can open all failed
    URLs in the browser for manual download, or skip.

    Closing the window via the X button is treated as Skip (does not cancel sync).
    """

    def __init__(
        self,
        parent: tk.Tk,
        failed: list,
        on_open: Callable[[], None],
        on_skip: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title("Failed Downloads")
        self.grab_set()
        self.transient(parent)

        self._failed = failed
        self._on_open = on_open
        self._on_skip = on_skip

        self._build_ui()

        self.geometry("740x360")
        self.protocol("WM_DELETE_WINDOW", self._skip)
        self.wait_visibility()
        self.focus_set()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        main = ttk.Frame(self, padding=12)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        n = len(self._failed)
        ttk.Label(
            main,
            text=(
                f"{n} {'story' if n == 1 else 'stories'} could not be downloaded. "
                "Open in your browser to download manually."
            ),
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        tree_frame = ttk.Frame(main)
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        cols = ("title", "reason")
        self._tree = ttk.Treeview(
            tree_frame, columns=cols, show="headings", selectmode="none", height=10,
        )
        self._tree.heading("title", text="Title")
        self._tree.heading("reason", text="Failure Reason")
        self._tree.column("title", width=440, minwidth=120, stretch=True)
        self._tree.column("reason", width=160, minwidth=80, stretch=False)

        self._tree.tag_configure(browser_module.CATEGORY_LOGIN, background="#f8d7da")
        self._tree.tag_configure(browser_module.CATEGORY_CLOUDFLARE, background="#fff3cd")
        self._tree.tag_configure(browser_module.CATEGORY_FAILED, background="#f5f5f5")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        for result in self._failed:
            title = (result.story.get("title") or result.story["ao3_work_id"])[:80]
            reason = browser_module.categorize_failure(result)
            self._tree.insert("", "end", values=(title, reason), tags=(reason,))

        btn_frame = ttk.Frame(main)
        btn_frame.grid(row=2, column=0, sticky="e", pady=(10, 0))

        ttk.Button(btn_frame, text="Skip", command=self._skip).grid(
            row=0, column=0, padx=(0, 8)
        )
        ttk.Button(
            btn_frame,
            text=f"Open {n} {'Story' if n == 1 else 'Stories'} in Browser",
            command=self._open_in_browser,
        ).grid(row=0, column=1)

    def _open_in_browser(self) -> None:
        self.destroy()
        self._on_open()

    def _skip(self) -> None:
        self.destroy()
        self._on_skip()


# ---------------------------------------------------------------------------
# AO3 curation dialog
# ---------------------------------------------------------------------------


class AO3CurationDialog(tk.Toplevel):
    """
    Modal dialog listing stories whose Calibre #readstatus was just updated
    from the Palma and need AO3 curation.

    Stories are grouped into two sections:
      - Favorites — Add to bookmarks & mark read
      - Others    — Mark read only

    The user can open all URLs in the browser, or skip.
    Closing via X is treated as Skip.
    """

    def __init__(
        self,
        parent: tk.Tk,
        rs_result,
        on_open: Callable[[], None],
        on_skip: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title("AO3 Curation Needed")
        self.grab_set()
        self.transient(parent)

        self._rs_result = rs_result
        self._on_open = on_open
        self._on_skip = on_skip

        # Separate into groups.
        cids = browser_module.curation_needed(rs_result)
        self._favorites = [
            c for c in cids
            if rs_result.updated_statuses.get(c, "").lower() == "favorite"
        ]
        self._others = [c for c in cids if c not in set(self._favorites)]

        self._build_ui()

        self.geometry("740x400")
        self.protocol("WM_DELETE_WINDOW", self._skip)
        self.wait_visibility()
        self.focus_set()

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        main = ttk.Frame(self, padding=12)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        n = len(self._favorites) + len(self._others)
        ttk.Label(
            main,
            text=(
                f"{n} {'story' if n == 1 else 'stories'} need AO3 curation "
                "after Palma read status sync."
            ),
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        tree_frame = ttk.Frame(main)
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        cols = ("title", "status")
        self._tree = ttk.Treeview(
            tree_frame,
            columns=cols,
            show="tree headings",
            selectmode="none",
            height=12,
        )
        self._tree.heading("#0", text="")
        self._tree.heading("title", text="Title")
        self._tree.heading("status", text="New Status")
        self._tree.column("#0", width=20, minwidth=20, stretch=False)
        self._tree.column("title", width=440, minwidth=120, stretch=True)
        self._tree.column("status", width=160, minwidth=80, stretch=False)

        self._tree.tag_configure("group_header", background="#e9ecef", font=("TkDefaultFont", 9, "bold"))
        self._tree.tag_configure("favorite_row", background="#fff3cd")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self._populate_groups()

        btn_frame = ttk.Frame(main)
        btn_frame.grid(row=2, column=0, sticky="e", pady=(10, 0))

        ttk.Button(btn_frame, text="Skip", command=self._skip).grid(
            row=0, column=0, padx=(0, 8)
        )
        ttk.Button(
            btn_frame,
            text=f"Open {n} {'Story' if n == 1 else 'Stories'} in Browser",
            command=self._open_in_browser,
        ).grid(row=0, column=1)

    def _populate_groups(self) -> None:
        rs = self._rs_result
        if self._favorites:
            grp = self._tree.insert(
                "", "end",
                text="Favorites — Add to bookmarks & mark read",
                values=("", ""),
                tags=("group_header",),
                open=True,
            )
            for cid in self._favorites:
                title = (rs.updated_titles.get(cid) or str(cid))[:80]
                status = rs.updated_statuses.get(cid, "")
                self._tree.insert(grp, "end", values=(title, status), tags=("favorite_row",))

        if self._others:
            grp = self._tree.insert(
                "", "end",
                text="Others — Mark read only",
                values=("", ""),
                tags=("group_header",),
                open=True,
            )
            for cid in self._others:
                title = (rs.updated_titles.get(cid) or str(cid))[:80]
                status = rs.updated_statuses.get(cid, "")
                self._tree.insert(grp, "end", values=(title, status))

    def _open_in_browser(self) -> None:
        self.destroy()
        self._on_open()

    def _skip(self) -> None:
        self.destroy()
        self._on_skip()


# ---------------------------------------------------------------------------
# Review queue dialog
# ---------------------------------------------------------------------------


class ReviewQueueDialog(tk.Toplevel):
    """
    Modal dialog showing the normalisation review queue.

    Flagged rows (amber) require the user to supply a collection and/or ship
    value before the Confirm & Write button becomes available.
    Auto-resolved rows (green) are shown for visibility but need no action.

    Layout:
      - Treeview with two virtual groups: "Review Required" (expanded) and
        "Auto-resolved" (collapsed by default).
      - Edit panel below the tree for the selected row.
      - Cancel / Confirm & Write buttons.
    """

    _FLAGGED_IID = "group_flagged"
    _AUTO_IID = "group_auto"

    def __init__(
        self,
        parent: tk.Tk,
        queue: list,
        existing_ships: list[str],
        existing_collections: list[str],
        on_confirm: Callable[[list], None],
        on_cancel: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        self.title("Review Metadata")
        self.grab_set()
        self.transient(parent)

        self._queue = queue
        self._existing_ships = existing_ships
        # Merge library collections with config keyword collections for the dropdown
        config_collections = sorted({c for _, c in config.COLLECTION_KEYWORDS})
        self._existing_collections = sorted(
            set(existing_collections) | set(config_collections)
        )
        self._on_confirm = on_confirm
        self._on_cancel = on_cancel
        self._edit_row_index: int | None = None

        self._build_ui()
        self._populate()
        self._refresh_confirm_btn()

        self.geometry("940x580")
        self.wait_visibility()
        self.focus_set()

    # -----------------------------------------------------------------------
    # UI
    # -----------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        main = ttk.Frame(self, padding=12)
        main.grid(row=0, column=0, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(1, weight=1)

        ttk.Label(
            main,
            text=(
                "Review proposed metadata before writing to Calibre. "
                "Amber rows require your input."
            ),
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))

        # Treeview with group rows
        tree_frame = ttk.Frame(main)
        tree_frame.grid(row=1, column=0, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        cols = ("title", "fandom", "collection", "raw_ship", "ship", "status")
        self._tree = ttk.Treeview(
            tree_frame,
            columns=cols,
            show="tree headings",
            selectmode="browse",
            height=14,
        )

        self._tree.heading("#0", text="")
        self._tree.column("#0", width=16, minwidth=16, stretch=False)

        headings: dict[str, tuple[str, int, bool]] = {
            # col: (heading text, width, stretch)
            "title":      ("Title",         200, True),
            "fandom":     ("Fandom",        120, False),
            "collection": ("Collection",    100, False),
            "raw_ship":   ("Raw Ship",      150, False),
            "ship":       ("Proposed Ship", 130, False),
            "status":     ("Status",         68, False),
        }
        for col, (text, width, stretch) in headings.items():
            self._tree.heading(col, text=text)
            self._tree.column(col, width=width, minwidth=48, stretch=stretch)

        # Colour tags
        self._tree.tag_configure("review", background="#fff3cd")   # amber
        self._tree.tag_configure("resolved", background="#d4edda") # green
        self._tree.tag_configure("group", font=("TkDefaultFont", 9, "bold"))

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self._tree.bind("<<TreeviewSelect>>", self._on_select)

        # Edit panel
        edit_frame = ttk.LabelFrame(main, text="Edit Selected Row", padding=10)
        edit_frame.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        edit_frame.columnconfigure(1, weight=1)
        edit_frame.columnconfigure(3, weight=1)

        ttk.Label(edit_frame, text="Collection:").grid(
            row=0, column=0, sticky="w", padx=(0, 4)
        )
        self._edit_collection = ttk.Combobox(edit_frame, width=22, state="disabled")
        self._edit_collection.grid(row=0, column=1, sticky="ew", padx=(0, 14))

        ttk.Label(edit_frame, text="Ship:").grid(
            row=0, column=2, sticky="w", padx=(0, 4)
        )
        self._edit_ship = ttk.Combobox(edit_frame, width=28, state="disabled")
        self._edit_ship.grid(row=0, column=3, sticky="ew", padx=(0, 14))

        self._apply_btn = ttk.Button(
            edit_frame,
            text="Apply",
            state="disabled",
            command=self._apply_edit,
        )
        self._apply_btn.grid(row=0, column=4)

        # Confirm / Cancel
        btn_frame = ttk.Frame(main)
        btn_frame.grid(row=3, column=0, sticky="e", pady=(10, 0))

        ttk.Button(btn_frame, text="Cancel", command=self._cancel).grid(
            row=0, column=0, padx=(0, 8)
        )
        self._confirm_btn = ttk.Button(
            btn_frame,
            text="Confirm & Write",
            command=self._confirm,
            state="disabled",
        )
        self._confirm_btn.grid(row=0, column=1)

    # -----------------------------------------------------------------------
    # Populate treeview
    # -----------------------------------------------------------------------

    def _populate(self) -> None:
        flagged = review_module.flagged_rows(self._queue)
        auto = review_module.auto_rows(self._queue)

        # Group headers
        n_flagged = len(flagged)
        n_auto = len(auto)
        self._tree.insert(
            "", "end",
            iid=self._FLAGGED_IID,
            values=(f"Review Required ({n_flagged})", "", "", "", "", ""),
            open=True,
            tags=("group",),
        )
        self._tree.insert(
            "", "end",
            iid=self._AUTO_IID,
            values=(f"Auto-resolved ({n_auto})", "", "", "", "", ""),
            open=False,
            tags=("group",),
        )

        # Insert rows under their group — use the queue index as iid
        for i, row in enumerate(self._queue):
            parent = self._FLAGGED_IID if row.needs_review else self._AUTO_IID
            tag = "review" if row.needs_review else "resolved"
            self._tree.insert(
                parent, "end",
                iid=str(i),
                values=self._row_values(row),
                tags=(tag,),
            )

    def _row_values(self, row) -> tuple:
        title = (row.story.get("title") or row.story["ao3_work_id"])[:64]
        fandom = (row.story.get("fandoms") or "")[:36]
        collection = row.resolved_collection or row.collection_result.value or "—"
        raw_ship = (row.story.get("relationships") or "")[:40]
        ship = row.resolved_ship or row.ship_result.value or "—"
        status = "Review" if row.needs_review else "Auto"
        return (title, fandom, collection, raw_ship, ship, status)

    # -----------------------------------------------------------------------
    # Selection / editing
    # -----------------------------------------------------------------------

    def _on_select(self, _event: tk.Event) -> None:
        sel = self._tree.selection()
        if not sel:
            return
        iid = sel[0]
        if iid in (self._FLAGGED_IID, self._AUTO_IID):
            # Group header selected — clear edit panel
            self._edit_row_index = None
            self._edit_collection.configure(state="disabled")
            self._edit_ship.configure(state="disabled")
            self._apply_btn.configure(state="disabled")
            return

        idx = int(iid)
        self._edit_row_index = idx
        row = self._queue[idx]

        # Populate collection combobox
        coll_values = self._existing_collections
        self._edit_collection["values"] = coll_values
        self._edit_collection.set(
            row.resolved_collection or row.collection_result.value or ""
        )
        self._edit_collection.configure(state="normal")

        # Populate ship combobox
        self._edit_ship["values"] = self._existing_ships
        self._edit_ship.set(row.resolved_ship or row.ship_result.value or "")
        self._edit_ship.configure(state="normal")

        self._apply_btn.configure(state="normal")

    def _apply_edit(self) -> None:
        if self._edit_row_index is None:
            return
        idx = self._edit_row_index
        row = self._queue[idx]

        coll = self._edit_collection.get().strip()
        ship = self._edit_ship.get().strip()

        if coll:
            review_module.set_collection_override(row, coll)
        if ship:
            review_module.set_ship_override(row, ship)

        # Refresh the treeview row
        new_tag = "resolved" if row.is_resolved else "review"
        self._tree.item(str(idx), values=self._row_values(row), tags=(new_tag,))

        # If now resolved, move from flagged group to auto group visually?
        # Keep it simple: just recolour. The grouping is frozen after populate.

        self._refresh_confirm_btn()

    # -----------------------------------------------------------------------
    # Confirm / Cancel
    # -----------------------------------------------------------------------

    def _refresh_confirm_btn(self) -> None:
        state = "normal" if review_module.all_resolved(self._queue) else "disabled"
        self._confirm_btn.configure(state=state)

    def _confirm(self) -> None:
        self.destroy()
        self._on_confirm(self._queue)

    def _cancel(self) -> None:
        self.destroy()
        self._on_cancel()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    root = tk.Tk()
    FanFictionFlowApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
