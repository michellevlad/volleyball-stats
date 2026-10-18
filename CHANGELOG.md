# Changelog

What changed, in the words of someone using the app rather than writing it.
Versions follow [semantic versioning](https://semver.org): while the app is
pre-1.0 a new feature bumps the **minor** number and a fix bumps the **patch**.

The version lives in `volley/__init__.py` and is shown at the bottom of the
sidebar, so the running app can always be matched to an entry here.

## [Unreleased]

## [0.4.0] - 2026-10-18

### Added
- **Set → hitter → outcome in one chain.** A plain set now asks who it went to
  and how the attack ended, and records both events, the way an assist already
  recorded the hitter's kill. (#6)
- **Auto score.** A toggle next to the score keeps it for you: a kill, ace or
  block point adds one to us, an error adds one to them. It starts off for a
  set that has an official protocol, because that protocol already carries a
  score for every point.
- **The score sits beside the video**, where you can see it without looking
  away from the match.

### Changed
- The `SET` result once shown as `set` now reads **`set attempt`**, so the
  button no longer reads the same as the set you are entering.
- **The player of a recorded event can be corrected again.** The `player` cell
  in *Edit all events* is a drop-down of that match's line-up; picking a name
  moves the event to that player. Editing the shirt number still works too.
- *Official vs entered* explains the case where an imported protocol stops
  short of the official score: the protocol only records points **our** players
  scored, so a set that ended on opponent errors is missing its last points
  until you add them.

### Fixed
- Reopening the app no longer throws away points added by hand to a set that
  has a protocol. The protocol is treated as a floor, not as the whole truth.

## [0.3.0] - 2026-10-18

Entering a whole match from video, end to end (#3, #5).

### Added
- Review duplicates: settle a protocol row against a hand-entered one, once,
  and have that decision remembered.
- An assist records the hitter's kill as well as the setter's assist.
- Per-match archive of raw events, and a role saved as it is picked.

### Fixed
- Saving an edit no longer renames players: a recorded event takes its name
  from the match line-up, never from the current roster.
- Events are ordered by when they were registered, so the newest is the first
  row of both the recent list and the editor.
- The set no longer snaps back to 1 while you work.

### Security
- Real player names moved out of the repository into git-ignored fixtures.

## [0.2.0] - 2026-10-17

### Added
- One squad table, a name-keyed roster, and scoring actions you can correct.

### Fixed
- Protocol import from the command line.

## [0.1.0] - 2026-09-27

First version: match entry from video, Profixio import, Looker-ready output.
