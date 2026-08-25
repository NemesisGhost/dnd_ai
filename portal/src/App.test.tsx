import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'
import App from './App'

function renderAppAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )
}

describe('portal routing', () => {
  it('does not show campaign navigation on the login route', () => {
    renderAppAt('/login')

    expect(
      screen.getByRole('heading', { name: 'Log in' }),
    ).toBeInTheDocument()

    expect(
      screen.queryByRole('navigation', { name: 'Campaign' }),
    ).not.toBeInTheDocument()
  })

  it('shows campaign navigation and disables unavailable Ask', () => {
    renderAppAt('/app/mundivita/home')

    expect(
      screen.getByRole('navigation', { name: 'Campaign' }),
    ).toBeInTheDocument()

    expect(
      screen.getByRole('link', { name: 'Home' }),
    ).toHaveAttribute('aria-current', 'page')

    expect(
      screen.queryByRole('link', { name: 'Ask' }),
    ).not.toBeInTheDocument()

    expect(screen.getByText('Ask')).toHaveAttribute(
      'aria-disabled',
      'true',
    )
  })

  it('does not disclose campaign chrome for an unknown campaign', () => {
    renderAppAt('/app/not-a-real-campaign/home')

    expect(
      screen.getByRole('heading', { name: 'Campaign not found' }),
    ).toBeInTheDocument()

    expect(
      screen.queryByRole('navigation', { name: 'Campaign' }),
    ).not.toBeInTheDocument()
  })
})