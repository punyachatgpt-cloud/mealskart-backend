## 2026-05-22 - Improving Keyboard and Screen Reader Accessibility for Dynamic Content
**Learning:** Screen readers and keyboard users often lose context when content is updated dynamically or when custom interactive elements (like `div` cards) are used without proper ARIA roles and keyboard listeners.
**Action:** Always use `role="button"`, `tabindex="0"`, and keydown listeners for custom interactive elements. Use `aria-pressed` for toggle states and `aria-live` for status updates to ensure all users are notified of state changes.
