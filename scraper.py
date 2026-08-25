#!/usr/bin/env python3
"""
Pro Kickball Reference - Data Scraper
Pulls Vaxxed & Waxxed game data from madisonssc.com,
updates index.html, and exports a CSV.
"""

import requests
from bs4 import BeautifulSoup
import re
import csv
import os
import sys
from datetime import datetime, date

# ── Config ────────────────────────────────────────────────────────────────────

LOGIN_URL  = "https://www.madisonssc.com/login"
USERNAME   = "marzottn@gmail.com"
PASSWORD   = "football1"
TEAM_ID    = "1040143"
TEAM_URL   = f"https://www.madisonssc.com/team/{TEAM_ID}"

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_PATH  = os.path.join(SCRIPT_DIR, "index.html")
CSV_PATH   = os.path.join(SCRIPT_DIR, "games.csv")

# All kickball leagues Nick's team has participated in.
# Format: league_id → season_name (derived from first game date + league name)
LEAGUE_MAP = {
    41794:  "Summer 2021",
    43701:  "Fall 2021",
    49860:  "Spring 2022",
    51877:  "Summer 2022",
    53145:  "Fall 2022",
    59299:  "Spring 2023",
    63281:  "Summer 2023",
    64994:  "Fall 2023",
    71425:  "Spring 2024",
    74567:  "Summer 2024",
    77400:  "Fall 2024",
    84674:  "Spring 2025",
    88162:  "Summer 2025",
    90491:  "Fall 2025",
    96912:  "Spring 2026",
    100734: "Summer 2026",
    104618: "Fall 2026",
}

# ── Login ─────────────────────────────────────────────────────────────────────

def login():
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0"})
    r = session.get(LOGIN_URL)
    soup = BeautifulSoup(r.text, "html.parser")
    token = soup.find("input", {"name": "reqToken"})["value"]
    session.post(LOGIN_URL, data={
        "Username": USERNAME,
        "Password": PASSWORD,
        "reqToken": token,
        "cmd": "processLogin",
        "RememberMe": "1",
    }, allow_redirects=True)
    return session

# ── Scrape current season ─────────────────────────────────────────────────────

def season_label_from_league(league_name, game_date_str):
    """
    Determine season label from the league name and game date year.
    e.g. 'Fall Wednesday Co-ed Kickball' + '2026-08-19' → 'Fall 2026'
    """
    year = game_date_str[:4]
    name_lower = league_name.lower()
    if "spring" in name_lower:
        part = "Spring"
    elif "summer" in name_lower:
        part = "Summer"
    elif "fall" in name_lower:
        part = "Fall"
    else:
        # Fallback: infer from month
        m = int(game_date_str[5:7])
        part = "Spring" if m <= 5 else ("Fall" if m >= 9 else "Summer")
    return f"{part} {year}"

def get_current_league_name(session):
    """Return the league name string from the team page league links."""
    r = session.get(TEAM_URL)
    soup = BeautifulSoup(r.text, "html.parser")
    # The league name appears in the leagueName container
    el = soup.find("div", {"class": "value leagueName"})
    return el.get_text(strip=True) if el else ""

def scrape_current_season(session):
    """Return list of completed game dicts from the team page."""
    league_name = get_current_league_name(session)
    print(f"Current league: {league_name}")
    r = session.get(TEAM_URL)
    soup = BeautifulSoup(r.text, "html.parser")
    table = soup.find("table", {"id": "teamScheduleTable"})
    if not table:
        print("ERROR: Could not find team schedule table.")
        return []

    games = []
    current_date = None

    for row in table.find_all("tr"):
        # Date header row
        date_cell = row.find("td", {"class": "gameDate"})
        if date_cell:
            # Pull date from the detail link in the NEXT game row via data attr
            # Instead parse from the row id of the next sibling
            # The gameDate row has a sibling game row with id="game_GAMEID_LEAGUEID"
            # We'll grab date from the detailLink cell id: "game_YYYY-MM-DD_..."
            current_date = None  # will be set when we hit the game row
            continue

        # Game row
        result_cell = row.find("td", {"class": "result"})
        opp_cell    = row.find("td", {"class": "opponent"})
        detail_cell = row.find("td", {"class": "detailLink"})

        if not opp_cell or not detail_cell:
            continue

        # Extract date from detailLink cell id: "game_2026-08-19_8-30 PM_764_1"
        detail_id = detail_cell.get("id", "")
        date_match = re.search(r"game_(\d{4}-\d{2}-\d{2})_", detail_id)
        if date_match:
            current_date = date_match.group(1)

        # Skip future games (no result)
        if not result_cell or not current_date:
            continue

        result_text = result_cell.get_text(" ", strip=True)
        # result_text like "Win 3 - 1" or "Loss 1 - 3" or "Tie 2 - 2"
        outcome_match = re.match(r"(Win|Loss|Tie)\s+(\d+)\s*-\s*(\d+)", result_text)
        if not outcome_match:
            continue

        outcome = outcome_match.group(1)
        score1  = int(outcome_match.group(2))
        score2  = int(outcome_match.group(3))

        # Determine home/away to get rs/ra right
        home_away = opp_cell.find("div", {"class": "homeOrVisitor"})
        home_away_text = home_away.get_text(strip=True) if home_away else "Home"

        # rs = our runs, ra = opponent runs
        if home_away_text == "Home":
            rs, ra = score1, score2
        else:
            rs, ra = score1, score2  # site always shows our score first

        opp_link = opp_cell.find("a")
        opp_name = opp_link.get_text(strip=True) if opp_link else "Unknown"

        score_str = f"{rs} – {ra}"
        margin    = rs - ra

        games.append({
            "season":  season_label_from_league(league_name, current_date),
            "date":    current_date,
            "opp":     opp_name,
            "outcome": outcome,
            "score":   score_str,
            "rs":      rs,
            "ra":      ra,
            "margin":  margin,
        })

    return games

# ── Parse existing HTML data ──────────────────────────────────────────────────

def extract_js_array(html, var_name):
    """Extract the raw JS array string for a given const name."""
    pattern = rf"const {var_name}\s*=\s*(\[.*?\]);"
    m = re.search(pattern, html, re.DOTALL)
    return m.group(1) if m else None

def parse_js_entry(entry_str, bool_keys=None):
    """Parse a single JS object literal string into a Python dict."""
    bool_keys = bool_keys or set()
    obj = {}
    # String fields: handles 'value', "value", escaped chars like \' and \"
    for m in re.finditer(r'''(\w+)\s*:\s*(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")''', entry_str):
        raw = m.group(2) if m.group(2) is not None else m.group(3)
        # Unescape \\' → ' and \\" → "
        raw = raw.replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\")
        obj[m.group(1)] = raw
    # Boolean fields: key:true/false
    for m in re.finditer(r"(\w+)\s*:\s*(true|false)", entry_str):
        obj[m.group(1)] = m.group(2) == "true"
    # Integer fields: key:N (skip if already set as string/bool)
    for m in re.finditer(r"(\w+)\s*:\s*(-?\d+)", entry_str):
        k = m.group(1)
        if k not in obj:
            obj[k] = int(m.group(2))
    return obj

REQUIRED_GAME_KEYS = {"season", "date", "opp", "outcome", "score"}

def parse_games_from_html(html):
    """Parse existing GAMES array from the HTML file."""
    raw = extract_js_array(html, "GAMES")
    if not raw:
        return []
    games = []
    for entry in re.finditer(r"\{([^}]+)\}", raw):
        obj = parse_js_entry(entry.group(1))
        if REQUIRED_GAME_KEYS.issubset(obj.keys()):
            games.append(obj)
        elif "date" in obj:
            print(f"WARNING: Skipping malformed game entry (missing keys): {obj.get('date')} {obj.get('opp','?')} — keys found: {set(obj.keys())}")
    return games

def parse_seasons_from_html(html):
    """Parse existing SEASONS array from the HTML file."""
    raw = extract_js_array(html, "SEASONS")
    if not raw:
        return []
    seasons = []
    for entry in re.finditer(r"\{([^}]+)\}", raw):
        obj = parse_js_entry(entry.group(1), bool_keys={"champ"})
        if "season" in obj:
            seasons.append(obj)
    return seasons

# ── Build updated JS arrays ───────────────────────────────────────────────────

def build_season_summary(season_name, games):
    """Compute a SEASONS entry from a list of game dicts for that season."""
    sg = [g for g in games if g["season"] == season_name]
    w  = sum(1 for g in sg if g["outcome"] == "Win")
    l  = sum(1 for g in sg if g["outcome"] == "Loss")
    t  = sum(1 for g in sg if g["outcome"] == "Tie")
    rs = sum(g["rs"] for g in sg)
    ra = sum(g["ra"] for g in sg)
    return {
        "season":  season_name,
        "w": w, "l": l, "t": t,
        "rs": rs, "ra": ra,
        "seed": 0, "teams": 0,
        "outcome": "Season in Progress",
        "result": "—",
        "opp": "TBD",
        "champ": False,
    }

def qs(s):
    """Quote a string for JS using double-quotes with proper escaping."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'

def game_to_js(g):
    return (
        f"  {{season:{qs(g['season'])},date:{qs(g['date'])},opp:{qs(g['opp'])},"
        f"outcome:{qs(g['outcome'])},score:{qs(g['score'])},"
        f"rs:{g['rs']},ra:{g['ra']},margin:{g['margin']}}}"
    )

def season_to_js(s):
    champ = "true" if s.get("champ") else "false"
    return (
        f"  {{ season:{qs(s['season'])}, w:{s['w']}, l:{s['l']}, t:{s['t']}, "
        f"rs:{s['rs']},  ra:{s['ra']},  seed:{s.get('seed',0)}, teams:{s.get('teams',0)},  "
        f"outcome:{qs(s['outcome'])},  result:{qs(s['result'])},      "
        f"opp:{qs(s['opp'])},               champ:{champ}  }}"
    )

# ── Merge and update HTML ─────────────────────────────────────────────────────

def update_html(new_games):
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    existing_games   = parse_games_from_html(html)
    existing_seasons = parse_seasons_from_html(html)

    # Build a set of existing game keys (date + opp) for dedup
    existing_keys = {(g["date"], g["opp"]) for g in existing_games}

    added = []
    for g in new_games:
        key = (g["date"], g["opp"])
        if key not in existing_keys:
            existing_games.append(g)
            added.append(g)
            existing_keys.add(key)

    if not added:
        print("No new games to add.")
    else:
        print(f"Adding {len(added)} new game(s):")
        for g in added:
            print(f"  {g['date']} vs {g['opp']}: {g['outcome']} {g['score']}")

    # Sort games by date
    existing_games.sort(key=lambda g: g["date"])

    # Update or add the current season summary in SEASONS
    current_seasons_scraped = {g["season"] for g in new_games}
    existing_season_names   = {s["season"] for s in existing_seasons}

    for season_name in current_seasons_scraped:
        summary = build_season_summary(season_name, existing_games)
        if season_name in existing_season_names:
            # Preserve existing playoff/champ data if already set
            for i, s in enumerate(existing_seasons):
                if s["season"] == season_name:
                    if s.get("outcome", "").startswith("Season in Progress") or s.get("outcome", "") == "—":
                        existing_seasons[i].update({
                            "w": summary["w"], "l": summary["l"], "t": summary["t"],
                            "rs": summary["rs"], "ra": summary["ra"],
                        })
                    break
        else:
            existing_seasons.append(summary)
            print(f"Added new season: {season_name}")

    # Rebuild JS arrays
    games_js   = "[\n" + ",\n".join(game_to_js(g) for g in existing_games) + "\n]"
    seasons_js = "[\n" + ",\n".join(season_to_js(s) for s in existing_seasons) + "\n]"

    s_js = f"const SEASONS = {seasons_js};"
    g_js = f"const GAMES = {games_js};"
    html = re.sub(r"const SEASONS\s*=\s*\[.*?\];", lambda m: s_js, html, flags=re.DOTALL)
    html = re.sub(r"const GAMES\s*=\s*\[.*?\];",   lambda m: g_js, html, flags=re.DOTALL)

    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"HTML updated: {HTML_PATH}")
    return existing_games, existing_seasons

# ── Scrape all-league game data ───────────────────────────────────────────────

def scrape_league_games(session, league_id, season_name):
    """Return all completed games from a league schedule (both teams, not just V&W)."""
    import time
    r = session.get(f"https://www.madisonssc.com/league/{league_id}/schedule")
    soup = BeautifulSoup(r.text, "html.parser")
    games = []
    for cell in soup.find_all("td", attrs={"data-gamedate": True}):
        date   = cell.get("data-gamedate")
        t1_id  = cell.get("data-teamoneid")
        t2_id  = cell.get("data-teamtwoid")
        t1_lnk = cell.find("a", {"class": "gameCellTeamOne"})
        t2_lnk = cell.find("a", {"class": "gameCellTeamTwo"})
        scores = cell.find_all("span", {"class": "scoreDisplay"})
        if not (t1_lnk and t2_lnk and len(scores) >= 2):
            continue
        m1 = re.match(r"\[(\d+)\]", scores[0].get_text(strip=True))
        m2 = re.match(r"\[(\d+)\]", scores[1].get_text(strip=True))
        if not (m1 and m2):
            continue
        games.append({
            "date":    date,
            "season":  season_name,
            "team1":   t1_lnk.get_text(strip=True),
            "id1":     int(t1_id),
            "rs1":     int(m1.group(1)),
            "team2":   t2_lnk.get_text(strip=True),
            "id2":     int(t2_id),
            "rs2":     int(m2.group(1)),
        })
    return games

def scrape_all_league_games(session):
    """Scrape all leagues in LEAGUE_MAP and return combined game list."""
    all_games = []
    for lid, season in LEAGUE_MAP.items():
        games = scrape_league_games(session, lid, season)
        print(f"  {season} (league {lid}): {len(games)} games")
        all_games.extend(games)
    all_games.sort(key=lambda g: g["date"])
    return all_games

def league_game_to_js(g):
    def q(s):
        # Escape backslashes and double-quotes, wrap in double quotes (JSON-safe)
        s = str(s).replace("\\", "\\\\").replace('"', '\\"')
        return f'"{s}"'
    return (
        f"  {{date:{q(g['date'])},season:{q(g['season'])},"
        f"team1:{q(g['team1'])},id1:{g['id1']},rs1:{g['rs1']},"
        f"team2:{q(g['team2'])},id2:{g['id2']},rs2:{g['rs2']}}}"
    )

def update_html_all_league_games(all_games):
    """Write ALL_LEAGUE_GAMES const into the HTML, inserting it if not present."""
    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    js_array = "[\n" + ",\n".join(league_game_to_js(g) for g in all_games) + "\n]"
    new_const = f"const ALL_LEAGUE_GAMES = {js_array};"

    if "const ALL_LEAGUE_GAMES" in html:
        html = re.sub(r"const ALL_LEAGUE_GAMES\s*=\s*\[.*?\];", lambda m: new_const, html, flags=re.DOTALL)
    else:
        # Replace the placeholder comment with the actual data
        html = html.replace("// ALL_LEAGUE_GAMES is injected here by scraper.py", new_const, 1)

    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"ALL_LEAGUE_GAMES updated: {len(all_games)} games across {len(LEAGUE_MAP)} leagues")

# ── Export CSV ────────────────────────────────────────────────────────────────

def export_csv(games):
    fieldnames = ["season", "date", "opp", "outcome", "score", "rs", "ra", "margin"]
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for g in games:
            writer.writerow({k: g.get(k, "") for k in fieldnames})
    print(f"CSV exported: {CSV_PATH} ({len(games)} games)")

# ── Playoff update ────────────────────────────────────────────────────────────

OUTCOME_SHORTCUTS = {
    "champ":  "WIN Championship",
    "finals": "Loss in Championship",
    "semis":  "Loss in Semifinals",
    "qtrs":   "Loss in Quarterfinal",
}

def cmd_playoff(args):
    """
    Update a season's playoff result in the HTML.
    Usage:
      python3 scraper.py playoff "Fall 2026" champ "4-2" "Just the Tipsy" 1 6
      python3 scraper.py playoff "Fall 2026" finals "2-5" "Average and Savage" 2 6
      python3 scraper.py playoff "Fall 2026" semis "1-3" "Pirates" 3 6
      python3 scraper.py playoff "Fall 2026" qtrs "0-4" "Team X" 4 6

    outcome shortcuts: champ | finals | semis | qtrs
    Or use a full string in quotes: "Loss in First Round"
    """
    if len(args) < 6:
        print("Usage: python3 scraper.py playoff <season> <outcome> <score> <opponent> <seed> <teams>")
        print("  outcome shortcuts: champ | finals | semis | qtrs")
        print('  Example: python3 scraper.py playoff "Fall 2026" champ "4-2" "Just the Tipsy" 1 6')
        sys.exit(1)

    season_name = args[0]
    outcome_raw = args[1]
    score       = args[2]
    opp         = args[3]
    seed        = int(args[4])
    teams       = int(args[5])

    outcome = OUTCOME_SHORTCUTS.get(outcome_raw.lower(), outcome_raw)
    champ   = outcome_raw.lower() == "champ" or outcome.startswith("WIN")

    with open(HTML_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    seasons = parse_seasons_from_html(html)
    games   = parse_games_from_html(html)

    matched = False
    for s in seasons:
        if s["season"] == season_name:
            s["outcome"] = outcome
            s["result"]  = score
            s["opp"]     = opp
            s["seed"]    = seed
            s["teams"]   = teams
            s["champ"]   = champ
            matched = True
            break

    if not matched:
        print(f"ERROR: Season '{season_name}' not found. Available seasons:")
        for s in seasons:
            print(f"  {s['season']}")
        sys.exit(1)

    games_js   = "[\n" + ",\n".join(game_to_js(g) for g in games) + "\n]"
    seasons_js = "[\n" + ",\n".join(season_to_js(s) for s in seasons) + "\n]"

    s_js2 = f"const SEASONS = {seasons_js};"
    g_js2 = f"const GAMES = {games_js};"
    html = re.sub(r"const SEASONS\s*=\s*\[.*?\];", lambda m: s_js2, html, flags=re.DOTALL)
    html = re.sub(r"const GAMES\s*=\s*\[.*?\];",   lambda m: g_js2, html, flags=re.DOTALL)

    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    champ_str = " 🏆" if champ else ""
    print(f"Updated {season_name}: {outcome} ({score} vs {opp}), Seed {seed}/{teams}{champ_str}")
    print(f"HTML updated: {HTML_PATH}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "playoff":
        cmd_playoff(sys.argv[2:])
        return

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] Starting scrape...")

    session   = login()
    print("Logged in.")

    new_games = scrape_current_season(session)
    print(f"Scraped {len(new_games)} completed game(s) from current season.")

    all_games, _ = update_html(new_games)
    export_csv(all_games)

    print("Scraping all league games for Teams tab...")
    league_games = scrape_all_league_games(session)
    update_html_all_league_games(league_games)

    print("Done.")

if __name__ == "__main__":
    main()
