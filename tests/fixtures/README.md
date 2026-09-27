# Test recordings

The Profixio parsers are tested against **real saved output** rather than a mock of what it might
look like. Those recordings are not in version control, because they name real people — the squad,
the opposition and the match referees.

`tests/test_profixio.py` skips itself when they are absent. To run it, put two files here:

| File | Where from |
|---|---|
| `profixio_team.html.gz` | your team page, `profixio.com/app/leagueid<L>/teams/<T>?k=<K>`, saved and gzipped |
| `a_<match id>.pdf` | the Arbetsprotokoll of a played match |

```bash
curl -sL "https://www.profixio.com/app/leagueid<L>/teams/<T>?k=<K>" | gzip -9 > profixio_team.html.gz
```

The protocol PDF has to be saved from a browser — Profixio puts a bot check on that route. The
assertions in the test are pinned to one specific match, so you will need to adjust the expected
numbers to whichever one you use.
