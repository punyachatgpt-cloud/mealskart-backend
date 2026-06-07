## 2026-06-07 - Accessibility Foundations for Interactive Elements
**Learning:** In a single-page interactive application like this, users expect core interactive elements (cards, toggles) to be keyboard-accessible and provide state feedback. The lack of `role="button"`, `tabindex`, and `aria-pressed` significantly hindered screen reader and keyboard-only usability.
**Action:** Always verify that dynamically generated interactive elements have appropriate ARIA roles and keyboard listeners (Enter/Space) matched to their click behavior.

## 2026-06-07 - Modal Focus and Transition Synchronization
**Learning:** Transitioning modals from `display: none` to `flex` via `opacity`/`visibility` allows for smooth CSS animations but requires careful synchronization with JavaScript focus management. Setting focus to a button within a modal that is still transitioning or not yet `visible` can sometimes be ignored by the browser or screen reader.
**Action:** Use `visibility: visible` along with `opacity` to ensure the modal is in the accessibility tree when active, and consider a tiny delay or transitionend listener if focus is not being captured reliably during rapid transitions.
