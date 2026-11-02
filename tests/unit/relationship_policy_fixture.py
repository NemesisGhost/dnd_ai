"""The portal's relationship policy fixture, generated from the domain policy.

`portal/src/fixtures/relationshipPolicy.json` gives the portal tests the same metadata the options
endpoint serves, so a change to the policy cannot leave the UI tests describing a rule the server
no longer has. `test_relationship_compatibility_policy.py` fails when the file is stale;
regenerate it with `python -m tests.unit.relationship_policy_fixture`.
"""

import json
from pathlib import Path
from typing import Any

from dnd_ai.api.relationship_authoring import pairing_json, relationship_type_json
from dnd_ai.domain.relationship_authoring import RELATIONSHIP_TYPE_POLICIES, pairs_for

FIXTURE_PATH = (
    Path(__file__).resolve().parents[2] / "portal" / "src" / "fixtures" / "relationshipPolicy.json"
)
RECORD_TYPES = ("npc", "player_character", "settlement", "nation", "organization")


def build() -> dict[str, Any]:
    return {
        "relationship_types": [
            relationship_type_json(p) for p in RELATIONSHIP_TYPE_POLICIES.values()
        ],
        "pairings": {code: [pairing_json(p) for p in pairs_for(code)] for code in RECORD_TYPES},
    }


if __name__ == "__main__":
    FIXTURE_PATH.write_text(json.dumps(build(), indent=2) + "\n", encoding="utf-8")
