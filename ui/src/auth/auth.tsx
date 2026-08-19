import { createContext, type PropsWithChildren, useContext } from "react";

export interface PortalIdentity {
  displayName: string;
  accessToken?: string;
}

export interface AuthState {
  identity: PortalIdentity | null;
  login(): Promise<void>;
  logout(): Promise<void>;
}

const pendingAuth: AuthState = {
  identity: null,
  async login() {
    throw new Error("Browser authentication has not been configured.");
  },
  async logout() {},
};

const AuthContext = createContext<AuthState>(pendingAuth);

export function AuthProvider({ children, value = pendingAuth }: PropsWithChildren<{ value?: AuthState }>) {
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  return useContext(AuthContext);
}
