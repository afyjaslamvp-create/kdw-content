"""Publish the Kids Discovery World content library.

One button (or one keypress) does the whole job:

    1. validate the content (same checks the build and the app use)
    2. build the publishable library and show exactly what changed
    3. bump the library version so installed apps notice the update
    4. commit the source files and push them to GitHub

GitHub Pages then rebuilds the library (about two minutes), and the installed
application picks up the new content with its own update check - no new APK.

The double-click entry point is `publish.bat` next to this file. With no
arguments the helper opens a small window with buttons; run
`python tools/publish.py --console` for a plain text menu instead.

Nothing here stores or needs a token: `git push` uses whatever credentials
Windows Git already has (for example the ones GitHub Desktop set up).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CONTENT_DIR = os.path.join(ROOT, "content")
DIST_DIR = os.path.join(ROOT, "dist")
LIBRARY_PATH = os.path.join(CONTENT_DIR, "library.json")

UAE = timezone(timedelta(hours=4))


def log(message: str) -> None:
    print(message, flush=True)


# ------------------------------------------------------------- content steps
def run_check(log_fn=log) -> int:
    """Run the validator and stream its output. Returns its exit code."""
    log("-" * 60)
    log("Step 1/3: checking the content")
    log("-" * 60)
    return stream_run([sys.executable, os.path.join(HERE, "validate_content.py")], log_fn)


def read_library() -> dict:
    with open(LIBRARY_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def bump_library(log_fn=log) -> bool:
    """Move the library version on so installed apps notice the new content."""
    try:
        library = read_library()
    except (OSError, json.JSONDecodeError) as error:
        log_fn(f"Cannot read {LIBRARY_PATH}: {error}")
        return False

    number = library.get("libraryVersionNumber")
    if not isinstance(number, int) or number < 1:
        log_fn("libraryVersionNumber is missing - fix content/library.json first.")
        return False
    number += 1
    library["libraryVersionNumber"] = number

    version = library.get("libraryVersion", "")
    if isinstance(version, str) and "-" in version:
        date_part, _tail = version.rsplit("-", 1)
        today = datetime.now(UAE).strftime("%Y.%m.%d")
        library["libraryVersion"] = (today if date_part != today else date_part) + f"-{number}"

    with open(LIBRARY_PATH, "w", encoding="utf-8") as handle:
        json.dump(library, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    log_fn(f"Library version bumped to {library['libraryVersion']} (#{number}).")
    return True


def run_build(log_fn=log) -> int:
    """Build the library; the build validates everything first."""
    log_fn("-" * 60)
    log_fn("Step 2/3: building the library (this also re-checks everything)")
    log_fn("-" * 60)
    code = stream_run([sys.executable, os.path.join(HERE, "build_content.py")], log_fn)
    if code == 0:
        report_path = os.path.join(DIST_DIR, "build-report.json")
        if os.path.exists(report_path):
            try:
                with open(report_path, "r", encoding="utf-8") as handle:
                    report = json.load(handle)
                log_fn("")
                log_fn("What kids will download:")
                if not (
                    report.get("addedPacks")
                    or report.get("changedPacks")
                    or report.get("removedPacks")
                ):
                    log_fn("  nothing new - no files changed since the last build")
                else:
                    for pack_id in report.get("addedPacks", []):
                        log_fn(f"  + new pack: {pack_id}")
                    for pack_id in report.get("changedPacks", []):
                        log_fn(f"  ~ changed pack: {pack_id}")
                    for pack_id in report.get("removedPacks", []):
                        log_fn(f"  - removed pack: {pack_id}")
                    log_fn(
                        f"  about {report.get('downloadBytes', 0) / 1024:.0f} KB "
                        f"for each updating device"
                    )
            except (OSError, json.JSONDecodeError):
                pass
    return code


# -------------------------------------------------------------------- git
def git(*args: str, log_fn=log) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        log_fn("Git is not installed or not on PATH. Install Git and try again.")
        return 127, ""
    output = (result.stdout or "") + (result.stderr or "")
    for line in output.strip().splitlines():
        log_fn(f"  git> {line}")
    return result.returncode, output


def stream_run(cmd: list[str], log_fn=log) -> int:
    """Run a command, streaming its output through log_fn."""
    try:
        process = subprocess.Popen(
            cmd,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as error:
        log_fn(f"Could not start {cmd[1]}: {error}")
        return 127
    assert process.stdout is not None
    for line in process.stdout:
        log_fn(line.rstrip())
    return process.wait()


def last_committed_number() -> int | None:
    """The libraryVersionNumber in the last commit, or None when unknown."""
    code, output = git("show", "HEAD:content/library.json")
    if code != 0:
        return None
    try:
        value = json.loads(output)
    except json.JSONDecodeError:
        return None
    number = value.get("libraryVersionNumber")
    return number if isinstance(number, int) else None


def changed_content_files() -> list[str]:
    code, output = git("status", "--porcelain", "content/")
    if code != 0:
        return []
    return [line[3:].strip() for line in output.strip().splitlines() if line.strip()]


def run_publish(bump: bool, commit_message: str, log_fn=log) -> int:
    log_fn("=" * 60)
    log_fn("PUBLISH: check, build, commit, push")
    log_fn("=" * 60)

    if run_check(log_fn) != 0:
        log_fn("")
        log_fn("Stopped: the content has problems - fix them and try again.")
        return 1

    code, _ = git("--version")
    if code != 0:
        return 1

    code, _ = git("rev-parse", "--is-inside-work-tree")
    if code != 0:
        log_fn("This folder is not a git repository - cannot commit or push.")
        return 1

    code, _ = git("remote", "get-url", "origin")
    if code != 0:
        log_fn("No 'origin' remote is set - nothing to push to.")
        return 1

    changed = changed_content_files()
    committed_number = last_committed_number()
    already_bumped = committed_number is not None and not _same_library_number(committed_number)

    if changed:
        if already_bumped:
            log_fn("The library version number is already different from the last commit - keeping your bump.")
        elif bump:
            if not bump_library(log_fn):
                log_fn("Stopped: could not bump the library version.")
                return 1
        else:
            log_fn("")
            log_fn(
                "Warning: the content changed but the library version number was not "
                "bumped, so installed apps may not notice the update."
            )

    if not changed:
        log_fn("")
        log_fn("The content files are identical to the last commit - nothing to publish.")
        return 0

    if run_build(log_fn) != 0:
        log_fn("")
        log_fn("Stopped: the build found problems - nothing was committed or pushed.")
        return 1

    code, _ = git("add", "content/")
    if code != 0:
        log_fn("Git could not stage the content files.")
        return 1

    log_fn("-" * 60)
    log_fn("Step 3/3: committing and pushing")
    log_fn("-" * 60)
    code, _ = git("commit", "-m", commit_message)
    if code != 0:
        log_fn("Git did not create a commit - nothing was pushed.")
        return 1

    code, _ = git("push", "origin", "HEAD")
    if code != 0:
        log_fn("")
        log_fn(
            "The commit is saved on this computer, but the push failed. Fix the "
            "git credentials (for example with GitHub Desktop or `git config "
            "credential.helper`) and push again with:  git push"
        )
        return 1

    log_fn("")
    log_fn("Published.")
    log_fn(
        "GitHub Pages rebuilds the library in about two minutes, and installed "
        "apps pick it up at their next check (on start, when the internet comes "
        "back, or within six hours). No new APK is needed."
    )
    return 0


def _same_library_number(committed: int) -> bool:
    try:
        return read_library().get("libraryVersionNumber") == committed
    except (OSError, json.JSONDecodeError):
        return False


def default_commit_message(report_path: str | None = None) -> str:
    try:
        library = read_library()
        version = library.get("libraryVersion", "?")
        number = library.get("libraryVersionNumber", "?")
    except (OSError, json.JSONDecodeError):
        version, number = "?", "?"
    return f"Content library {version} (#{number})"


def open_content_folder() -> None:
    if sys.platform == "win32":
        os.startfile(CONTENT_DIR)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", CONTENT_DIR])


def open_editor() -> None:
    import webbrowser

    path = os.path.join(HERE, "authoring", "index.html")
    webbrowser.open("file://" + path.replace(os.sep, "/"))


# -------------------------------------------------------------- console mode
def console_menu() -> int:
    while True:
        log("")
        log("Kids Discovery World - publish helper")
        log("[1] Check the content")
        log("[2] Build and show what changed (no commit)")
        log("[3] Publish: check, build, commit, push")
        log("[4] Open the content folder")
        log("[5] Open the content editor")
        log("[q] Quit")
        try:
            choice = input("Choice: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return 0

        if choice == "1":
            run_check()
        elif choice == "2":
            run_build()
        elif choice == "3":
            committed = last_committed_number()
            current_number = None
            try:
                current_number = read_library().get("libraryVersionNumber")
            except (OSError, json.JSONDecodeError):
                pass
            if committed is not None and current_number is not None and current_number != committed:
                log(f"Note: the library version is already bumped ({committed} -> {current_number}); keeping it.")
                bump = False
            else:
                bump = (
                    input("Bump the library version number so apps notice? [Y/n] ").strip().lower()
                    in ("", "y")
                )
            message = input(f"Commit message [{default_commit_message()}]: ").strip()
            if not message:
                message = default_commit_message()
            code = run_publish(bump, message)
            if code != 0:
                input("Press Enter to continue...")
        elif choice == "4":
            open_content_folder()
        elif choice == "5":
            open_editor()
        elif choice in ("q", "quit", "exit"):
            return 0
        else:
            log("Please choose 1-5 or q.")


# -------------------------------------------------------------------- gui
def gui() -> int:
    import queue
    import threading

    import tkinter as tk
    from tkinter import messagebox, scrolledtext

    out_queue: "queue.Queue[str]" = queue.Queue()

    def log_fn(message: str) -> None:
        out_queue.put(message)

    root = tk.Tk()
    root.title("Kids Discovery World - Publish content")
    root.geometry("860x640")
    root.minsize(640, 420)

    log_box = scrolledtext.ScrolledText(
        root,
        wrap="word",
        font=("Consolas", 9),
        state="disabled",
        background="#10233d",
        foreground="#e8f0fe",
    )
    log_box.pack(fill="both", expand=True, padx=10, pady=(10, 4))

    def append(text: str) -> None:
        log_box.configure(state="normal")
        log_box.insert("end", text + "\n")
        log_box.see("end")
        log_box.configure(state="disabled")

    def pump() -> None:
        try:
            while True:
                append(out_queue.get_nowait())
        except queue.Empty:
            pass
        root.after(120, pump)

    bump_var = tk.BooleanVar(value=True)
    message_var = tk.StringVar(value=default_commit_message())
    options = tk.Frame(root)
    options.pack(fill="x", padx=10)
    tk.Checkbutton(
        options,
        text="Bump the library version number so installed apps notice",
        variable=bump_var,
    ).pack(side="left")
    tk.Entry(options, textvariable=message_var).pack(side="left", fill="x", expand=True, padx=(12, 0))
    tk.Label(options, text="commit message", foreground="#5b6b7c").pack(side="left", padx=(6, 0))

    buttons = tk.Frame(root)
    buttons.pack(fill="x", padx=10, pady=8)

    busy = {"flag": False}

    def set_busy(value: bool) -> None:
        busy["flag"] = value
        for child in buttons.winfo_children():
            child.configure(state="disabled" if value else "normal")

    def in_worker(fn) -> None:
        if busy["flag"]:
            return
        set_busy(True)
        code_box = {"value": 0}

        def job() -> None:
            try:
                code_box["value"] = fn() or 0
            except Exception as error:  # noqa: BLE001 - show anything that goes wrong
                out_queue.put(f"Unexpected error: {error}")
                code_box["value"] = 1
            finally:
                out_queue.put("")
                root.after(0, lambda: set_busy(False))

        threading.Thread(target=job, daemon=True).start()

    tk.Button(buttons, text="1. Check content", command=lambda: in_worker(run_check)).pack(
        side="left", padx=(0, 6)
    )
    tk.Button(
        buttons, text="2. Build + show changes", command=lambda: in_worker(run_build)
    ).pack(side="left", padx=(0, 6))
    tk.Button(
        buttons,
        text="3. Publish (check, build, commit, push)",
        command=lambda: in_worker(
            lambda: run_publish(
                bool(bump_var.get()), message_var.get().strip() or default_commit_message()
            )
        ),
    ).pack(side="left", padx=(0, 6))
    tk.Button(buttons, text="Open content folder", command=open_content_folder).pack(
        side="left", padx=(0, 6)
    )
    tk.Button(buttons, text="Open content editor", command=open_editor).pack(side="left")

    append("Ready. Edit the content with the content editor, then press "
           "3. Publish (check, build, commit, push).")
    append("Nothing is sent anywhere until you press a button; no tokens are stored.")
    root.after(120, pump)

    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    return 0


# -------------------------------------------------------------------- main
def main() -> int:
    os.chdir(ROOT)
    if "--console" in sys.argv[1:]:
        return console_menu()
    try:
        import tkinter  # noqa: F401
    except ImportError:
        log("The windowed helper needs tkinter, which this Python does not include.")
        log("Falling back to the text menu (or install the standard Python from python.org).")
        log("")
        return console_menu()
    if sys.stdout is None:  # pythonw: no console at all
        return gui()
    return gui()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
