## 2025-05-15 - [Keyboard Accessibility for Dynamic Cards]
**Learning:** Dynamically injected interactive elements (like recipe cards) often miss keyboard support. Simply adding a click listener is insufficient for users who rely on screen readers or keyboards.
**Action:** Always add `role="button"`, `tabindex="0"`, and a `keydown` listener (for Enter/Space) when creating clickable elements that aren't native `<button>` or `<a>` tags.

## 2025-05-15 - [Modal Focus Management]
**Learning:** Opening a modal without shifting focus can leave keyboard users stranded. Closing it without returning focus breaks the user's navigational flow.
**Action:** Programmatically `.focus()` the primary action (e.g., 'Close' button) when a modal opens, and return focus to the trigger element when it closes.
