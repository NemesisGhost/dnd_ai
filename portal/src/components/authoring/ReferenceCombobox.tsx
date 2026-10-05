import { useEffect, useId, useRef, useState } from "react"
import type { KeyboardEvent } from "react"
import "./authoring.css"

export interface ReferenceOption {
    id: string
    label: string
    // Secondary text shown beside the label (a category, a status).
    detail?: string
}

interface ReferenceComboboxProps {
    id: string
    label: string
    value: ReferenceOption | null
    onChange: (value: ReferenceOption | null) => void
    // Runs the server-side search. `signal` aborts when a newer search starts
    // or the control unmounts; a late response is discarded either way.
    search: (query: string, signal: AbortSignal) => Promise<ReferenceOption[]>
    hint?: string
    error?: string | null
    disabled?: boolean
    placeholder?: string
}

type Status = "idle" | "loading" | "ready" | "error"

const DEBOUNCE_MS = 200

// An accessible searchable combobox (WAI-ARIA 1.2 editable combobox with list
// autocomplete) for choosing one record from a server-side search: a parent
// location, a headquarters, an origin. It never accepts free text -- leaving
// the control restores the chosen record's name -- and it holds no result cache,
// so authority and scope are re-evaluated by the server on every search.
//
// Keyboard: Down/Up open and move, Enter chooses (without submitting the form),
// Escape closes, Tab leaves. Searches are debounced, aborted when superseded,
// and out-of-order responses are discarded.
export function ReferenceCombobox({
    id,
    label,
    value,
    onChange,
    search,
    hint,
    error,
    disabled,
    placeholder,
}: ReferenceComboboxProps) {
    const listboxId = useId()
    const [open, setOpen] = useState(false)
    const [text, setText] = useState<string | null>(null)
    const [options, setOptions] = useState<ReferenceOption[]>([])
    const [status, setStatus] = useState<Status>("idle")
    const [active, setActive] = useState(-1)
    const timer = useRef<number | null>(null)
    const controller = useRef<AbortController | null>(null)
    const generation = useRef(0)
    const searchRef = useRef(search)
    useEffect(() => {
        searchRef.current = search
    })

    useEffect(
        () => () => {
            if (timer.current !== null) {
                window.clearTimeout(timer.current)
            }
            controller.current?.abort()
        },
        [],
    )

    function runSearch(query: string) {
        controller.current?.abort()
        const next = new AbortController()
        controller.current = next
        const mine = ++generation.current
        setStatus("loading")
        void searchRef
            .current(query, next.signal)
            .then((found) => {
                if (next.signal.aborted || mine !== generation.current) {
                    return
                }
                setOptions(found)
                setActive(found.length > 0 ? 0 : -1)
                setStatus("ready")
            })
            .catch(() => {
                if (next.signal.aborted || mine !== generation.current) {
                    return
                }
                setOptions([])
                setActive(-1)
                setStatus("error")
            })
    }

    function schedule(query: string, immediate: boolean) {
        if (timer.current !== null) {
            window.clearTimeout(timer.current)
            timer.current = null
        }
        if (immediate) {
            runSearch(query)
            return
        }
        setStatus("loading")
        timer.current = window.setTimeout(() => {
            timer.current = null
            runSearch(query)
        }, DEBOUNCE_MS)
    }

    function close() {
        setOpen(false)
        setText(null)
        setActive(-1)
        if (timer.current !== null) {
            window.clearTimeout(timer.current)
            timer.current = null
        }
        controller.current?.abort()
        generation.current += 1
        setStatus("idle")
    }

    function choose(option: ReferenceOption) {
        onChange(option)
        close()
    }

    function openList() {
        if (!open) {
            setOpen(true)
            schedule("", true)
        }
    }

    function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
        switch (event.key) {
            case "ArrowDown":
                event.preventDefault()
                if (!open) {
                    openList()
                } else if (options.length > 0) {
                    setActive((current) => (current + 1) % options.length)
                }
                break
            case "ArrowUp":
                event.preventDefault()
                if (open && options.length > 0) {
                    setActive((current) => (current <= 0 ? options.length - 1 : current - 1))
                }
                break
            case "Enter":
                if (open) {
                    event.preventDefault()
                    const option = options[active]
                    if (option !== undefined) {
                        choose(option)
                    }
                }
                break
            case "Escape":
                if (open) {
                    event.preventDefault()
                    event.stopPropagation()
                    close()
                }
                break
            case "Tab":
                if (open) {
                    close()
                }
                break
            default:
        }
    }

    const hintId = hint ? `${id}-hint` : undefined
    const errorId = error ? `${id}-error` : undefined
    const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined
    const shown = text ?? value?.label ?? ""
    const activeId = open && active >= 0 ? `${listboxId}-${active}` : undefined

    return (
        <div className={error ? "authoring-field authoring-field--invalid" : "authoring-field"}>
            <label className="authoring-field__label" htmlFor={id}>
                {label}
            </label>
            {hint ? (
                <p className="authoring-field__hint" id={hintId}>
                    {hint}
                </p>
            ) : null}
            <div className="authoring-combobox">
                <input
                    id={id}
                    className="authoring-field__control"
                    type="text"
                    role="combobox"
                    autoComplete="off"
                    aria-autocomplete="list"
                    aria-expanded={open}
                    aria-controls={listboxId}
                    aria-activedescendant={activeId}
                    aria-invalid={error ? true : undefined}
                    aria-describedby={describedBy}
                    disabled={disabled}
                    placeholder={placeholder}
                    value={shown}
                    onChange={(event) => {
                        setText(event.target.value)
                        setOpen(true)
                        schedule(event.target.value, false)
                    }}
                    onFocus={openList}
                    onBlur={(event) => {
                        // Moving into the list (a click on an option) must not
                        // close it before the click lands.
                        const next = event.relatedTarget
                        if (!(next instanceof Node) || !event.currentTarget.parentElement?.contains(next)) {
                            close()
                        }
                    }}
                    onKeyDown={onKeyDown}
                />
                {value !== null && !disabled ? (
                    <button
                        type="button"
                        className="authoring-button authoring-combobox__clear"
                        aria-label={`Clear ${label}`}
                        onClick={() => {
                            onChange(null)
                            close()
                        }}
                    >
                        Clear
                    </button>
                ) : null}
                <ul
                    id={listboxId}
                    role="listbox"
                    aria-label={label}
                    className="authoring-combobox__list"
                    hidden={!open}
                >
                    {options.map((option, index) => (
                        <li
                            key={option.id}
                            id={`${listboxId}-${index}`}
                            role="option"
                            aria-selected={option.id === value?.id}
                            className={
                                index === active
                                    ? "authoring-combobox__option authoring-combobox__option--active"
                                    : "authoring-combobox__option"
                            }
                            onMouseDown={(event) => event.preventDefault()}
                            onClick={() => choose(option)}
                        >
                            {option.label}
                            {option.detail ? (
                                <span className="authoring-combobox__detail"> ({option.detail})</span>
                            ) : null}
                        </li>
                    ))}
                </ul>
                <p className="visually-hidden" role="status" aria-live="polite">
                    {!open
                        ? ""
                        : status === "loading"
                          ? "Searching"
                          : status === "error"
                            ? "Could not load options"
                            : status === "ready"
                              ? options.length === 0
                                  ? "No matches"
                                  : `${options.length} ${options.length === 1 ? "option" : "options"} available`
                              : ""}
                </p>
                {open && status === "error" ? (
                    <p className="authoring-field__hint">
                        Options could not be loaded.{" "}
                        <button
                            type="button"
                            className="authoring-button"
                            onMouseDown={(event) => event.preventDefault()}
                            onClick={() => schedule(text ?? "", true)}
                        >
                            Retry
                        </button>
                    </p>
                ) : null}
                {open && status === "ready" && options.length === 0 ? (
                    <p className="authoring-field__hint">No matches.</p>
                ) : null}
            </div>
            {error ? (
                <p className="authoring-field__error" id={errorId}>
                    <span className="visually-hidden">Error: </span>
                    {error}
                </p>
            ) : null}
        </div>
    )
}
