## 2026-06-04 - Keyboard Accessibility for Dynamic Content
**Learning:** Dynamically injected interactive elements (like recipe cards) require explicit 'tabindex="0"', 'role="button"', and 'keydown' listeners (Enter/Space) to be accessible to keyboard users. Focus indicators via ':focus-visible' are crucial for navigation clarity in grid layouts.
**Action:** Always include keyboard event handlers and ARIA roles when generating dynamic interactive elements in JavaScript.
