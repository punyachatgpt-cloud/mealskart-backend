## 2025-05-14 - Accessibility and Keyboard Navigation Improvements
**Learning:** Interactive elements like custom selection buttons and dynamic cards require explicit ARIA roles and keyboard event handlers to be accessible to screen reader and keyboard-only users.
**Action:** Consistently apply `role="group"`, `aria-pressed`, and `tabindex="0"` with `keydown` listeners to all custom interactive components.
