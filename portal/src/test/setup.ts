import '@testing-library/jest-dom/vitest'
import { cleanup, configure } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(() => {
  cleanup()
})

// The default 1s for findBy*/waitFor is too tight for a loaded CI runner; a lookup that is going
// to succeed does so as soon as it can, so a longer ceiling only slows genuine failures.
configure({ asyncUtilTimeout: 8000 })
