## 2026-06-06 - [Accessibility & Modal Focus Management]
**Learning:** For SPAs with dynamic content, adding `role="button"`, `tabindex="0"`, and keydown listeners to interactive cards is essential for keyboard parity. Managing focus when opening/closing modals (saving `document.activeElement`) prevents focus loss and improves navigation flow for screen reader users.
**Action:** Always wrap selection buttons in `role="group"` with `aria-labelledby`, and ensure dynamic results are both focusable and actionable via keyboard.
