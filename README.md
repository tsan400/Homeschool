# hs: personal homeschool engine

Each morning, print one paper packet per child. In the evening, scan the finished pages.
The engine grades them, you approve the results, and the next day's packet is set at the edge
of each child's ability.

Phase 1 covers Math only.

## Setup

```sh
uv sync
uv run hs keygen               # once; save the key in your password manager
export HS_SCAN_KEY=...         # the key from keygen: encrypts every saved scan image
export ANTHROPIC_API_KEY=...   # used only to read handwriting
```

Edit `config/students.yaml` (children, starting grade) and `config/settings.yaml`
(model, confidence threshold, level rules, problems per day).

## Daily loop

```sh
hs print                 # data/<today>/<child>/packet.pdf and key.pdf
# ...children work on paper; scan each child's pages to inbox/ (PDF or photos)...
hs grade                 # grades everything in inbox/ (or: hs grade path/to/scan.pdf)
hs review                # confirm flagged reads, override grades, approve -> levels update
hs status                # current levels and what's waiting
```

Other options:

- `hs print --placement` prints a placement packet. It has two problems per skill around the
  child's grade. Approving it sets starting levels: both right means mastered, one right
  means level 3, none right means level 1.
- `hs print --test` prints a 10-problem calibration packet that never changes levels. Use it
  to check your printer and phone scanner before the kids start.
- `hs print --fresh` throws away today's unscanned packet and makes a new one.

## Scan privacy

Scans are never stored unencrypted by the engine:

- `hs grade` reads an inbox scan, encrypts it to `inbox/<name>.enc`, and overwrites and deletes
  the original **before** grading starts. All image work happens in memory.
- The only images it keeps are the full scan (`scan.enc`) and the answer-box crops
  (`crops/NN.enc`). Both use AES-256-GCM with `HS_SCAN_KEY`, and each file is bound to its own
  name, so files can't be swapped or edited without detection.
- Once every page has been used, the `inbox/*.enc` copy is deleted. If a page couldn't be used,
  or grading crashed, the copy stays and `hs grade` retries it.
- `hs review` shows crops in a browser tab served from memory on `127.0.0.1`, at a random path,
  with no-cache headers. No decrypted file is written.
- Without `HS_SCAN_KEY`, `hs grade` refuses to run and leaves the inbox untouched. If the key
  is lost, saved crops can't be opened, but grades and levels are unaffected.

What this doesn't cover:

- Anything outside the engine, such as your phone's scan app, cloud sync, or the copy in your
  photo library.
- Answer-box crops are sent to the Anthropic API over HTTPS to be read.
- Deleting a file on an SSD or a copy-on-write filesystem may leave old blocks behind. Full-disk
  encryption (FileVault, BitLocker, LUKS) covers that, and is worth having anyway.
- Packets and answer keys are blank worksheets, not scans, and are stored as normal PDFs.
  `hs.db` and `grades.json` hold the typed transcriptions and scores, not images.

## How it works

- **Pages.** Each page has corner markers, a QR code (student, date, worksheet, page), five
  problems, a boxed answer area, and "stuck" and "too easy" circles. Pages can be scanned in
  any order and any orientation.
- **Reading.** The scan is straightened using the corner markers. The circles are read by
  measuring how dark they are. Each non-blank answer box is sent to Claude, which only
  transcribes what was written and reports its confidence. It never grades.
- **Grading.** Answer keys are computed exactly in Python when the packet is made
  (`src/hs/generators/math.py`). Grading compares values, so `0.75` matches `3/4`. Fraction
  skills require lowest terms. Division with a remainder takes `12 R3`.
- **Review.** Reads below `confidence_threshold`, half-filled circles, and answers that can't
  be understood go to `hs review`. Levels change only when you approve a packet.
- **Levels.** Each skill in `content/math/skills.yaml` has levels 1 to 5:
  - 3 sessions in a row at 85% or better moves the child up a level.
  - 2 sessions in a row under 60% moves them down a level.
  - A session at 85% or better where most problems are marked "too easy" moves them up
    straight away.
  - Passing level 5 marks the skill mastered. It then goes into spaced review, which makes up
    about 20% of each packet.
- **Stuck.** A problem with "stuck" filled in comes back the next day as a worked example,
  followed by two practice problems on the same skill.

## Files

```
config/            students and settings (edit these)
content/math/      skills tree, in teaching order
src/hs/            cli, planner, generators, render (Typst), scan, read (Claude), grade, review, levels, vault, viewer
data/YYYY-MM-DD/<child>/   packet.pdf, key.pdf, grades.json, scan.enc, crops/NN.enc   (gitignored)
inbox/             drop scans here; they are encrypted then shredded on `hs grade`   (gitignored)
hs.db              SQLite results (gitignored, so back it up)
```

## Tests

```sh
uv run pytest            # includes a synthetic filled-in, phone-scanned packet
```

With `ANTHROPIC_API_KEY` set, `test_live_transcription` also sends the synthetic scan to the
real API.
