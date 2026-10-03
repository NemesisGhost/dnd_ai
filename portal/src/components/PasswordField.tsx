interface PasswordFieldProps {
    id: string
    label: string
    value: string
    onChange: (value: string) => void
    autoComplete: "new-password" | "current-password"
    disabled?: boolean
    minLength?: number
    invalid?: boolean
    describedBy?: string
}

// Shared across every screen that sets or verifies a local-account
// password (CP 11's activation/reset pages, CP 11b's self-service change-
// password form) — one control, one set of attributes, rather than a
// fourth hand-rolled copy.
export function PasswordField({
    id,
    label,
    value,
    onChange,
    autoComplete,
    disabled = false,
    minLength,
    invalid,
    describedBy,
}: PasswordFieldProps) {
    return (
        <div className="form-group">
            <label htmlFor={id} className="form-label">
                {label}
            </label>
            <input
                id={id}
                type="password"
                className="form-input"
                autoComplete={autoComplete}
                value={value}
                disabled={disabled}
                minLength={minLength}
                aria-invalid={invalid ? true : undefined}
                aria-describedby={describedBy}
                onChange={(event) => {
                    onChange(event.currentTarget.value)
                }}
                required
            />
        </div>
    )
}
