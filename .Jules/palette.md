## 2026-05-28 - [Accessibility and Focus Management Improvements]
**Learning:** Adding `aria-live` to status regions and implementing focus management for modals significantly improves the screen reader experience. Toggling `aria-pressed` on custom choice buttons provides necessary state feedback that standard classes like `.selected` do not convey to assistive technologies.
**Action:** Always include focus management (capture/restore) for modals and use ARIA live regions for dynamic status updates in future UX improvements.
