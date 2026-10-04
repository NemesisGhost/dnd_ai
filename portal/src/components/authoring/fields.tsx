import { useId } from "react"
import type { ChangeEvent, ReactNode } from "react"
import "./authoring.css"

// Accessible labeled controls for the authoring forms (docs/UI_DESIGN.md
// §5.11). Every control has a visible <label>, an optional hint, and an error;
// a control with an error carries aria-invalid and aria-describedby pointing at
// its hint and error, and the error text is plain text (never color alone).

interface FieldShellProps {
    id: string
    label: string
    hint?: string
    error?: string | null
    required?: boolean
    children: (describedBy: string | undefined) => ReactNode
}

function FieldShell({ id, label, hint, error, required, children }: FieldShellProps) {
    const hintId = hint ? `${id}-hint` : undefined
    const errorId = error ? `${id}-error` : undefined
    const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined

    return (
        <div className={error ? "authoring-field authoring-field--invalid" : "authoring-field"}>
            <label className="authoring-field__label" htmlFor={id}>
                {label}
                {required ? (
                    <span className="authoring-field__required"> (required)</span>
                ) : null}
            </label>
            {hint ? (
                <p className="authoring-field__hint" id={hintId}>
                    {hint}
                </p>
            ) : null}
            {children(describedBy)}
            {error ? (
                <p className="authoring-field__error" id={errorId}>
                    <span className="visually-hidden">Error: </span>
                    {error}
                </p>
            ) : null}
        </div>
    )
}

interface TextFieldProps {
    id?: string
    label: string
    value: string
    onChange: (value: string) => void
    hint?: string
    error?: string | null
    required?: boolean
    maxLength?: number
    disabled?: boolean
    autoComplete?: string
}

export function TextField({
    id,
    label,
    value,
    onChange,
    hint,
    error,
    required,
    maxLength,
    disabled,
    autoComplete,
}: TextFieldProps) {
    const generated = useId()
    const fieldId = id ?? generated
    return (
        <FieldShell id={fieldId} label={label} hint={hint} error={error} required={required}>
            {(describedBy) => (
                <>
                    <input
                        id={fieldId}
                        className="authoring-field__control"
                        type="text"
                        value={value}
                        disabled={disabled}
                        autoComplete={autoComplete ?? "off"}
                        aria-invalid={error ? true : undefined}
                        aria-describedby={describedBy}
                        aria-required={required ? true : undefined}
                        onChange={(event: ChangeEvent<HTMLInputElement>) =>
                            onChange(event.target.value)
                        }
                    />
                    <CharacterCounter value={value} maxLength={maxLength} />
                </>
            )}
        </FieldShell>
    )
}

interface TextAreaFieldProps extends Omit<TextFieldProps, "autoComplete"> {
    rows?: number
}

export function TextAreaField({
    id,
    label,
    value,
    onChange,
    hint,
    error,
    required,
    maxLength,
    disabled,
    rows = 4,
}: TextAreaFieldProps) {
    const generated = useId()
    const fieldId = id ?? generated
    return (
        <FieldShell id={fieldId} label={label} hint={hint} error={error} required={required}>
            {(describedBy) => (
                <>
                    <textarea
                        id={fieldId}
                        className="authoring-field__control"
                        rows={rows}
                        value={value}
                        disabled={disabled}
                        aria-invalid={error ? true : undefined}
                        aria-describedby={describedBy}
                        aria-required={required ? true : undefined}
                        onChange={(event: ChangeEvent<HTMLTextAreaElement>) =>
                            onChange(event.target.value)
                        }
                    />
                    <CharacterCounter value={value} maxLength={maxLength} />
                </>
            )}
        </FieldShell>
    )
}

// A polite hint that appears only near the limit, so it is not read on every
// keystroke.
function CharacterCounter({ value, maxLength }: { value: string; maxLength?: number }) {
    if (maxLength === undefined) {
        return null
    }
    const remaining = maxLength - value.trim().length
    if (remaining > Math.max(20, Math.floor(maxLength * 0.1))) {
        return null
    }
    return (
        <p
            className={
                remaining < 0
                    ? "authoring-field__counter authoring-field__counter--over"
                    : "authoring-field__counter"
            }
            role="status"
            aria-live="polite"
        >
            {remaining < 0
                ? `${-remaining} characters over the limit`
                : `${remaining} characters remaining`}
        </p>
    )
}

export interface SelectOption {
    value: string
    label: string
}

interface SelectFieldProps {
    id?: string
    label: string
    value: string
    options: readonly SelectOption[]
    onChange: (value: string) => void
    hint?: string
    error?: string | null
    required?: boolean
    disabled?: boolean
    placeholder?: string
}

export function SelectField({
    id,
    label,
    value,
    options,
    onChange,
    hint,
    error,
    required,
    disabled,
    placeholder,
}: SelectFieldProps) {
    const generated = useId()
    const fieldId = id ?? generated
    return (
        <FieldShell id={fieldId} label={label} hint={hint} error={error} required={required}>
            {(describedBy) => (
                <select
                    id={fieldId}
                    className="authoring-field__control"
                    value={value}
                    disabled={disabled}
                    aria-invalid={error ? true : undefined}
                    aria-describedby={describedBy}
                    aria-required={required ? true : undefined}
                    onChange={(event) => onChange(event.target.value)}
                >
                    {placeholder !== undefined ? (
                        <option value="">{placeholder}</option>
                    ) : null}
                    {options.map((option) => (
                        <option key={option.value} value={option.value}>
                            {option.label}
                        </option>
                    ))}
                </select>
            )}
        </FieldShell>
    )
}

interface RadioGroupFieldProps {
    id?: string
    legend: string
    value: string
    options: readonly (SelectOption & { description?: string })[]
    onChange: (value: string) => void
    hint?: string
    error?: string | null
    disabled?: boolean
}

export function RadioGroupField({
    id,
    legend,
    value,
    options,
    onChange,
    hint,
    error,
    disabled,
}: RadioGroupFieldProps) {
    const generated = useId()
    const groupId = id ?? generated
    const hintId = hint ? `${groupId}-hint` : undefined
    const errorId = error ? `${groupId}-error` : undefined
    const describedBy = [hintId, errorId].filter(Boolean).join(" ") || undefined

    return (
        <fieldset
            id={groupId}
            className={
                error
                    ? "authoring-field authoring-field--invalid authoring-radio-group"
                    : "authoring-field authoring-radio-group"
            }
            aria-describedby={describedBy}
            aria-invalid={error ? true : undefined}
            disabled={disabled}
        >
            <legend className="authoring-field__label">{legend}</legend>
            {hint ? (
                <p className="authoring-field__hint" id={hintId}>
                    {hint}
                </p>
            ) : null}
            {options.map((option) => {
                const optionId = `${groupId}-${option.value}`
                return (
                    <div className="authoring-radio" key={option.value}>
                        <input
                            id={optionId}
                            type="radio"
                            name={groupId}
                            value={option.value}
                            checked={value === option.value}
                            onChange={() => onChange(option.value)}
                        />
                        <label htmlFor={optionId}>{option.label}</label>
                        {option.description ? (
                            <p className="authoring-field__hint">{option.description}</p>
                        ) : null}
                    </div>
                )
            })}
            {error ? (
                <p className="authoring-field__error" id={errorId}>
                    <span className="visually-hidden">Error: </span>
                    {error}
                </p>
            ) : null}
        </fieldset>
    )
}
