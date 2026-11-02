// Calendars and world-time points (Phase 15 checkpoint 15.2W-1).

export interface CalendarMonth {
    month_number: number
    name: string
    day_count: number
}

export interface Calendar {
    calendar_id: string
    code: string
    name: string
    description: string | null
    days_per_week: number | null
    epoch_label: string | null
    months: CalendarMonth[]
}

export interface CalendarListResponse {
    calendars: Calendar[]
}

export interface WorldTimeItem {
    world_time_id: string
    calendar_id: string | null
    year: number | null
    month_number: number | null
    day: number | null
    hour: number | null
    minute: number | null
    label: string | null
    precision: string
    sort_key: number
    display: string
}

export interface WorldTimePage {
    items: WorldTimeItem[]
    next_cursor: string | null
}

export interface CreateCalendarBody {
    name: string
    description: string | null
    days_per_week: number | null
    epoch_label: string | null
    months: { name: string; day_count: number }[]
}

export interface CreateWorldTimeBody {
    calendar_id?: string
    year?: number
    month_number?: number
    day?: number
    hour?: number
    minute?: number
    approximate?: boolean
    label?: string
    after_world_time_id?: string
    before_world_time_id?: string
}

// Writes answer with an id-only receipt; the page refetches.
export interface CalendarReceipt {
    calendar_id: string
    created: boolean
    changed: boolean
}

export interface WorldTimeReceipt {
    world_time_id: string
    created: boolean
    changed: boolean
}
