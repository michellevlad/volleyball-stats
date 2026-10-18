# 🏐 Elden VBK — Volleyball Stats

Turn a match into numbers you can actually use: who scores, who passes well, who hits efficiently,
and how that changes depending on the position they play.

**You never type a point twice.** The official scorers already recorded every point — this app
imports that, and you only add from the video what the scoresheet cannot know.

---

## How it works, in one picture

```
  Profixio  ──────────────┐
  (official)              │   fixtures, squad, and every POINT of the match
                          ▼
                    ┌───────────────┐
  You + video ─────▶│   this app    │──▶ Google Sheet ──▶ Looker Studio
  (everything       └───────────────┘      (database)       (dashboard)
   that isn't a point)
```

Three sources, each doing what it is best at:

| Comes from | What it gives |
|---|---|
| **Profixio** | The season fixture list, the squad with shirt numbers, and the official rally log: every point, who scored it, and the running score. |
| **You, watching video** | Everything that never reaches a scoresheet: attack attempts and errors, how well each serve was received, digs, sets, block touches. |
| **The app** | Puts them together, works out the statistics, and keeps the spreadsheet up to date. |

---

## Getting started

Open Terminal, go to this folder, and run these once:

```bash
python3 -m venv .venv                      # a private space for the app's code
.venv/bin/pip install -r requirements.txt  # install what it needs
.venv/bin/python sync_profixio.py          # pull the season from Profixio
```

From then on, **double-click `Volleyball Stats` on the Desktop.** It starts the app if it is not
already running and opens it in your browser. Launching it twice just reopens the tab.

The equivalent from Terminal, if you prefer:

```bash
.venv/bin/streamlit run app.py
```

Either way it is at <http://localhost:8501>. To stop it: `Ctrl-C` in Terminal, or
`pkill -f "streamlit run app.py"`. The launcher writes its output to `data/app.log`.

---

## Doing a match, step by step

### 1. Match setup

This is the screen you land on. Nothing can be entered until you have been through it, and the
**⚙ Match setup** button in the sidebar brings it back whenever you need it.

1. **Choose the match** from the list — it comes from Profixio, so it is already there.
2. **Import the official protocol.** For a match that has been played, Profixio publishes an
   *Arbetsprotokoll*: the complete official record of every point. Click the download link, save
   the PDF, and the app will spot it in your Downloads folder and offer a one-click import. That
   one click fills in every ace, kill and block point of the match, with the correct score.
3. **Paste the YouTube link** for the match video.
4. **Tick who was called up**, and set the role each player is starting in.
5. **Start entering →**

### 2. Watching the video

The video sits across the top. Underneath it are the buttons: **tap the action, tap the result,
tap the player.** Three taps and it is recorded.

The action row is first because it never changes — your hand goes to the same place every time.
The player row comes last, by which point you already know the name. A **set assist** is the one
exception: it asks a fourth time, for who it was set to.

That fourth tap records **two** events — the setter's assist and the hitter's kill — because an
assist is by definition a set that ended in a kill, and asking you to tap the same rally twice is
how points get missed. If the official protocol already has that kill you now have it twice; that
is deliberate, and **Review duplicates** is where you settle it, once.

Click the video once, then YouTube's own shortcuts work:

| key | what it does |
|---|---|
| `k` or `space` | play / pause |
| `j` `l` | jump back / forward 10 seconds |
| `←` `→` | 5 seconds |
| `,` `.` | one frame, when paused |

There is nothing to type. The buttons are the only way in, so there is no shorthand to remember and
nothing that can be mistyped.

### 3. What you record, and what you don't

Once the official protocol is imported, **the buttons for points are greyed out** — kill, ace and
block point. That is deliberate: those already exist, and recording them again would count them
twice. Your job on the video is everything else:

- every attack that *didn't* score (an attempt, or an error)
- how well each serve was received
- digs, sets, block touches

**A set carries on to the hitter.** Pick **Set**, then **assist** or **set attempt**, then the
setter, then who she set it to. An assist stops there — an assist *is* a set that ended in a kill,
so the kill is written for you. A set attempt asks one more thing, **attack attempt** or **attack
error**, and writes that too. Two events, one pass through the buttons: you never enter the set and
the attack separately.

If the protocol is genuinely missing something, switch on **Allow scoring actions** in the sidebar
and the buttons come back.

### 4. Moving between sets

The **set strip** sits just under the score: `Set 1` `Set 2` `Set 3` `Set 4` `Set 5`, then a
**Set 2 →** button.

- Tap any set to jump to it. Everything you record from then on belongs to that set.
- A set turns **✅** once what you have entered matches Profixio's official score for it — that is
  your signal the set is finished and correct, and the **Set N →** button lights up.
- The line-up carries into the next set automatically. Only open **Roles · set N** if someone has
  actually swapped position.

So the rhythm is: work through a set, watch it go ✅, press **Set N →**, carry on.

### 5. Push to Sheets

Press **Push to Sheets** whenever you like — after a set, after a match, after a week. It only
ever adds what is new, so pressing it twice changes nothing.

---

## What the volleyball words mean

If you have never kept stats before, this is the part to read. Every action has three possible
outcomes, and they always mean the same thing: **something good, something neutral, something that
gives the other team a point.**

### Serve — how every rally starts

| Result | What happened | Effect |
|---|---|---|
| **ace** | The serve wins the point on its own — they can't return it, or they shank it so badly the rally is over. | Point for us |
| **in** | A legal serve that they managed to play. | Nothing, rally continues |
| **error** | Into the net, out of bounds, or a foot fault. | Point for them |

### Reception — receiving their serve (also called "passing")

This is the first touch after their serve, and it decides what your team can do next. A team that
passes badly cannot attack well no matter how good its hitters are.

| Result | What happened | Counts as |
|---|---|---|
| **perfect** | The pass goes exactly where the setter wants it. Every attacking option is available. | 3 |
| **playable** | Not good, but the setter can still do something with it — usually only a safe set to the outside. | 2 |
| **error** | Unplayable — shanked, or the serve lands on the floor. | 0, point for them |

**Pass rating** is the average of those numbers. 3.00 is perfect every time. Around 2.3 and above
is strong; below 2.0 means their serve is dictating the match.

### Set — the second touch, feeding the attacker

| Result | What happened | Effect |
|---|---|---|
| **assist** | The set led directly to a kill. This is the standard stat — an assist only counts when the attack scores. | Asks who it went to, then records the hitter's kill too; a point for us |
| **set attempt** | A set that didn't lead to a point. | Asks who it went to and how the attack ended, then records that attack too |
| **error** | A ball-handling fault (double contact, lift) or a set so bad it can't be played. | Point for them |

### Attack — spiking, trying to score

| Result | What happened | Effect |
|---|---|---|
| **kill** | The attack wins the point outright. | Point for us |
| **attempt (0)** | They dug it or blocked it back up — the rally goes on. | Nothing |
| **error** | Hit out, into the net, stuffed straight down by the block, or an illegal contact. | Point for them |

All three count as an *attempt*, which is what the percentages are measured against:

- **Kill %** = kills ÷ attempts. Simple, but ignores errors.
- **Hitting efficiency** = (kills − errors) ÷ attempts. The number coaches actually look at,
  because it punishes errors. `.300` is excellent, `.200` is solid, `.000` means as many errors as
  kills, and a negative number means the player is giving away more points than they win.

### Block — stopping their attack at the net

| Result | What happened | Effect |
|---|---|---|
| **block point** | The block sends the ball straight down. Also called a "stuff". | Point for us |
| **touch (0)** | You got a hand on it but it stayed in play. Genuinely valuable — it slows the ball down so your defence can dig it. | Nothing |
| **error** | Touching the net, reaching over illegally, or blocking the ball out. | Point for them |

### Dig — defending their attack, keeping the ball off the floor

| Result | What happened | Effect |
|---|---|---|
| **dig** | You kept it alive. | Nothing |
| **error** | Their attack landed, or your dig was unplayable. | Point for them |

### Points

**Points = kills + aces + block points.** Those are the only three ways one player can end a rally
in your favour.

The team always scores more points than its players add up to, and that is not a mistake: a large
share of every volleyball match is won on **opponent errors** — they serve out, they hit out. Those
points belong to nobody, so they move the scoreboard without appearing next to any player's name.
In the 26 Sep match against Jomala, 23 of our 75 points came that way.

### Roles

**OH** outside hitter · **MB** middle blocker · **S** setter · **OP** opposite ·
**L** libero · **DS** defensive specialist

Roles are recorded **per set**, because players genuinely move: someone can set in one set and play
opposite in the next. Every event is stamped with the role that player was in at the time, so at
the end of the season you can ask "is she more effective as an outside hitter or as a middle?" and
get a real answer instead of one blurred average.

You only write down the **changes**. Set the line-up once and it carries forward to every later set
until you change it — open **Roles · set N** under the video whenever someone swaps. Change a role
after you have already recorded events and those events are updated too, so the two never disagree.

### The score

The score sits **directly under the video**, in one row, so it is in view while you watch without
costing the video any width.

A set's score is one of two things, and the switch beside it says which:

**Official** — Profixio's score for that set. It is *shown*, not offered: there is no box to type
in and no **+1** to press, because the league has already settled it. A set is official the moment
its protocol has been imported.

**Count as I go** — yours. It starts at **0-0** on a set you haven't counted yet (or wherever your
own counting had got to, if you are coming back to one), and follows what you record:

| What you record | Score |
|---|---|
| kill, ace, block point | **+1 us** |
| any error — serve, attack, set, dig, block | **+1 them** |
| reception error | nothing — use **+1 them** |
| everything else | nothing |

Points that came from an *opponent* mistake have no event of ours at all, so those are **+1 us** by
hand. You can type over either number whenever you like.

---

## Fixing mistakes

- **✕** next to any recent event removes it.
- **Edit all events** opens the whole match in a table you can edit like a spreadsheet, **newest
  first** — the same order as Recent, so whatever you just got wrong is the top row of both. That
  is the order you *registered* things in, not set-and-rally order: sets don't finish in the order
  you track them, and the last thing you typed is the thing you want to reach.
- **The wrong player is fixed in that table.** The **player** cell is a drop-down of everyone in
  this match's line-up — pick the right one and the event moves to her, shirt number and all. You
  can change the **#** instead if you prefer; the name then follows the line-up for that set.
- **Names come from the line-up, never from the roster.** The roster is current; the line-up is who
  wore which shirt *that day*. Shirt numbers get reassigned between matches, so a name looked up by
  number in the roster puts tonight's #4 on the points scored by last month's #4. If a name is wrong
  on an event, fix it in **Roles** for that set and every event of that set follows.
- **Official vs entered** under the box score checks **each set separately** against Profixio, so
  you can confirm a set the moment you finish it rather than discovering at the end of the match
  that one went in under the wrong number:

  | Set | Profixio | Entered | |
  |---|---|---|---|
  | Set 1 | 25-9 | 25-9 | ✅ |
  | Set 2 | 25-5 | 25-5 | ✅ |
  | Set 3 | 25-6 | — | not entered yet |
  | Result | 3-0 | 2-0 | ⚠️ |

  The check is about **sets you counted yourself** — a ⚠️ there means events went in under the
  wrong set number, or the set isn't finished, or you missed the **+1 us** on a point that came
  from an opponent error. A set whose score is **Official** is taking Profixio's own number, so of
  course it agrees; switch it to **Count as I go** if you want the comparison to test something.
- Re-importing the protocol is always safe: it replaces only the imported rows and never touches
  anything you entered from the video.

### Review duplicates

The protocol owns the points. If you also tapped an ace the scoresheet already had, the set now
holds it twice and the player looks twice as productive. **Review duplicates** lists the
point-scoring events of one set — aces, kills and block points, the only three a protocol records —
with both sources side by side. Receptions, digs, attempts, errors and sets can never collide with
a protocol, so they are never shown and never touched.

Each row says what both sides hold: `protocol 4 · you 2`. The guess is that a row the protocol also
has is a re-entry, and a row it has nothing like is a correction — because **the scoresheet is
sometimes wrong**, and "she had 10 aces, not 7" has to be recordable.

**Apply is how you record a decision, not just how you delete.** It removes what you unticked and
marks everything you kept as reviewed, so it is never questioned again — a kept row comes back
marked `✓ kept on review`. Press Apply even when there is nothing to remove; that is how you say
"these are all fine" and stop being asked. Add new events later and only *those* are asked about.

---

## Setting up Google Sheets

The app writes to the spreadsheet you configure, and connects by itself on startup. It tries three
ways to sign in, and uses the first one that is set up.

### 1. Service account (no browser, usually easiest)

Create a service account in a Google Cloud project, download its JSON key, save it here as
`service_account.json`, and **share the spreadsheet with the service account's email address** just
like you would with a teammate. Enable the Sheets and Drive APIs on the project.

### 2. Your own OAuth client

Google Cloud Console → **APIs & Services → Credentials → Create credentials → OAuth client ID** →
**Desktop app**. Save the JSON as `~/.config/gspread/credentials.json`.

### 3. Application Default Credentials

```bash
gcloud auth application-default login \
  --scopes=https://www.googleapis.com/auth/cloud-platform,https://www.googleapis.com/auth/spreadsheets,https://www.googleapis.com/auth/drive.file,openid,https://www.googleapis.com/auth/userinfo.email
```

**This one is being withdrawn.** Google now blocks the Sheets scope for gcloud's built-in client
and shows *"This app is blocked"*. If you see that, use option 1 or 2 — there is nothing to fix in
the command. (It is also why the Colab trick of `auth.authenticate_user()` + `default()` doesn't
work on a laptop: Colab ships its own approved client.)

### What gets written

**A push writes one tab: `PlayerSetStats`.** One row per player per set, counts only, rebuilt from
scratch every time. Because it is rebuilt rather than appended, pushing twice does nothing, and
deleting an event locally removes it from the sheet on the next push.

```
match_id, match_date, match_name, set_no, player_num, player_name, player_role,
kills, attack_errors, attempts, aces, serve_errors, serves,
receptions_perfect, receptions_playable, reception_errors, reception_count,
blocks, block_errors, block_attempts, digs, dig_errors,
assists, set_errors, set_attempts, sets_played
```

Players are identified by **shirt number**. There is no internal id in the sheet.

**No rates are stored** — kill %, hitting efficiency, pass rating and points are calculated fields
in Looker. That is not a preference: a stored rate cannot be re-aggregated. Averaging per-set
hitting efficiencies into a season figure gives a number that is simply wrong, while
`SUM(kills)/SUM(attempts)` is right at every grain.

#### Stopping half way through a match

**Nothing is lost.** Every action is written to `data/events.csv` the instant you record it, so you
can close the app, shut the laptop, and come back days later: open the match and carry on. Pushing
has nothing to do with it.

That holds **on this machine**. Your raw events, roster, fixtures and line-ups live in `data/` and
are not pushed by default, and `PlayerSetStats` is an aggregate — it cannot be turned back into the
actions it was built from. So if `data/` is lost, or you want to continue on a different computer,
the totals survive and the detail does not.

To make the work recoverable, archive the raw rows too:

```
VOLLEY_PUSH_TABS=PlayerSetStats,Events
```

With that set, **⬇ Restore from Sheets** in the sidebar pulls the archived events back down. It is
additive — events already on this machine are left exactly as they are, so restoring can never
overwrite work in progress, and restoring twice changes nothing.

Corrections flow the other way on a push: fix a name or delete an event here, and the next push
makes the sheet match for that match. So the two never drift.

Available names: `PlayerSetStats`, `Events`, `Matches`, `Lineup`, `PlayerMatchStats`,
`TeamMatchStats`, `PlayerRoleStats`. `Events`, `Matches` and `Lineup` append and deduplicate;
the rest are rebuilt each push.

Until then, **`data/` is the only copy of your work**, and the only way to rebuild a half-tracked
match elsewhere is to re-import the Profixio protocol — which returns the aces, kills and blocks
but none of the attempts, errors, receptions or digs you watched for.

#### Fitting an existing spreadsheet

When a push writes into a tab that already has its own columns, it fits in around them:

- **A match this machine holds is mirrored.** Corrections reach rows written weeks ago, and events
  you delete stop coming back — without that, Restore would resurrect everything Review duplicates
  had just removed.
- **A match this machine has never seen is left exactly as it is.** That is what makes the archive
  worth keeping after a local loss.
- **Columns are matched by name**; ones the app doesn't recognise are carried across untouched.
- **Columns it needs but can't find are added on the far right.** Nothing is reordered.

Use **Tab mapping** in the sidebar to say which of your tabs holds what.

---

## The dashboard

In [Looker Studio](https://lookerstudio.google.com): **Create → Data source → Google Sheets**. Two
sources cover everything — `PlayerSetStats` for anything about players, `Matches` for the fixture
list.

Set `match_date` (and `date` on Matches) as the date dimension, and check the counts arrive as
**Number**, not Text.

### Calculated fields

Every rate lives here, not in the sheet — a stored rate cannot be re-aggregated, so these stay
correct whether the chart shows one set, one match or the whole season.

| Field | Formula |
|---|---|
| Points | `SUM(kills) + SUM(aces) + SUM(blocks)` |
| Games | `COUNT_DISTINCT(match_id)` |
| Points per match | `(SUM(kills) + SUM(aces) + SUM(blocks)) / COUNT_DISTINCT(match_id)` |
| Kill % | `SUM(kills) / SUM(attempts)` |
| Hitting efficiency | `(SUM(kills) - SUM(attack_errors)) / SUM(attempts)` |
| Pass rating | `(3 * SUM(receptions_perfect) + 2 * SUM(receptions_playable)) / SUM(reception_count)` |
| Serve error % | `SUM(serve_errors) / SUM(serves)` |

Write them as `SUM(x) / SUM(y)`, never as an average of a rate. Guard a divide-by-zero with
`NARY_MAX(SUM(attempts), 1)` where a filter could leave a player with none.

### Scorers board

The Profixio top-scorers table, from `PlayerSetStats`:

| | |
|---|---|
| **Dimension** | `player_name` |
| **Metrics** | Points · Points per match · `SUM(kills)` *(their "Anfall")* · `SUM(blocks)` *(Block)* · `SUM(aces)` *(Serveess)* · Games |
| **Sort** | Points, descending |

Swap the dimension for `player_role` to get the same board by position, or add it as a second
dimension to see a player split by the roles she played.

> **This covers our players only.** Profixio's board spans the division; ours is built from the
> protocols you import, and those name almost no opponents — their points come overwhelmingly from
> *our* errors, which belong to no player. A board including other teams would be wrong rather than
> incomplete.

### Match list

The fixture view, from `Matches`:

| | |
|---|---|
| **Dimensions** | `date` · `time` · `home_team` · `away_team` · `sets_home` · `result_home` |
| **Sort** | `date` |
| **Filter** | `result_home` *is not null* for played matches only |

`sets_home` and `result_home` are printed **home side first**, the way the league does
(`9-25, 5-25, 6-25` and `0-3`). `official_sets` and `official_result` are the same match from our
point of view (`25-9, 25-5, 25-6` and `3-0`) — use those for anything about how *we* did.

### Worth building too

- **Role comparison** — `PlayerSetStats`, dimensions `player_name` + `player_role`: her numbers as
  OH versus as MB.
- **Match box score** — dimension `player_name`, filtered to one `match_name`.
- **Form over time** — `match_date` across the x-axis against hitting efficiency.

Looker caches; press **Refresh data** after a push if the numbers look old.

---

## For developers

```
app.py                      The whole interface
CHANGELOG.md                What changed, version by version
sync_profixio.py            Season sync and protocol import, from the terminal
seed_demo.py                Fake data, for trying the app out
volley/
  config.py                 Settings: environment -> .env -> defaults
  schema.py                 Actions, results, roles, columns — the single source of truth
  shorthand.py              `7 k` -> an event (used by seed_demo.py only)
  store.py                  Local CSV files, written on every keystroke
  stats.py                  The statistics, in pandas
  sheets.py                 Google auth and writing to the spreadsheet
  profixio.py               Fixtures, squad and official protocol parsing
  video.py                  YouTube link parsing and the video panel
  frontend/index.html       The video player itself
tests/fixtures/             A real Profixio page and a real protocol PDF
data/                       Your local copy of everything. Never leaves your machine.
```

Everything is written to `data/` the instant you record it, so a crash or an accidental refresh
loses nothing. Google Sheets is only involved when you press push.

**Why the video panel is a custom component:** Streamlit re-runs the whole page on every click. A
normal embedded video would restart each time you recorded a kill. A custom component keeps its
frame alive across re-runs. Inside it is a plain YouTube embed — the IFrame API was only there to
read the player clock, and once that was no longer needed it was pure risk: if its script failed to
re-initialise after a rebuild, the panel stayed blank.

```bash
.venv/bin/python -m pytest -q      # 313 tests
```

### Releasing

The version lives in one place, `volley/__init__.py`, and is shown at the bottom of the sidebar so
a running app can always be matched to an entry in `CHANGELOG.md`.

**Every pull request that changes behaviour bumps it**, in the same commit as the change:

1. Bump `__version__` — a new feature moves the minor number, a fix the patch one. The app is
   pre-1.0, so neither is a promise about compatibility yet.
2. Add the matching `## [x.y.z] - YYYY-MM-DD` section to `CHANGELOG.md`, written for someone using
   the app rather than someone reading the diff.

`tests/test_version.py` fails if the two disagree, which is the whole reason it exists: forgetting
is silent otherwise.

The Profixio parsers are tested against **real recorded output** — an actual season page and a real
Arbetsprotokoll — asserting known-good numbers: 16 fixtures, 11 players, 110 protocol rows, 75–20
on points, and a 3–0 with set scores identical to the official ones.
