// What a write that was confirmed tells the Access page besides its message. Optional, and sent only by the
// character-denial controls (P15-C02-S04), so every other write behaves exactly as before.
export interface WriteNotice {
    // The member (or access group) whose "Direct resource access" heading takes focus after the list is read
    // again, but only if focus was displaced to the page body by that re-read (D-5).
    focusGrantsOf?: string
}
