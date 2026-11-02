"""Source and provenance policy (Phase 15 checkpoint 15.3C-1, decision D-26).

A source says where a fact in the world came from. Every authored entity cites the source it was
created from; a GM can attach further sources later and detach one that no longer applies, and
both are kept as history. A GM authors a source as one of a closed list of types with a title and
a GM-only reference text (a page, a section, a note); there is no upload and no URL fetch.
"""

from .authoring import AuthoringValidationError
from .errors import SafeMessageError

SOURCE_TYPES = (
    ("gm_entry", "GM entry"),
    ("published_reference", "Published reference"),
    ("homebrew_document", "Homebrew document"),
    ("session_notes", "Session notes"),
)
SOURCE_TYPE_CODES = frozenset(code for code, _ in SOURCE_TYPES)
TITLE_MAX_LENGTH = 500
REFERENCE_MAX_LENGTH = 2000

# The lifecycle commands whose audit rows make up an entity's transition history.
LIFECYCLE_COMMANDS = {
    "submit_entity_for_review": "Submitted for review",
    "return_entity_to_draft": "Returned to draft",
    "approve_entity": "Approved",
    "reject_entity": "Rejected",
    "publish_entity_as_canon": "Published as canon",
    "supersede_entity": "Superseded",
    "archive_entity": "Archived",
    "restore_entity": "Restored",
}


def normalize_source_type(value: str) -> str:
    if value not in SOURCE_TYPE_CODES:
        raise AuthoringValidationError("source_type is not one of the authorable source types")
    return value


def normalize_title(value: str) -> str:
    clean = value.strip()
    if not clean:
        raise AuthoringValidationError("title is required")
    if len(clean) > TITLE_MAX_LENGTH:
        raise AuthoringValidationError(f"title must be at most {TITLE_MAX_LENGTH} characters")
    return clean


def normalize_reference(value: str | None) -> str | None:
    if value is None or not value.strip():
        return None
    clean = value.strip()
    if len(clean) > REFERENCE_MAX_LENGTH:
        raise AuthoringValidationError(
            f"reference must be at most {REFERENCE_MAX_LENGTH} characters"
        )
    return clean


class SourceNotUsableError(SafeMessageError):
    """The source does not exist in this world."""

    safe_status_code = 400
    safe_error_code = "source_invalid"
    safe_message = "Choose a source that belongs to this world."


class SourceAlreadyAttachedError(SafeMessageError):
    safe_status_code = 409
    safe_error_code = "source_already_attached"
    safe_message = "That source is already attached to this record."


class SourceNotAttachedError(SafeMessageError):
    safe_status_code = 409
    safe_error_code = "source_not_attached"
    safe_message = "That source is not attached to this record."
