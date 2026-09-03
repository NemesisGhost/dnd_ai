import {
    useCallback,
    useState,
} from "react"
import {
    login,
    LoginRequestError,
} from "../api/login"
import type { LoginCredentials } from "../api/login"
import { useSession } from "../context/SessionContext"

export type LoginState =
    | { status: "idle" }
    | { status: "submitting" }
    | { status: "complete" }
    | { status: "error"; message: string }

export interface UseLoginResult {
    state: LoginState
    submit: (
        credentials: LoginCredentials,
    ) => Promise<boolean>
}

const initialState: LoginState = {
    status: "idle",
}

function loginErrorMessage(cause: unknown): string {
    if (cause instanceof LoginRequestError) {
        if (cause.status === 401) {
            return "The login name or password is incorrect."
        }

        if (cause.status === 429) {
            return "Too many login attempts. Wait and try again."
        }
    }

    return "The portal could not sign you in. Try again."
}

export function useLogin(): UseLoginResult {
    const { reload } = useSession()
    const [state, setState] =
        useState<LoginState>(initialState)

    const submit = useCallback(
        async (
            credentials: LoginCredentials,
        ): Promise<boolean> => {
            setState({ status: "submitting" })

            try {
                await login(credentials)

                setState({ status: "complete" })
                reload()

                return true
            } catch (cause: unknown) {
                setState({
                    status: "error",
                    message: loginErrorMessage(cause),
                })

                return false
            }
        },
        [reload],
    )

    return {
        state,
        submit,
    }
}