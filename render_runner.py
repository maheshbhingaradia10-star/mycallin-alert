"""One-shot Render entrypoint. Disabled until setup is explicitly completed."""
import argparse
import json
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from mycallin_alert import run


def in_window(now):
    # Render schedule: 5 10,11 * * * (UTC). Exactly one of the two
    # candidates falls in this local window across standard/daylight time.
    local = now.astimezone(ZoneInfo("America/Chicago"))
    return local.hour == 5 and 5 <= local.minute <= 20


def load_config(dry_run=False):
    raw = os.environ.get("MYCALLIN_CONFIG_JSON", "")
    if not raw:
        raise ValueError("Set MYCALLIN_CONFIG_JSON after verifying the site flow")
    try:
        cfg = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("MYCALLIN_CONFIG_JSON is not valid JSON") from None
    if not isinstance(cfg, dict) or cfg.get("verified") is not True:
        raise ValueError("Site configuration has not been verified")
    if cfg.get("timezone") != "America/Chicago":
        raise ValueError("This schedule requires America/Chicago; confirm site timezone first")
    for key in ("submit_selector", "result_selector", "status_selector", "date_selector",
                "date_format", "template", "language"):
        if not isinstance(cfg.get(key), str) or not cfg[key].strip():
            raise ValueError("Configure " + key)
    if "%Y" not in cfg["date_format"]:
        raise ValueError("date_format must include a four-digit year")
    for key in ("yes_phrases", "no_phrases"):
        phrases = cfg.get(key)
        if not isinstance(phrases, list) or not phrases or not all(
            isinstance(p, str) and p.strip() for p in phrases
        ):
            raise ValueError("Configure exact observed " + key)
    from mycallin_alert import normalized
    if {normalized(p) for p in cfg["yes_phrases"]} & {normalized(p) for p in cfg["no_phrases"]}:
        raise ValueError("Test-required and no-test phrases overlap")
    steps = cfg.get("login_steps")
    if not isinstance(steps, list) or not steps:
        raise ValueError("Configure login_steps")
    required = []
    for step in steps:
        if not isinstance(step, dict) or not step.get("selector") or not step.get("env"):
            raise ValueError("Each login step needs a selector and environment variable name")
        required.append(step["env"])
    if not dry_run:
        required += ["WA_ACCESS_TOKEN", "WA_PHONE_NUMBER_ID", "WA_API_VERSION", "WA_TO"]
    if any(not os.environ.get(name, "").strip() for name in required):
        raise ValueError("Login or WhatsApp environment variables are missing")
    return cfg


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-setup", action="store_true", help="Validate setup without network calls")
    parser.add_argument("--now", action="store_true", help="Manual run bypassing the scheduled window")
    parser.add_argument("--dry-run", action="store_true", help="Website check only; no WhatsApp upload")
    args = parser.parse_args()
    if not args.check_setup and os.environ.get("ALERTS_ENABLED", "false").lower() != "true":
        print("DISABLED: no website check or WhatsApp message performed.")
        return 0
    if not args.now and not args.check_setup and not in_window(datetime.now(ZoneInfo("UTC"))):
        print("SKIPPED: outside 05:05-05:20 America/Chicago. No check performed.")
        return 0
    cfg = load_config(args.dry_run)
    if args.check_setup:
        print("Configuration is present. Live website and delivery validation are still required.")
        return 0
    return run(cfg, args.dry_run)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ValueError as exc:
        print("SETUP ERROR: " + str(exc), file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        # Never print tokens, form values, status text or HTTP response bodies.
        print("RUN FAILED (" + type(exc).__name__ + "). Check manually.", file=sys.stderr)
        sys.exit(1)
