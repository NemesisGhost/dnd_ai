import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { expect, test } from "vitest";
import { App } from "./App";
import { AuthProvider } from "../auth/auth";

test("renders the portal shell without an auth implementation", () => {
  render(<AuthProvider><MemoryRouter><App /></MemoryRouter></AuthProvider>);
  expect(screen.getByRole("heading", { name: "World Portal" })).toBeInTheDocument();
  expect(screen.getByRole("navigation", { name: "Primary navigation" })).toBeInTheDocument();
  expect(screen.getByText("Authentication pending")).toBeInTheDocument();
});
