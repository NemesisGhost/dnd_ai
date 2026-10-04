import { StrictMode } from "react"
import { createRoot } from "react-dom/client"
import { RouterProvider, createBrowserRouter } from "react-router"
import App from "./App.tsx"
import { RouteSessionProvider } from "./context/RouteSessionProvider"
import { ThemeProvider } from "./themes/ThemeProvider"
import "./index.css"

// A data router (rather than <BrowserRouter>) so authoring forms can use
// useBlocker to protect unsaved changes. A single splat route renders the whole
// application, so App's declarative <Routes> and every existing route are
// unchanged (docs/UI_DESIGN.md §5.11).
const router = createBrowserRouter([
  {
    path: "*",
    element: (
      <RouteSessionProvider>
        <App />
      </RouteSessionProvider>
    ),
  },
])

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <RouterProvider router={router} />
    </ThemeProvider>
  </StrictMode>,
)