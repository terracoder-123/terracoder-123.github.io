#!/usr/bin/env python3
"""Daily job hunt for Althaf Rismy.

Pulls fresh listings from Seek (public search API) and Indeed (results saved
from the Indeed connector), scores them against profile.json with Adelaide
weighted highest, and keeps a ledger so a job is never shown twice.

  python3 hunt.py search            # Seek + saved Indeed results -> ranked shortlist
  python3 hunt.py detail N          # full job description for shortlist item N
  python3 hunt.py skip N "reason"   # reject item N after reading the ad
  python3 hunt.py finish            # write today's digest and update the ledger

Cover letters are written with letter.py. See RUNBOOK.md for the daily routine.
"""

import argparse
import datetime as dt
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
PROFILE = json.loads((ROOT / "profile.json").read_text())
LEDGER = ROOT / "ledger.json"
TZ = ZoneInfo("Australia/Adelaide")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"

SEEK_SEARCH = "https://www.seek.com.au/api/jobsearch/v5/search"
SEEK_GRAPHQL = "https://www.seek.com.au/graphql"
SEEK_DETAIL_QUERY = """query jobDetails($jobId: ID!, $locale: Locale!) {
  jobDetails(id: $jobId) { job {
    id title content(platform: WEB)
    advertiser { name(locale: $locale) }
    location { label(locale: $locale, type: LONG) }
    workTypes { label(locale: $locale) }
    salary { label }
  } } }"""

CAPITALS = {"adelaide": "SA", "melbourne": "VIC", "sydney": "NSW", "brisbane": "QLD",
            "perth": "WA", "hobart": "TAS", "darwin": "NT", "canberra": "ACT"}
STATE_CAPITAL = {v: k.title() for k, v in CAPITALS.items()}
RELEVANT = re.compile(r"data|analy|insight|intelligence|\bbi\b|reporting|scien|python|\bsql\b|machine learning|graph|quantitative|statistic")


def today():
    return dt.datetime.now(TZ).date().isoformat()


def run_dir(day=None):
    d = ROOT / "runs" / (day or today())
    d.mkdir(parents=True, exist_ok=True)
    return d


def out_dir(day=None):
    d = ROOT / "out" / (day or today())
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def http(url, body=None, headers=None, tries=3):
    hdrs = {"User-Agent": UA, "Accept": "application/json"}
    hdrs.update(headers or {})
    data = json.dumps(body).encode() if body is not None else None
    if data:
        hdrs["Content-Type"] = "application/json"
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=hdrs), timeout=30) as r:
                return json.loads(r.read().decode())
        except Exception as e:  # network hiccups and 5xx: back off and retry
            if attempt == tries - 1:
                raise
            print(f"  retry after error: {e}", file=sys.stderr)
            time.sleep(2 * (attempt + 1))


def norm(s):
    s = (s or "").lower()
    s = re.sub(r"\b(pty|ltd|limited|inc|group|australia|the)\b", " ", s)
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def job_key(title, company):
    return f"{norm(title)}|{norm(company)}"


def html_to_text(h):
    h = re.sub(r"(?i)<li[^>]*>", "\n- ", h or "")
    h = re.sub(r"(?i)<br\s*/?>|</p>|</h\d>|</ul>|</div>", "\n", h)
    t = html.unescape(re.sub(r"<[^>]+>", "", h))
    return re.sub(r"\n\s*\n+", "\n\n", t).strip()


# ---------------------------------------------------------------- sources

def seek_jobs(days):
    s = PROFILE["search"]
    found = {}
    for where in s["seek_locations"]:
        for kw in s["keywords"]:
            for page in range(1, s["seek_pages"] + 1):
                q = dict(siteKey="AU-Main", sourcesystem="houston", where=where, keywords=kw,
                         page=page, pageSize=30, daterange=days, locale="en-AU")
                try:
                    data = http(SEEK_SEARCH + "?" + urllib.parse.urlencode(q))
                except Exception as e:
                    print(f"  Seek search failed ({kw} / {where}): {e}", file=sys.stderr)
                    break
                rows = data.get("data", [])
                for j in rows:
                    found.setdefault(j["id"], seek_normalise(j))
                if len(rows) < 30:
                    break
                time.sleep(0.5)
    print(f"Seek: {len(found)} unique listings")
    return list(found.values())


def seek_normalise(j):
    loc = (j.get("locations") or [{}])[0]
    arrangements = [a["label"]["text"] for a in (j.get("workArrangements") or {}).get("data", [])]
    company = j.get("companyName") or (j.get("advertiser") or {}).get("description", "")
    return {
        "source": "seek",
        "seek_id": j["id"],
        "title": j.get("title", "").strip(),
        "company": company.strip(),
        "location": loc.get("label", ""),
        "location_detail": " / ".join([h.get("contextualName", "") for h in loc.get("seoHierarchy", [])] + arrangements),
        "posted": (j.get("listingDate") or "")[:10],
        "work_type": ", ".join(j.get("workTypes") or []),
        "salary": j.get("salaryLabel", ""),
        "summary": " ".join([j.get("teaser", "")] + (j.get("bulletPoints") or [])),
        "url": f"https://www.seek.com.au/job/{j['id']}",
        "apply_url": f"https://www.seek.com.au/job/{j['id']}/apply",
    }


def indeed_records(text):
    """Yield field dicts from Indeed connector output: either the raw markdown blocks
    or compact lines `Job Id | Title | Company | Location | Posted on | URL`."""
    try:
        text = json.loads(text)["result"]
    except Exception:
        text = text.replace("\\n", "\n")
    for line in text.splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 6 and parts[0].startswith("JOBSEARCH_"):
            yield dict(zip(["Job Id", "Job Title", "Company", "Location", "Posted on", "View Job URL"], parts))
    for block in re.split(r"\n\s*\n(?=\s*\*\*Job Title)", text):
        fields = dict(re.findall(r"\*\*([^*:]+):\*\*\s*(.*)", block))
        if fields.get("Job Title"):
            yield fields


def indeed_jobs(day):
    """Parse Indeed connector results the agent saved to runs/<day>/indeed/*."""
    jobs = {}
    for f in sorted((run_dir(day) / "indeed").glob("*")):
        for fields in indeed_records(f.read_text()):
            posted = fields.get("Posted on", "").strip()
            try:
                posted = dt.datetime.strptime(posted, "%B %d, %Y").date().isoformat()
            except ValueError:
                posted = ""
            job = {
                "source": "indeed",
                "indeed_job_id": fields.get("Job Id", "").strip(),
                "title": fields["Job Title"].strip(),
                "company": fields.get("Company", "").strip(),
                "location": fields.get("Location", "").strip(),
                "location_detail": "",
                "posted": posted,
                "work_type": fields.get("Job Type", "").strip().replace("N/A", ""),
                "salary": fields.get("Compensation", "").strip().replace("N/A", ""),
                "summary": "",
                "url": fields.get("View Job URL", "").strip(),
                "apply_url": fields.get("View Job URL", "").strip(),
            }
            jobs.setdefault(job_key(job["title"], job["company"]) + "|" + norm(job["location"]), job)
    print(f"Indeed: {len(jobs)} unique listings from {len(list((run_dir(day) / 'indeed').glob('*')))} saved searches")
    return list(jobs.values())


# ---------------------------------------------------------------- scoring

def location_tier(job):
    """Return (tier, city, relocation-mode) for a job's location."""
    loc = f"{job['location']} {job.get('location_detail', '')}"
    low = loc.lower()
    state = next((st for st in ("ACT", "NSW", "VIC", "QLD", "TAS", "SA", "WA", "NT")
                  if re.search(rf"\b{st}\b", loc)), "")
    if "adelaide" in low:
        return "adelaide", "Adelaide", "adelaide"
    if state == "SA":
        town = re.sub(r"\bSA\b.*", "", job["location"]).split(",")[-1].strip() or "South Australia"
        return "south_australia", town, "south_australia"
    if re.search(r"\b(remote|work from home|wfh)\b", low) and not re.search(r"on-site|hybrid", low):
        return "remote", "", "remote"
    for city, st in CAPITALS.items():
        if city in low:
            mode = "home" if city == PROFILE["applicant"]["home_city"].lower() else "other"
            return ("melbourne" if mode == "home" else "other_capital"), city.title(), mode
    if state:
        town = re.sub(rf"\b{state}\b.*", "", job["location"]).split(",")[-1].strip() or STATE_CAPITAL[state]
        return "regional", town, "other"
    return "regional", job["location"], "other"


def score(job):
    sc = PROFILE["scoring"]
    title = f" {job['title'].lower()} "
    text = f"{title} {job.get('summary', '').lower()} {job.get('description', '').lower()}"
    pts, why, flags = 0, [], []

    if not RELEVANT.search(title):
        return -100, ["title not data/analytics"], flags
    if any(term in title for term in sc["exclude_terms"]):
        return -100, ["excluded role type"], flags

    t = sum(v for term, v in sc["title_terms"].items() if term in title)
    pts += min(t, 60)
    why.append(f"title +{min(t, 60)}")

    b = sum(v for term, v in sc["body_terms"].items() if term in text)
    if b:
        pts += min(b, 20)
        why.append(f"skills +{min(b, 20)}")

    if any(re.search(rf"(?<![a-z]){re.escape(term.strip())}(?![a-z])", title) for term in sc["senior_terms"]):
        pts -= sc["senior_penalty"]
        why.append(f"senior -{sc['senior_penalty']}")
    if re.search(sc["experience_regex"], text):
        pts -= sc["experience_penalty"]
        why.append(f"3+ yrs exp -{sc['experience_penalty']}")
    if re.search(sc["clearance_regex"], text, re.I):
        flags.append("clearance/citizenship")
        if not PROFILE["eligibility"]["australian_citizen"]:
            pts -= sc["clearance_penalty"]
            why.append(f"clearance -{sc['clearance_penalty']}")

    tier, city, mode = location_tier(job)
    job.update(tier=tier, city=city, relocation=mode)
    lp = sc["location"][tier]
    pts += lp
    why.append(f"{tier} +{lp}")

    if job.get("posted"):
        age = (dt.date.fromisoformat(today()) - dt.date.fromisoformat(job["posted"])).days
        r = sc["recency"]
        bonus = r["le_2_days"] if age <= 2 else r["le_7_days"] if age <= 7 else r["gt_30_days"] if age > 30 else 0
        if bonus:
            pts += bonus
            why.append(f"age {age}d {bonus:+d}")
    return pts, why, flags


# ---------------------------------------------------------------- commands

def cmd_search(args):
    day = today()
    ledger = load_json(LEDGER, [])
    seen = {e["key"] for e in ledger}

    merged = {}
    for job in seek_jobs(args.days or PROFILE["search"]["seek_days"]) + indeed_jobs(day):
        key = job_key(job["title"], job["company"])
        if key in merged:  # same ad on both boards: keep Seek, remember the Indeed link
            if job["source"] == "indeed":
                merged[key].setdefault("also_on", job["url"])
            continue
        job["key"] = key
        merged[key] = job

    fresh = [j for j in merged.values() if j["key"] not in seen]
    for j in fresh:
        j["score"], j["why"], j["flags"] = score(j)
    shortlist = sorted((j for j in fresh if j["score"] >= PROFILE["search"]["min_score"]),
                       key=lambda j: -j["score"])
    for i, j in enumerate(shortlist, 1):
        j["n"] = i
    save_json(run_dir(day) / "shortlist.json", shortlist)
    print(f"{len(merged)} unique jobs, {len(merged) - len(fresh)} already in ledger, "
          f"{len(shortlist)} scored >= {PROFILE['search']['min_score']}\n")
    print_table(shortlist[: args.top])


def print_table(jobs):
    for j in jobs:
        flag = f"  [{', '.join(j['flags'])}]" if j["flags"] else ""
        print(f"{j['n']:>3}. {j['score']:>3}  {j['title'][:55]:<55} | {j['company'][:28]:<28} | "
              f"{j['location'][:30]:<30} | {j['source']} {j['posted']}{flag}")


def shortlist_item(n):
    items = load_json(run_dir() / "shortlist.json", [])
    for j in items:
        if j["n"] == n:
            return j, items
    sys.exit(f"No shortlist item {n}. Run `python3 hunt.py search` first.")


def cmd_detail(args):
    job, items = shortlist_item(args.n)
    if job["source"] == "indeed":
        print(f"Indeed listing. Fetch the description with the Indeed connector:\n"
              f"  get_job_details(job_id=\"{job['indeed_job_id']}\")\n"
              f"then save it with:  python3 hunt.py describe {args.n} <file>")
        return
    data = http(SEEK_GRAPHQL, {"operationName": "jobDetails", "query": SEEK_DETAIL_QUERY,
                               "variables": {"jobId": job["seek_id"], "locale": "en-AU"}},
                {"seek-request-brand": "seek", "seek-request-country": "AU"})
    d = data["data"]["jobDetails"]["job"]
    store_description(job, items, html_to_text(d["content"]))
    print(f"# {d['title']} | {d['advertiser']['name']} | {d['location']['label']}")
    print(f"# {job['url']}  score {job['score']} ({', '.join(job['why'])})  flags: {job['flags'] or 'none'}\n")
    print(job["description"])


def cmd_describe(args):
    job, items = shortlist_item(args.n)
    store_description(job, items, Path(args.file).read_text())
    print(f"Saved description for #{args.n}. score {job['score']} ({', '.join(job['why'])}) flags: {job['flags'] or 'none'}")


def store_description(job, items, text):
    job["description"] = text
    job["score"], job["why"], job["flags"] = score(job)  # rescore with the full ad
    save_json(run_dir() / "shortlist.json", items)


def cmd_skip(args):
    job, _ = shortlist_item(args.n)
    apps = load_json(run_dir() / "applications.json", [])
    apps = [a for a in apps if a["n"] != args.n]
    apps.append({"n": args.n, "status": "skipped", "reason": args.reason, "key": job["key"]})
    save_json(run_dir() / "applications.json", apps)
    print(f"Skipped #{args.n} {job['title']} ({args.reason})")


def cmd_finish(args):
    day = today()
    items = {j["n"]: j for j in load_json(run_dir(day) / "shortlist.json", [])}
    apps = load_json(run_dir(day) / "applications.json", [])
    done = {a["n"]: a for a in apps}
    letters = [(items[n], a) for n, a in done.items() if a["status"] == "letter"]
    letters.sort(key=lambda p: -p[0]["score"])
    skipped = [(items[n], a) for n, a in done.items() if a["status"] == "skipped"]
    rest = [j for n, j in items.items() if n not in done][:15]

    lines = [f"# Job hunt, {dt.date.fromisoformat(day).strftime('%A %d %B %Y')}", ""]
    lines += [f"{len(letters)} cover letters written. Adelaide and South Australia roles are ranked first.", ""]
    if letters:
        lines += ["## Ready to apply", "", "| # | Role | Company | Location | Score | Apply | Cover letter |",
                  "|---|---|---|---|---|---|---|"]
        for i, (j, a) in enumerate(letters, 1):
            lines.append(f"| {i} | {j['title']} | {j['company']} | {j['location']} | {j['score']} | "
                         f"[{j['source'].title()}]({j['apply_url']}) | {a['file']} |")
        lines.append("")
    if skipped:
        lines += ["## Read but not a fit", ""]
        lines += [f"- [{j['title']} | {j['company']} | {j['location']}]({j['url']}): {a['reason']}" for j, a in skipped]
        lines.append("")
    if rest:
        lines += ["## Also matched (no letter yet, may come up again tomorrow)", ""]
        lines += [f"- [{j['title']} | {j['company']} | {j['location']}]({j['url']}) score {j['score']}"
                  + (f" ({', '.join(j['flags'])})" if j["flags"] else "") for j in rest]
        lines.append("")
    digest = out_dir(day) / f"digest-{day}.md"
    digest.write_text("\n".join(lines))

    ledger = load_json(LEDGER, [])
    seen = {e["key"] for e in ledger}
    for j, a in letters + skipped:
        if j["key"] not in seen:
            ledger.append({"key": j["key"], "date": day, "status": a["status"], "source": j["source"],
                           "title": j["title"], "company": j["company"], "location": j["location"],
                           "url": j["url"]})
    save_json(LEDGER, ledger)
    print("\n".join(lines))
    print(f"\nDigest: {digest}\nLedger now holds {len(ledger)} jobs.")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search"); s.add_argument("--top", type=int, default=30)
    s.add_argument("--days", type=int, help="Seek listing age in days (default from profile.json)"); s.set_defaults(fn=cmd_search)
    s = sub.add_parser("detail"); s.add_argument("n", type=int); s.set_defaults(fn=cmd_detail)
    s = sub.add_parser("describe"); s.add_argument("n", type=int); s.add_argument("file"); s.set_defaults(fn=cmd_describe)
    s = sub.add_parser("skip"); s.add_argument("n", type=int); s.add_argument("reason"); s.set_defaults(fn=cmd_skip)
    s = sub.add_parser("finish"); s.set_defaults(fn=cmd_finish)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
