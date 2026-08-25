# Deadline Agent

Deadlines reach a student scattered across channels, out of order, and
contradicting each other. This agent takes forwarded messages one at a time,
keeps one consolidated task list in SQLite, and answers questions from it.

It updates tasks instead of duplicating them, and it says "I don't know"
rather than guessing a date.

## Run it in five minutes

```bash
git clone git@github.com:ritesh7107/deadline-agent.git && cd deadline-agent
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # paste your ANTHROPIC_API_KEY
python cli.py ingest messages.jsonl
python cli.py tasks
python cli.py ask "what's due this week?"
```

No database to install. `sqlite3` ships with Python and the database is a
file (`deadlines.db`).

`NOW=2026-08-25` is pinned in `.env.example` so "this week" means the same
thing on your machine as it did on mine. Unset it to use the real date.

## Commands

| | |
|---|---|
| `ingest <file.jsonl>` | Process messages. `-v` also prints the noise it rejected. |
| `tasks` | Open tasks. `-c DBMS` by course, `-f` only those needing confirmation. |
| `show <id>` | One task with every source that ever touched it. |
| `ask "..."` | Natural-language question answered from the database. |
| `reset` | Empty the tables. |

## What it does with a message

```
message
  │
  ├─ 1 extract   is this task-bearing? title, course, due, weightage,
  │              correction signals, hearsay markers        [LLM, typed]
  │              └─ noise → logged as ignored, stop
  │
  ├─ 2 resolve   narrow to candidate open tasks in SQL, then let the model
  │              pick: NEW / UPDATE(id) / DUPLICATE        [SQL + LLM]
  │
  ├─ 3 apply     insert, or update and write a task_events row recording
  │              old value, new value, source and authority
  │
  └─ 4 gate      deadline unknown or sources in conflict → needs_confirmation
                 with a reason; both values stay visible
```

## The four cases the brief asks about

Ingest the bundled corpus and these all appear:

**Noise is rejected.** Around 25 of the 81 messages are chatter, and most of
them contain a time — *"anyone up for football at 6?"*, *"is there class at 9
tmrw?"*, *"cricket match on Sunday 4pm"*. A time is not a deadline. The
extractor classifies intent, so none of these become tasks.

**A correction updates, it does not duplicate.** The professor announces a
DBMS quiz for Wednesday, then emails *"moved to Friday, not Wednesday"*. One
task, its date changed, the old value preserved in its history.

**A contradiction is flagged, with both sides shown.** Two classmates give
different dates for the CN assignment — Sept 2 and Sept 4 — with no
correction language and equal credibility. The agent takes neither silently:

```
$ python cli.py show 4
#4 CN assignment  CN · assignment
  due 2026-09-04  (date_only, source: whatsapp group)
  ⚑ whatsapp group says 2026-09-02, whatsapp group says 2026-09-04
    - equally credible sources, unresolved
```

**An unknown deadline stays unknown.** *"Start working on the OS lab report,
submit soon. The exact date will be announced later."* is stored with
`due_at = NULL`, flagged, and never filled in by inference:

```
$ python cli.py ask "is the OS lab due this week or next?"
The OS lab report's deadline isn't known. The announcement said the date
would be given later, so it's flagged for confirmation — I can't tell you
whether it falls this week or next.
```

## Design decisions

**Deterministic retrieval, model judgement.** Candidate tasks are narrowed in
SQL — same course, still open, last 60 days, capped at ten — and only then
does the model decide `NEW` / `UPDATE` / `DUPLICATE`. Holding the whole task
list in the prompt does not scale and is not reproducible; pure string
similarity breaks the moment someone writes *"that database submission"*
instead of *"DBMS Assignment 2"*.

**Authority is a property of the sender, not the channel.** A professor on
WhatsApp is still a professor, so the ladder keys on `sender_role`:
professor and official systems 4, TA 3, student 2. Relayed claims — *"I
heard"*, *"someone said"* — are capped at 1 regardless of who forwarded them.
This is what stops a rumour from overwriting the professor's date.

**Correction and contradiction are different things.** Conflicting dates take
one of four paths (`resolve.py`): explicit correction from an equal-or-higher
source updates cleanly; a strictly higher authority overrides cleanly; equal
authority with no correction language updates *tentatively* and raises the
flag; a lower authority does not move the date at all but still raises the
flag, because the student should know people are disagreeing with the
official date.

**A weak source that quotes the old date correctly is trusted — and
flagged.** *"the DBMS report is due 25th not 28th"* comes from a group chat
and contradicts the TA. Knowing the superseded value is evidence the sender
is actually informed, so the date moves; the weak source is why it still
carries a flag. A "correction" quoting a date the task never held is ignored.

**`due_precision` makes guessing structurally impossible.** Every task
records whether its deadline is `exact`, `date_only`, or `unknown`. The
extraction prompt requires `due_at = NULL` for *soon* / *TBA* / *will be
announced*, and the query layer never drops an undated task from a date
filter — those are precisely the ones a student gets blindsided by.

**`task_events` is the audit trail and the "show both versions" mechanism.**
One table doing both jobs. It is what makes `show` able to answer *why does
this say the 25th?* with receipts.

**SQLite by default, Postgres by environment variable.** A reviewer who has
to create a Supabase project first is twenty minutes from their first output,
not five. `DB_PATH` points the database anywhere; the schema is plain SQL and
ports to Supabase unchanged.

**The model call is injected, so the logic is testable.** `resolve()` takes
a match function as an argument. The tests pass canned verdicts, which is why
the whole branch table runs offline with no API key and no flakiness.

## Tests

```bash
python test_resolve.py     # no API key, no network
```

Fourteen assertions over every branch of the resolver: noise rejection,
unknown-deadline preservation, clean correction, quoted correction from a
weak source, a correction quoting the wrong old date, true contradiction,
higher- and lower-authority conflicts, duplicate absorption, flag clearing by
agreement, and idempotent re-ingest.

## Layout

```
schema.sql        three tables
db.py             raw SQL, no ORM
models.py         Extraction and MatchVerdict — the typed LLM contracts
extract.py        step 1, plus the model half of step 2
resolve.py        steps 2–4: matching, authority rules, confidence gate
query.py          one filter tool the answering agent calls
cli.py            ingest / tasks / show / ask / reset
build_corpus.py   generates messages.jsonl, kept so the corpus is reviewable
test_resolve.py   offline branch tests
```

## Known limits

- A correction is matched to a stored date by day-of-month only. Fine while
  people write *"the 28th"*; compare full dates once messages start quoting
  month and year.
- Single student, single timeline. No accounts, no auth — nothing in the
  brief needs them.
- `status` is only ever `open`. Completion would be the next column to use,
  not a new table.
