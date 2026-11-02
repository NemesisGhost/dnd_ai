import { useEffect } from "react"

// Reports what a section holds that has not been sent, to the page's one unsaved-input guard.
// `source` names the reporter (a section or one card in it); `labels` are the things in it that
// would be lost, such as "a participant". An empty list clears the report, and so does unmounting.
export type ReportUnsaved = (source: string, labels: string[]) => void

export function useUnsavedReport(report: ReportUnsaved, source: string, labels: string[]): void {
    const key = labels.join("|")
    useEffect(() => {
        report(source, key === "" ? [] : key.split("|"))
    }, [report, source, key])
    useEffect(() => () => report(source, []), [report, source])
}
