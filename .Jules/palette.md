## 2025-05-15 - Keyboard Accessibility for Dynamic Content
**Learning:** Dynamically injected interactive elements (like recipe cards) are often overlooked in keyboard navigation. They must be explicitly made focusable with `tabindex` and handled with keyboard event listeners.
**Action:** Always add `tabindex="0"`, `role="button"`, and a 'keydown' listener for 'Enter'/'Space' to any dynamic element that acts as a button.
