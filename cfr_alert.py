# cfr_alert.py  (Alarm 30m before the train reaches Videle = actual departure from Videle)
import re, sys, time
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional, List
from bs4 import BeautifulSoup
from dateutil import tz
from plyer import notification
from playwright.sync_api import sync_playwright

try:
    import winsound
    HAS_WINSOUND = True
except Exception:
    HAS_WINSOUND = False

ROUTE_URL_DEFAULT = "https://mersultrenurilor.infofer.ro/ro-RO/Rute-trenuri/Videle/Bucuresti-(toate-statiile)"

@dataclass
class Snapshot:
    found: bool
    dep_sched: Optional[datetime] = None
    delay_min: int = 0
    target_dt: Optional[datetime] = None  # actual depart from Videle
    card_id: Optional[str] = None
    note: str = ""

def notify(title: str, msg: str):
    try:
        notification.notify(title=title, message=msg, timeout=6)
    except Exception:
        print("\a" + f"[NOTIFY] {title}: {msg}")

def beep():
    try:
        if HAS_WINSOUND:
            winsound.Beep(1200, 500)
        else:
            sys.stdout.write("\a"); sys.stdout.flush()
    except Exception:
        pass

def get_rendered_html(url: str) -> str:
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        page = b.new_page()
        page.goto(url, wait_until="networkidle", timeout=45000)
        page.wait_for_selector('li[id^="li-itinerary-"]', timeout=20000)
        html = page.content()
        b.close()
        return html

def list_card_ids(soup: BeautifulSoup) -> List[str]:
    return [li.get("id") for li in soup.select('li[id^="li-itinerary-"]')]

def to_today_dt(hhmm: str, tzinfo) -> datetime:
    """Return today's datetime at HH:MM (NO rolling to tomorrow)."""
    now = datetime.now(tzinfo)
    h, m = map(int, hhmm.split(":"))
    return now.replace(hour=h, minute=m, second=0, microsecond=0)

def parse_delay_min(text: str) -> int:
    m = re.search(r"(\d+)\s*min", text, flags=re.IGNORECASE)
    return int(m.group(1)) if m else 0

def parse_card_for_videle_depart(card, tzinfo) -> Snapshot:
    txt = card.get_text(" ", strip=True)

    # Scheduled depart (Videle)
    m_dep = re.search(r"Plecare\s*(?:la)?\s*([0-2]?\d:[0-5]\d)", txt, flags=re.IGNORECASE)
    if not m_dep:
        m_dep = re.search(r"\b([0-2]?\d:[0-5]\d)\b", txt)
    if not m_dep:
        return Snapshot(False, note="no dep time", card_id=card.get("id"))

    dep_hhmm = m_dep.group(1)
    dep_dt = to_today_dt(dep_hhmm, tzinfo)

    # Live delay: prefer gray stopwatch spans, fallback to whole card
    delay_min = 0
    gray_spans = card.find_all("span", class_=re.compile(r"color-gray", re.IGNORECASE))
    for sp in gray_spans:
        t = sp.get_text(" ", strip=True)
        tl = t.lower()
        if "intarziere" in tl or "întârziere" in tl or "pleaca cu" in tl or "pleacă cu" in tl:
            delay_min = parse_delay_min(t)
            if delay_min:
                break
    if delay_min == 0:
        m = re.search(r"(\d+)\s*min\s*(?:intarziere|întârziere)", txt, flags=re.IGNORECASE)
        if m:
            delay_min = int(m.group(1))

    # Actual depart = scheduled + delay
    actual_depart = dep_dt + timedelta(minutes=delay_min)

    # Today-only: if already in the past, clamp to now
    now = datetime.now(tzinfo)
    if actual_depart < now:
        actual_depart = now

    return Snapshot(
        True,
        dep_sched=dep_dt,
        delay_min=delay_min,
        target_dt=actual_depart,
        card_id=card.get("id"),
        note="vid-ele depart"
    )

def scrape(url: str, itinerary_id: Optional[int], tzinfo) -> Snapshot:
    html = get_rendered_html(url)
    soup = BeautifulSoup(html, "html.parser")

    card = None
    if itinerary_id is not None:
        li_id = f"li-itinerary-{itinerary_id}"
        card = soup.find(id=li_id)
        if not card:
            ids = ", ".join(list_card_ids(soup))
            return Snapshot(False, note=f"{li_id} not found; have: {ids}")
    else:
        for li in soup.select('li[id^="li-itinerary-"]'):
            if li.find("span", class_=re.compile(r"color-gray", re.IGNORECASE)):
                card = li
                break
        if not card:
            ids = ", ".join(list_card_ids(soup))
            return Snapshot(False, note=f"no card with delay; have: {ids}")

    return parse_card_for_videle_depart(card, tzinfo)

def run_monitor(url: str, itinerary_id: Optional[int], tz_name: str, interval_s: int, notify_at_min: int, alarm_gap_s: int):
    tzinfo = tz.gettz(tz_name)
    if not tzinfo:
        print("Unknown timezone: " + tz_name, file=sys.stderr)
        sys.exit(1)

    print(f"Monitoring departure-from-Videle time | itinerary={'auto' if itinerary_id is None else itinerary_id}")
    last_target: Optional[datetime] = None
    alarm_active = False
    last_beep = 0.0

    # Initial test ping
    try:
        s0 = scrape(url, itinerary_id, tzinfo)
        if s0.found and s0.target_dt:
            rem = int((s0.target_dt - datetime.now(tzinfo)).total_seconds() // 60)
            notify(
                "CFR Alert started",
                f"{s0.card_id} | dep_sched {s0.dep_sched:%H:%M} | delay {s0.delay_min}m | depart {s0.target_dt:%H:%M} | ~{rem}m"
            )
            print(f"[START] card={s0.card_id} dep_sched={s0.dep_sched:%H:%M} delay={s0.delay_min}m depart={s0.target_dt:%H:%M} left≈{rem}m")
            last_target = s0.target_dt
        else:
            notify("CFR Alert started", "Card not parsed; will retry.")
            print("[START] " + s0.note)
    except Exception as e:
        notify("Start error", str(e))

    while True:
        try:
            snap = scrape(url, itinerary_id, tzinfo)
            now = datetime.now(tzinfo)

            if not snap.found or not snap.target_dt:
                print(f"[{now:%H:%M:%S}] not found: {snap.note}")
                time.sleep(interval_s)
                continue

            remaining = int((snap.target_dt - now).total_seconds() // 60)
            target_changed = (last_target is None) or (abs((snap.target_dt - last_target).total_seconds()) >= 60)

            hrs, mins = divmod(remaining, 60)
            left_str = f"{hrs}h {mins}m" if hrs > 0 else f"{mins}m"
            print(f"[{now:%H:%M:%S}] card={snap.card_id} delay={snap.delay_min}m depart={snap.target_dt:%H:%M} left≈{left_str}")

            if target_changed:
                last_target = snap.target_dt
                alarm_active = False  # re-arm after ETA change

            if remaining <= notify_at_min and remaining > 0:
                if not alarm_active:
                    alarm_active = True
                    notify(
                        "30 min until train reaches Videle (ready to depart)",
                        f"{snap.card_id} depart {snap.target_dt:%H:%M} (delay {snap.delay_min}m)"
                    )
                    for _ in range(3):
                        beep()
                        time.sleep(0.25)
                else:
                    if time.time() - last_beep >= alarm_gap_s:
                        beep()
                        last_beep = time.time()
            else:
                alarm_active = False

            if remaining <= 0:
                notify("Train is at Videle / departing now", f"{snap.card_id} {snap.target_dt:%H:%M}")
                for _ in range(2):
                    beep()
                    time.sleep(0.25)
                break

        except Exception as e:
            print(f"[ERR] {e}")

        time.sleep(interval_s)

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Alert 30 min before train reaches Videle (actual depart time).")
    ap.add_argument("--url", default=ROUTE_URL_DEFAULT)
    ap.add_argument("--itinerary", type=int, default=13)  # change if card id changes
    ap.add_argument("--tz", default="Europe/Bucharest")
    ap.add_argument("--interval", type=int, default=120)
    ap.add_argument("--notify-at", type=int, default=30)
    ap.add_argument("--alarm-gap", type=int, default=10)
    args = ap.parse_args()
    run_monitor(args.url, args.itinerary, args.tz, args.interval, args.notify_at, args.alarm_gap)

if __name__ == "__main__":
    main()
