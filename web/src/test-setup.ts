import '@testing-library/jest-dom/vitest'
import {cleanup} from '@testing-library/react'
import {afterEach,beforeEach} from 'vitest'
afterEach(cleanup)
// F9: jsdom has no canvas; the visual widgets degrade gracefully, so stub getContext instead of
// letting "Not implemented" errors bury real failures in test output.
HTMLCanvasElement.prototype.getContext=(()=>null) as unknown as typeof HTMLCanvasElement.prototype.getContext
// Each test starts with an empty tab session (F5 persistence must not leak between tests).
beforeEach(()=>{sessionStorage.clear();localStorage.clear()})
