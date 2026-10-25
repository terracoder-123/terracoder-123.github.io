# Daily job hunt runbook

You are running Althaf Rismy's daily job search. Nobody is watching live, so work
through every step without stopping to ask questions, then finish with the report
in step 7. Althaf is a recent Data Analytics graduate based in Melbourne who will
relocate anywhere in Australia, and **Adelaide is the priority**.

The tool never submits applications. It finds jobs, writes tailored cover letters
and hands Althaf the apply links; Althaf submits them.

## 0. Setup

```bash
git fetch origin job-hunter && git checkout job-hunter && git pull origin job-hunter
python3 -c "import docx" 2>/dev/null || python3 -m pip install -q python-docx
export TODAY=$(TZ=Australia/Adelaide date +%F)
```

The scheduled prompt gives you Althaf's phone number as `APPLICANT_PHONE`. Pass it
on every `letter.py` command (`APPLICANT_PHONE='...' python3 letter.py ...`). Never
write it into a tracked file.

## 1. Indeed

For every `[search, location]` pair in `profile.json` → `search.indeed_queries`, call the
Indeed connector's `search_jobs(search=..., location=..., country_code="AU")`.

Save all results to `runs/$TODAY/indeed/results.txt`, one job per line, in this format
(replace any `|` inside a title with `/`; keep every job, the script does the filtering):

```
JOBSEARCH_100448 | Data Analyst | Community Living Options | Edwardstown SA | October 09, 2026 | https://to.indeed.com/aarzcmmn9bc7
```

If no Indeed tools are available (ToolSearch for "Indeed search_jobs" finds nothing), skip this
step, carry on with Seek only, and say so in one line of the report.

## 2. Search and rank

```bash
python3 hunt.py search
```

This pulls Seek automatically (ads from the last day, Adelaide and all of Australia), merges
the Indeed file (same window), removes anything already in `ledger.json`, scores the rest and prints a
numbered shortlist. Adelaide and SA roles get the biggest location bonus.

## 3. Review the shortlist

Work down the shortlist from the top. Read the full ad before deciding:

- Seek item: `python3 hunt.py detail N`
- Indeed item: call `get_job_details(job_id="JOBSEARCH_...")`, save the text to
  `runs/$TODAY/desc_N.txt`, then `python3 hunt.py describe N runs/$TODAY/desc_N.txt`

**Skip** (`python3 hunt.py skip N "short reason"`) when the ad:

- accepts only Australian citizens or permanent residents, or needs an NV1/NV2/baseline clearance.
  Althaf has full-time work rights, so any ad that also welcomes people with work rights
  ("full working rights", "right to work in Australia", "valid visa") is fine
- sets a hard minimum of 4+ years' experience, or is senior / lead / manager level
- is not data, analytics, BI, data engineering, data science or a closely related IT graduate role
- needs a licence, registration or check Althaf doesn't have as an essential requirement
- is a duplicate of a role already on the list (same job via an agency): `skip N "duplicate of #M"`

**Write a letter** for every remaining good fit, Adelaide and SA roles first, then the rest
by score, up to `max_letters_per_day` (10). A role asking for 2 to 3 years' experience is
still worth a letter when the work matches well, especially in Adelaide. Review at most
about 25 ads per day.

## 4. Write each cover letter

Create `runs/$TODAY/specs/NN.json`:

```json
{
  "recipient": ["Hiring Manager", "Company", "Suburb STATE"],
  "re": "Re: Application for <exact job title> (Reference <ref if the ad gives one>)",
  "salutation": "Dear Hiring Manager,",
  "paragraphs": ["opening", "evidence", "more evidence and fit"]
}
```

Then build it:

```bash
APPLICANT_PHONE='...' python3 letter.py N runs/$TODAY/specs/NN.json
```

`letter.py` adds the relocation and working-rights paragraph itself (from
`profile.json` → `relocation`, picked by the job's location) plus the standard closing,
so **do not write about relocation or work rights in your paragraphs**. The one exception:
if the ad asks specifically for interstate or relocating candidates, say in the opening
that Althaf is one. If the detected city is wrong (check the `detail` output), add
`"city": "Wollongong"` to the spec; `"relocation"` can override the mode
(`adelaide`, `south_australia`, `other`, `home`, `remote`).

Writing rules:

- Use only facts in `profile.json` → `facts`, and obey `do_not_claim` exactly. Never invent
  work experience, tools, results, dates or a start date.
- Paragraph 1: the exact role, that it was advertised on Seek or Indeed, the degree (completed
  Dec 2025) and current Master by Research, and one concrete reason this employer or role
  appeals, taken from the ad.
- Paragraph 2: the two or three most important requirements in the ad, each matched to real
  evidence (CBA and BCG simulations, capstone, MovieGraph, J.A.R.V.I.S., sysadmin project).
- Paragraph 3: a second strength or project, and any tool gap (Power BI, Snowflake, Azure, etc.)
  framed as eagerness to apply Python/SQL foundations to it. Never claim the tool itself.
- Use the contact name from the ad if one is given: `"Dear Firstname Lastname,"`, no Mr/Ms.
- Australian English, plain and specific. No em dashes, no exclamation marks, and none of:
  passionate, thrilled, delve, leverage, dynamic, synergy, fast-paced world.
- 330 to 420 words in total once the automatic paragraphs are added (`letter.py` rejects
  anything over 480 or any claim on its red-flag list; fix the text and rerun).

If an ad was flagged `clearance/citizenship` but the wording actually welcomes anyone with
work rights, add `"eligibility_checked": "<the ad's wording>"` to the spec.

## 5. Finish

```bash
python3 hunt.py finish
```

This writes `out/$TODAY/digest-$TODAY.md` and adds every lettered or skipped job to
`ledger.json` so it is never shown again.

## 6. Save the ledger

First check push access:

```bash
git push --dry-run origin job-hunter
```

- If it succeeds, commit and push:

  ```bash
  git add ledger.json
  git commit -m "Job hunt $TODAY: <n> letters"
  git push -u origin job-hunter
  ```

  Retry the push up to 4 times (2s, 4s, 8s, 16s) on network errors only.
- If it fails with 403 ("not in this session's authorized repository set"), the scheduled task
  has no write access. Run `git checkout ledger.json` to drop the change, don't commit, don't
  retry, and don't try `add_repo`. The one-day search window already stops jobs repeating.
  Mention it in one line of the report.

Never commit `runs/` or `out/`: they hold the phone number and are gitignored.

## 7. Report to Althaf

1. Send the digest and every `.docx` from `out/$TODAY/` with SendUserFile
   (status `proactive`).
2. Finish with a short message: a table of today's letters (role, company, location, apply
   link), Adelaide and SA first; how many ads were skipped and the main reasons; and anything
   that failed (Seek, Indeed or git push). Remind Althaf to attach the resume when applying.
3. If nothing new fitted today, say so in one or two lines and stop.
