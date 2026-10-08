"""Whether a run ended on a capacity error before any model turn (S-0079/D-9).

The night seat's `CLAUDE_CAPACITY_RETRY_SECONDS` asks the image to keep retrying
a capacity error for that long. A rerun is only safe when the run did nothing:
the result envelope is an error with an API status of 429 or 5xx (overloaded,
rate limited, down) and every token count is zero, so no turn ran and no file
was touched. Anything else ends the attempt as it ended. A 4xx other than 429 is
the request itself refused, which a retry cannot change (S-0089/D-2).

    python3 capacity.py <output file>    # exits 0 when a retry is safe
"""

import json
import sys

TOKENS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")

result = None

with open(sys.argv[1], encoding="utf-8", errors="replace") as handle:
    for line in handle:
        line = line.strip()

        if not line.startswith("{"):
            continue

        try:
            event = json.loads(line)
        except ValueError:
            continue

        if isinstance(event, dict) and event.get("type") == "result":
            result = event

if result is None or not result.get("is_error"):
    sys.exit(1)

status = result.get("api_error_status")
usage = result.get("usage") or {}
spent = sum(int(usage.get(key) or 0) for key in TOKENS)
transient = isinstance(status, int) and (status == 429 or status >= 500)

sys.exit(0 if transient and spent == 0 else 1)
