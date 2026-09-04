import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { BrowserRouter } from "react-router"
import App from "./App.tsx"
import { RouteSessionProvider } from "./context/RouteSessionProvider"
import "./index.css"

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <RouteSessionProvider>
        <App />
      </RouteSessionProvider>
    </BrowserRouter>
  </StrictMode>,
)