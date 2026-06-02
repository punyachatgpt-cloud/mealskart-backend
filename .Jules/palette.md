## 2026-06-02 - Comprehensive Accessibility Enhancement for Recipe Search
**Learning:** Dynamic content and modals require explicit accessibility management (ARIA live regions, focus trapping/restoration, and keyboard listeners) to be usable by assistive technology and keyboard-only users. Initial button states should also reflect their semantic state (e.g., aria-pressed).
**Action:** Always verify that dynamic status updates have aria-live, interactive non-button elements have appropriate roles and keyboard listeners, and modals handle focus restoration and the Escape key.
