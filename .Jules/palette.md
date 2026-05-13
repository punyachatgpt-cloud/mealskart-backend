## 2025-05-14 - Modal Focus Management and Keyboard Accessibility
**Learning:** Modals should manage focus by moving it to an interactive element (like a 'Close' button) on open and returning it to the trigger element on close. Additionally, dynamically injected cards that are clickable must have `role="button"`, `tabindex="0"`, and keydown listeners to be accessible to keyboard users.
**Action:** Always implement `lastFocusedElement` tracking and ensure all interactive pseudo-elements (like clickable cards) use semantic roles and handle keyboard events.
