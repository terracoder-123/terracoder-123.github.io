# Job hunter

A daily job search for Althaf Rismy (Data Analyst). Every morning a scheduled Claude
session:

1. searches **Seek** (public search API) and **Indeed** (Indeed connector) for data
   analyst, BI, data science, data engineering and graduate roles across Australia,
2. scores each job against `profile.json`, with **Adelaide and South Australia ranked
   highest**, then remote, Melbourne and the other capitals,
3. reads the full ads, skips roles that need citizenship or a clearance, senior roles and
   roles asking for 4+ years,
4. writes up to 10 tailored one-page cover letters (`.docx`, same layout as Althaf's own),
   each one stating that Althaf will relocate to the job's city,
5. sends the letters and a digest with the apply links. Each run only looks at ads from the
   last day, and `ledger.json` records handled jobs so nothing is shown twice.

Applications are **not** submitted automatically: Seek and Indeed require a signed-in
person to apply. Open the link, attach the resume and the letter, and submit.

| File | What it does |
|---|---|
| `profile.json` | Search keywords, locations, scoring weights, the facts letters may use, relocation wording |
| `hunt.py` | Seek search, Indeed parsing, scoring, job details, ledger and daily digest |
| `letter.py` | Builds a cover letter `.docx` from a short JSON spec |
| `RUNBOOK.md` | The step-by-step routine the scheduled session follows |
| `ledger.json` | Jobs already handled (lettered or skipped) |

Common tweaks, all in `profile.json`:

- more or fewer letters per day: `search.max_letters_per_day`
- different job titles: `search.keywords` and `search.indeed_queries`
- how strongly Adelaide is favoured: `scoring.location`
- if citizenship or PR is obtained: set `eligibility.australian_citizen` to `true`

The phone number is never stored in this repository; the scheduled task passes it in.
