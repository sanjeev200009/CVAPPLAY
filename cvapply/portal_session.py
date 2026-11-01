"""Saved browser sessions for portals that require a login.

XpressJobs is ~75% of the scored inventory and now gates its apply form behind
a job-seeker login — a logged-out listing page has zero apply buttons, which is
why every portal submission failed with an empty error. A bot cannot create the
account (phone/OTP), so the login happens once by hand:

    python -m cvapply.portal_session login xpressjobs

That opens a real browser window. Log in, then press Enter in the terminal. The
cookies are written to .sessions/xpressjobs.json and reused by every later run.

For the 24/7 GitHub Actions runner the file cannot live on disk — the runner is
wiped between runs — so it is passed in as a secret:

    python -m cvapply.portal_session export xpressjobs    # prints the blob
    gh secret set XPRESSJOBS_SESSION --body "<blob>"

and `storage_state_for()` prefers that env var over the local file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

SESSION_DIR = Path(__file__).resolve().parent.parent / ".sessions"

# portal -> (home page to log in on, env var holding the session for CI,
#            a selector that only exists while logged in)
PORTALS: dict[str, tuple[str, str, str]] = {
    "xpressjobs": (
        "https://xpress.jobs/",
        "XPRESSJOBS_SESSION",
        'button:has-text("APPLY"), a:has-text("APPLY")',
    ),
}


def _path(portal: str) -> Path:
    return SESSION_DIR / f"{portal}.json"


def storage_state_for(portal: str) -> dict | None:
    """Cookies for this portal, from the CI secret or the local file."""
    _, env_var, _ = PORTALS.get(portal, ("", "", ""))
    blob = os.getenv(env_var or "")
    if blob:
        try:
            return json.loads(blob)
        except Exception:
            print(f"  [session] {env_var} is set but is not valid JSON — ignoring")

    p = _path(portal)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"  [session] {p.name} unreadable: {exc}")
    return None


def have_session(portal: str) -> bool:
    return storage_state_for(portal) is not None


def login(portal: str) -> None:
    """Open a real browser, wait for a manual login, save the cookies."""
    from playwright.sync_api import sync_playwright

    if portal not in PORTALS:
        raise SystemExit(f"unknown portal {portal!r}; known: {', '.join(PORTALS)}")
    home, env_var, _ = PORTALS[portal]
    SESSION_DIR.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(locale="en-US", viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.goto(home, timeout=90000, wait_until="domcontentloaded")

        print()
        print(f"  A browser window is open on {home}")
        print("  1. Click JOB SEEKERS LOGIN and sign in (create the account first if needed).")
        print("  2. Leave the browser on a logged-in page.")
        print("  3. Come back here and press Enter.")
        print()
        input("  Press Enter once you are logged in... ")

        context.storage_state(path=str(_path(portal)))
        browser.close()

    state = storage_state_for(portal)
    n = len(state.get("cookies", [])) if state else 0
    print(f"  Saved {n} cookies to {_path(portal)}")
    if n == 0:
        print("  No cookies captured — the login did not complete. Run this again.")
        return
    print(f"  For the 24/7 runner: python -m cvapply.portal_session export {portal}")


def export(portal: str) -> None:
    """Print the session as one line, for `gh secret set`."""
    state = storage_state_for(portal)
    if not state:
        raise SystemExit(f"no session for {portal}; run: python -m cvapply.portal_session login {portal}")
    _, env_var, _ = PORTALS[portal]
    print(json.dumps(state, separators=(",", ":")))
    print(f"\n  ^ store that as the {env_var} repo secret", flush=True)


def check(portal: str) -> None:
    """Confirm the saved session still gets us an apply form."""
    from playwright.sync_api import sync_playwright

    home, _, logged_in_sel = PORTALS[portal]
    state = storage_state_for(portal)
    if not state:
        raise SystemExit(f"no session for {portal}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=state)
        page = context.new_page()
        page.goto(home, timeout=90000, wait_until="domcontentloaded")
        logged_out = page.locator('button:has-text("JOB SEEKERS LOGIN")').count()
        print(f"  login button still showing: {logged_out}  (0 means the session works)")
        browser.close()


if __name__ == "__main__":
    import sys

    cmds = {"login": login, "export": export, "check": check}
    if len(sys.argv) < 2 or sys.argv[1] not in cmds:
        raise SystemExit(f"usage: python -m cvapply.portal_session {{{'|'.join(cmds)}}} <portal>")
    cmds[sys.argv[1]](sys.argv[2] if len(sys.argv) > 2 else "xpressjobs")
