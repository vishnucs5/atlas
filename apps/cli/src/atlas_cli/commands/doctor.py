"""Implementation of 'atlas doctor' environment diagnostic command."""

import platform
import sqlite3
import sys

from atlas_cli.config import get_atlas_dir, get_db_path


def check_python_version() -> tuple[bool, str]:
    """Verify current Python interpreter is 3.11 or higher."""
    version_str = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if sys.version_info >= (3, 11):  # noqa: UP036
        return True, f"Python: {version_str} (>= 3.11 required) [OK]"
    return False, f"Python: {version_str} (>= 3.11 required) [FAIL]"


def check_platform() -> tuple[bool, str]:
    """Report platform and OS details."""
    os_detail = f"{sys.platform} ({platform.platform()})"
    return True, f"Platform: {os_detail} [OK]"


def check_windows_long_paths() -> tuple[bool, str] | None:
    """Verify Windows LongPathsEnabled registry setting if on Windows."""
    if sys.platform != "win32":
        return None

    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\FileSystem",
        ) as key:
            val, _ = winreg.QueryValueEx(key, "LongPathsEnabled")
            if bool(val):
                return True, "Windows Long Paths: Enabled [OK]"
            return True, "Windows Long Paths: Disabled (Recommended to enable) [INFO]"
    except Exception:
        return True, "Windows Long Paths: Unverified [INFO]"


def check_sqlite() -> tuple[bool, str]:
    """Verify SQLite library availability and WAL mode operation."""
    try:
        conn = sqlite3.connect(":memory:")
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode = WAL;")
        cursor.execute("PRAGMA busy_timeout = 5000;")
        conn.close()
        return True, f"SQLite: {sqlite3.sqlite_version} (WAL mode supported) [OK]"
    except Exception as exc:
        return False, f"SQLite: Error initializing SQLite ({exc}) [FAIL]"


def check_workspace() -> tuple[bool, str]:
    """Check if the ATLAS workspace is initialized."""
    atlas_dir = get_atlas_dir()
    db_path = get_db_path()
    if atlas_dir.exists() and db_path.exists():
        return True, f"Workspace: Initialized at {atlas_dir} [OK]"
    return True, f"Workspace: Not initialized at {atlas_dir} (Run 'atlas init') [INFO]"


def run_doctor() -> int:
    """Run all environment diagnostic checks and report overall health status."""
    print("ATLAS Environment Diagnostics")
    print("=============================")

    results: list[tuple[bool, str]] = []

    # Run checks
    results.append(check_python_version())
    results.append(check_platform())

    win_check = check_windows_long_paths()
    if win_check:
        results.append(win_check)

    results.append(check_sqlite())
    results.append(check_workspace())

    all_passed = True
    for passed, message in results:
        print(f"  {message}")
        if not passed:
            all_passed = False

    print("=============================")
    if all_passed:
        print("System status: HEALTHY")
        return 0
    else:
        print("System status: UNHEALTHY")
        return 1
