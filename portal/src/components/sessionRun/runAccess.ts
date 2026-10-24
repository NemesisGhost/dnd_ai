// A session can be run (prepared, played or wrapped up) when the server offers one of the play
// actions. There is no separate "run" action: the session list uses this same test for its
// Run link, and the Run page itself still decides every outcome on the server.
export function canRunSession(actions: readonly string[] | null | undefined): boolean {
    return (actions ?? []).some((a) => a === "start" || a === "log" || a === "end")
}
