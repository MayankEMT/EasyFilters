"""User-facing strings. Change wording here, nowhere else."""

# The asked-for preference is not available in the facets the caller sent.
NO_MATCH = "No flights match this preference."

# The message carried no filter intent at all (a search, a greeting, chit-chat).
NO_FILTER_INTENT = "No filter change requested."

# Some preferences applied and at least one did not. Distinct from NO_MATCH so
# the traveller is not told nothing matched when most of their request did.
PARTIAL = "We applied the closest match so you still see flights."
