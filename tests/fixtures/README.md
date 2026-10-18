# Test recordings

The Profixio parsers are tested against **real saved output** rather than a mock of what it might
look like. Those recordings are not in version control, because they name real people — the squad,
the opposition and the match referees.

`tests/test_profixio.py` skips itself when they are absent. To run it, put three files here:

| File | Where from |
|---|---|
| `profixio_team.html.gz` | your team page, `profixio.com/app/leagueid<L>/teams/<T>?k=<K>`, saved and gzipped |
| `a_<match id>.pdf` | the Arbetsprotokoll of a played match |
| `names.json` | the handful of names the parser tests assert on |

`names.json` is here for the same reason the recordings are: a parser test has to check that real
markup produces a real name, and that name should not be in a public repository. Everywhere else
in the suite the people are invented, because those tests are about the logic, not about anyone.

```json
{
  "squad": {"1": "First Player", "15": "Sécond Playér", "99": "Third Player"},
  "shirt_4_then": "Who wore #4 in the recorded match",
  "shirt_4_now": "Who wears #4 now"
}
```

At least one `squad` name needs a non-ASCII character, since that is what proves the parser keeps
accents intact.

```bash
curl -sL "https://www.profixio.com/app/leagueid<L>/teams/<T>?k=<K>" | gzip -9 > profixio_team.html.gz
```

The protocol PDF has to be saved from a browser — Profixio puts a bot check on that route. The
assertions in the test are pinned to one specific match, so you will need to adjust the expected
numbers to whichever one you use.
