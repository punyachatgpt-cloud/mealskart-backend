## 2025-05-15 - Enhancing Keyboard Accessibility for Dynamic Content
**Learning:** Interactive elements generated dynamically (like recipe cards) must be explicitly made keyboard-accessible by adding `role="button"`, `tabindex="0"`, and keydown listeners. Using `:focus-visible` ensures focus indicators only appear for keyboard users, maintaining visual polish for mouse users.
**Action:** Always include keyboard event listeners alongside click listeners for dynamic UI components and use ARIA attributes like `aria-pressed` for toggle states.
