#!/usr/bin/env python3
"""MyCallIn website check and Meta WhatsApp sender. See README.md for setup.
Site configuration remains unverified; use render_runner.py on Render.
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

BASE = Path(__file__).resolve().parent
CONFIG = BASE / "mycallin_config.json"
EXAMPLE = {
    "verified": False,
    "timezone": "America/Chicago",
    "login_steps": [{"selector": "", "env": "MYCALLIN_FIELD_1"},
                    {"selector": "", "env": "MYCALLIN_FIELD_2"},
                    {"selector": "", "env": "MYCALLIN_FIELD_3"}],
    "submit_selector": "", "result_selector": "",
    "status_selector": "", "date_selector": "", "date_format": "",
    "yes_phrases": [], "no_phrases": [],
    "template": "mycallin_daily", "language": "en_US"
}
UNKNOWN = "STATUS UNKNOWN - check MyCallIn manually"


def normalized(text):
    return " ".join(text.casefold().split())


def classify(status_text, date_text, cfg, today):
    try:
        if datetime.strptime(date_text.strip(), cfg["date_format"]).date() != today:
            return UNKNOWN
    except (ValueError, KeyError):
        return UNKNOWN
    yes = normalized(status_text) in {normalized(p) for p in cfg["yes_phrases"]}
    no = normalized(status_text) in {normalized(p) for p in cfg["no_phrases"]}
    if yes == no:
        return UNKNOWN
    return "TEST REQUIRED TODAY" if yes else "NO TEST TODAY"


def env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError("Missing environment variable: " + name)
    return value


def check(cfg, image_path, now):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(timezone_id=cfg["timezone"])
            page.set_default_timeout(25000)
            response = page.goto("https://mycallin.com/", wait_until="domcontentloaded")
            if response is None or response.status >= 400:
                raise RuntimeError("Site unavailable")
            # Do not send credentials to an unexpected redirect destination.
            if urlsplit(page.url).scheme != "https" or urlsplit(page.url).hostname not in {
                "mycallin.com", "www.mycallin.com"
            }:
                raise RuntimeError("Unexpected login destination")
            for step in cfg["login_steps"]:
                page.locator(step["selector"]).fill(env(step["env"]))
            page.locator(cfg["submit_selector"]).click()
            # Add ONLY verified continuation buttons after inspecting the live
            # flow. Never auto-accept agreements or solve verification challenges.
            for selector in cfg.get("continuation_selectors", []):
                page.locator(selector).click()
            result = page.locator(cfg["result_selector"])
            result.wait_for(state="visible")
            # A narrow result card avoids sending login fields or unrelated history.
            if result.locator("input, textarea").count():
                raise RuntimeError("Result scope includes form fields")
            status_text = result.locator(cfg["status_selector"]).inner_text()
            date_text = result.locator(cfg["date_selector"]).inner_text()
            status = classify(status_text, date_text, cfg, now.date())
            result.screenshot(path=str(image_path), animations="disabled")
            # Do not assign yesterday's result to today across local midnight.
            if datetime.now(ZoneInfo(cfg["timezone"])).date() != now.date():
                return UNKNOWN
            return status
        finally:
            browser.close()


def failure_image(path, now):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (1050, 210), "white")
    draw = ImageDraw.Draw(img)
    draw.text((25, 30), "MYCALLIN CHECK FAILED - STATUS UNKNOWN", fill="red")
    draw.text((25, 70), now.isoformat(timespec="minutes"), fill="black")
    draw.text((25, 110), "Open MyCallIn and check manually. This is NOT a website screenshot.", fill="black")
    img.save(path)


def send(cfg, image_path, now, status):
    import requests
    version = env("WA_API_VERSION")
    sender = env("WA_PHONE_NUMBER_ID")
    recipient = env("WA_TO")
    if not re.fullmatch(r"v\d+\.\d+", version) or not sender.isdigit():
        raise ValueError("Invalid API version or sender ID")
    if not re.fullmatch(r"[1-9]\d{7,14}", recipient):
        raise ValueError("WA_TO must include country code, digits only")
    if image_path.stat().st_size > 5_000_000:
        raise ValueError("Image exceeds WhatsApp image size limit")
    root = f"https://graph.facebook.com/{version}/{sender}"
    headers = {"Authorization": "Bearer " + env("WA_ACCESS_TOKEN")}
    with image_path.open("rb") as photo:
        response = requests.post(root + "/media", headers=headers,
                                 data={"messaging_product": "whatsapp", "type": "image/png"},
                                 files={"file": ("daily-check.png", photo, "image/png")}, timeout=60)
    if not response.ok:
        raise RuntimeError("WhatsApp media upload failed, HTTP " + str(response.status_code))
    media_id = response.json()["id"]
    values = [now.strftime("%Y-%m-%d"), status, now.strftime("%H:%M %Z")]
    payload = {"messaging_product": "whatsapp", "to": recipient, "type": "template",
               "template": {"name": cfg["template"], "language": {"code": cfg["language"]},
                            "components": [
                                {"type": "header", "parameters": [
                                    {"type": "image", "image": {"id": media_id}}]},
                                {"type": "body", "parameters": [
                                    {"type": "text", "text": v} for v in values]}]}}
    response = requests.post(root + "/messages", headers=headers, json=payload, timeout=60)
    if not response.ok:
        raise RuntimeError("WhatsApp submission failed, HTTP " + str(response.status_code))
    return response.json()["messages"][0]["id"]


def run(cfg, dry_run):
    now = datetime.now(ZoneInfo(cfg["timezone"]))
    out = Path(os.environ.get("OUTPUT_DIR", str(BASE / "private_output")))
    out.mkdir(mode=0o700, exist_ok=True)
    image_path, state_path = out / "latest.png", out / "state.json"
    try:
        status = check(cfg, image_path, now)
    except Exception as exc:
        # Raw browser/HTTP exceptions can contain credentials; do not print them.
        print("Site check failed (" + type(exc).__name__ + "). Check manually.", file=sys.stderr)
        status = UNKNOWN
        failure_image(image_path, now)
    # Shared hosting logs must not contain the person's test status.
    print(now.isoformat(timespec="minutes"), "Website check finished.", flush=True)
    if dry_run:
        print("Dry run: image saved locally; no WhatsApp message sent.")
        return 2 if status == UNKNOWN else 0
    previous = json.loads(state_path.read_text()) if state_path.exists() else {}
    key = now.date().isoformat() + ":" + status
    if previous.get("key") == key:
        print("Unchanged daily status already submitted; skipped.")
        return 2 if status == UNKNOWN else 0
    message_id = send(cfg, image_path, now, status)
    temporary = state_path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"key": key, "message_id": message_id}))
    temporary.replace(state_path)
    print("WhatsApp API accepted the message; phone delivery is not yet verified.")
    return 2 if status == UNKNOWN else 0


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--init", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--daily", metavar="HH:MM")
    args = parser.parse_args()
    if args.init:
        with CONFIG.open("x") as file:
            json.dump(EXAMPLE, file, indent=2)
        print("Created configuration. Read --help before configuring.")
        return
    cfg = json.loads(CONFIG.read_text())
    if not cfg.get("verified") or not all(cfg.get(k) for k in (
        "submit_selector", "result_selector", "status_selector", "date_selector",
        "date_format", "yes_phrases", "no_phrases", "login_steps"
    )) or not all(s.get("selector") and s.get("env") for s in cfg["login_steps"]):
        raise ValueError("Site configuration is incomplete or unverified; no check or send performed")
    if "%Y" not in cfg["date_format"]:
        raise ValueError("Date format must include a four-digit year")
    if not args.daily:
        run(cfg, args.dry_run)
        return
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", args.daily):
        raise ValueError("Use HH:MM in 24-hour time")
    last_day = None
    print("Daily process running in " + cfg["timezone"] + "; keep this computer awake.", flush=True)
    while True:
        now = datetime.now(ZoneInfo(cfg["timezone"]))
        if now.strftime("%H:%M") == args.daily and last_day != now.date():
            last_day = now.date()
            try:
                run(cfg, args.dry_run)
            except Exception as exc:
                print("ALERT FAILED (" + type(exc).__name__ + "). Check manually.", file=sys.stderr, flush=True)
        time.sleep(20)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        print("Setup/run failed (" + type(exc).__name__ + "). Review configuration and --help.", file=sys.stderr)
        sys.exit(1)
