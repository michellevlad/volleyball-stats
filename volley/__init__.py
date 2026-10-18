"""Volleyball box-score entry: local buffer, pandas metrics, Google Sheets sync."""

# One place the version is written down, so the app, the changelog and the git
# tag can never say three different things. Bump it in the same pull request as
# the change it describes - see "Releasing" in the README.
__version__ = "0.4.0"

__all__ = ["schema", "shorthand", "stats", "store", "sheets", "__version__"]
