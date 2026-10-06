# hs: homeschool engine and parent portal

Each morning, parents print one paper packet per child. When the work is done, they upload a
scan or phone photos of the pages. The engine grades them, the parent checks and approves the
results, and the next day's packet is set at the edge of each child's ability.

The parent portal is a website shared by many families. Each family has its own account, and
sees only its own children and scans.

- **Home:** one button prints every child's packet for today. A small calendar for each child
  shows which days are done, waiting to be checked, missing pages, or not turned in.
- **Child page:** a full month calendar. Click any day to see the packet, the answer key, the
  scanned pages, and each answer next to the image of what the child wrote. Fix anything
  misread, then approve.
- **Upload scans:** PDFs or photos, any order, any orientation, several children at once.
  Grading runs in the background and takes about a minute.
- **Family:** children, time zone, invite another parent, delete everything.

Math is the only subject so far.

## Run it locally

```sh
uv sync
export HS_MASTER_KEY=$(uv run hs keygen)   # encrypts every family's files; keep a copy safe
export ANTHROPIC_API_KEY=...               # reads handwriting
uv run hs invite you@example.com           # sign-in is invite-only
uv run hs serve                            # http://localhost:8000
```

Without `RESEND_API_KEY`, sign-in emails are printed to the server log, so you can click the
link from there.

## Hosting

The portal runs as one container with a persistent disk (`Dockerfile`, `fly.toml`). With
[Fly.io](https://fly.io):

```sh
fly launch --no-deploy --copy-config       # pick your app name; update app and HS_BASE_URL in fly.toml
fly volumes create hs_data --size 10
fly secrets set HS_MASTER_KEY=$(uv run hs keygen) ANTHROPIC_API_KEY=... \
                RESEND_API_KEY=... HS_MAIL_FROM="Homeschool <portal@yourdomain.com>"
fly deploy
fly ssh console -C "hs invite you@example.com"
```

- **Email:** [Resend](https://resend.com) sends the sign-in links. Verify your domain there
  and use it in `HS_MAIL_FROM`.
- **Invites:** families can only sign in once invited, because every graded page costs an API
  call. `hs invite <email>` starts a new family. Parents can invite a co-parent from the
  Family page. `hs families` lists accounts.
- **Backups:** Fly snapshots volumes daily and keeps them for 5 days. For longer retention,
  copy `/data` somewhere else regularly. The files are already encrypted, but the master key
  must be kept separately or the copy is useless.
- **Scale:** SQLite on one machine comfortably serves hundreds of families. Grading is the
  slow part: one worker reads one upload at a time. Past that, the next steps are Postgres,
  S3-compatible storage, and more workers.

## Scan storage and privacy

Scans are kept, so parents can look back at any day. Every file the portal stores (scans,
answer crops, packets, answer keys) is encrypted:

- **Encryption:** each family has its own random AES-256-GCM key, stored in the database
  wrapped by `HS_MASTER_KEY`. A stolen disk or database copy can't be read without the master
  key, which lives only in the host's secret store.
- **Binding:** each file is bound to its own name and family. Files can't be swapped between
  days or families without detection.
- **Access:** files are decrypted only to answer a signed-in parent's request, and are sent
  with no-store headers. Every page, PDF, and image checks that it belongs to the signed-in
  parent's family. Anything else returns "not found", and a page from another family's packet
  is refused at upload.
- **Uploads:** a raw upload is kept encrypted until every page has been used, so failed
  grading can be retried. After that, the portal keeps the straightened page images and the
  answer crops.
- **Sign-in:** emailed links work once and expire after 20 minutes. Sessions are signed
  cookies, and form posts from other sites are refused.
- **Deleting:** "Delete our account" on the Family page removes the family's rows and files
  immediately. Volume snapshots age out within 5 days.

What this doesn't cover:

- **Operator access:** you, as the operator, hold the master key, so you could decrypt any
  family's files. Tell families that.
- **Anthropic API:** answer crops are sent to the Anthropic API to be read.
- **Children's data:** before opening this to families beyond your own, publish a privacy
  policy. It should say what is stored, who can see it, the API use above, and how deletion
  works. Families should also agree to it.

## Curriculum

`content/math/curriculum.yaml` is the K-12 math sequence that the skills tree is built from.
AmblesideOnline doesn't set a math sequence. It lists programs to choose from, so this file
follows the order of the ones it names that suit a Charlotte Mason, paper-and-pencil approach:

- Grades K-5: Charlotte Mason Elementary Arithmetic, Books 1-5.
- Grades 3-8: Strayer-Upton Practical Arithmetics.
- Grade 9: Jacobs' *Elementary Algebra*.
- Grade 10: Jacobs' *Geometry*, with Euclid Book I.
- Grades 11-12: Algebra 2 and precalculus in the usual order.

Each topic has a `mode`:

- `paper`: short answers the engine can grade.
- `written`: proofs or drawings the parent checks.
- `oral`: mental arithmetic and narration.
- `hands-on`: objects, measuring, ruler and compass.

`skills.yaml` holds the topics the engine currently generates. A test keeps it in the same
grade and order as the curriculum.

### History, science and French

A child with an AmblesideOnline year set on the Family page gets that year's readings in
order, one a day: history on Monday (*This Country of Ours*), science on Tuesday and Thursday
(Fabre's *Story-Book of Science*), and nature lore on Wednesday (*Madam How and Lady Why*).
Friday is math and French only. The days are set in `settings.yaml` under `ao.days`.
All three books are public domain. The chapter is printed in the packet and followed by a
narration page, which the child can write on or skip by telling it back out loud. A missed
day doesn't skip a reading: the next one goes out on the next matching weekday.

`content/ao/year4/` is built from the Project Gutenberg texts by `scripts/build_ao.py`,
following AmblesideOnline's Year 4 schedule from Week 1. Other years can be added the same way.

French is taught by ear first, as Charlotte Mason recommends. Page 1 names the day's audio
lesson (`french.program` in `settings.yaml`) with a circle to fill in once it's done. The lesson
moves on only once that circle is marked, or once the parent ticks it on the day page.

### Word of the day and weather

Page 1 opens with a word of the day: the word, its part of speech, a meaning and an example
sentence. The words come from `content/words.yaml`, with one list for grades 3-5 and one for
grades 6-8. A child never gets the same word twice. On a reading day, a word from that
day's chapter is chosen first.

Next to it is the day's weather, if the family has set a town or ZIP on the Family page:
- The forecast comes from Open-Meteo, which needs no API key. Its free tier is for
  non-commercial use, so check its terms before charging families.
- The town is looked up once, with OpenStreetMap's Nominatim, and stored rounded to about
  a kilometre.
- If no forecast can be fetched, the word of the day takes the full width and the packet
  prints as usual.

## How it works

- **Pages.** Each page has corner markers and a QR code (worksheet and page). A math page has
  six problems, each with a boxed answer area and "stuck" and "too easy" circles. Pages can be
  scanned in any order and any orientation.
- **Look.** Packets are black and white. Words are in Nunito, math in New Computer Modern
  (built into Typst) and readings in Literata. Nunito and Literata are bundled in
  `src/hs/fonts` with their open font licences. The QR codes are drawn with round dots and gently rounded corners. ZXing reads them
  first and OpenCV is the backup, and a test checks that both can.
- **Reading.** The scan is straightened using the corner markers. The circles are read by
  measuring how dark they are. Each non-blank answer box is sent to Claude, which only
  transcribes what was written and reports its confidence. It never grades.
- **Grading.** Answer keys are computed exactly in Python when the packet is made
  (`src/hs/generators/math.py`). Grading compares values, so `0.75` matches `3/4`. Fraction
  skills require lowest terms. Division with a remainder takes `12 R3`.
- **Review.** Reads below `confidence_threshold`, half-filled circles, and answers that can't
  be understood are highlighted on the day page. Levels change only when a parent approves.
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
config/settings.yaml   engine settings: model, confidence threshold, level rules, packet size
content/math/          curriculum.yaml (K-12 map) and skills.yaml (the part the engine generates)
content/ao/year4/      AmblesideOnline Year 4 readings (public domain), built by scripts/build_ao.py
content/words.yaml     word of the day, by grade band
src/hs/                web (portal), accounts, jobs (grading queue), packets, planner, generators,
                       render (Typst), scan, read (Claude), grade, levels, vault, mail,
                       readings (AO and French), words, weather
src/hs/fonts/          Nunito and Literata (SIL Open Font License)
src/hs/templates/      portal pages
HS_HOME/hs.db          SQLite: families, children, levels, results (not in git)
HS_HOME/files/<family>/   encrypted packets, keys, page images, crops, pending uploads
```

## Tests

```sh
uv run pytest
```

- **Engine tests:** a real packet is filled in, "phone scanned" (perspective, rotation, shadow,
  noise, JPEG), uploaded, graded, approved and re-planned.
- **Portal tests:** sign-in, the calendar, the day page, review, and checks that one family
  can't reach another's data.
- **Live read:** with `ANTHROPIC_API_KEY` set, `test_live_transcription` sends the synthetic
  scan to the real API.
