## 2025-05-24 - Enhancing dynamic element accessibility
**Learning:** Elements like `<article>` used as cards for search results are not natively keyboard-accessible. Adding `role="button"` and `tabindex="0"` allows them to be focused, but they do not automatically trigger click events on 'Enter' or 'Space'. Manual `keydown` listeners are required to ensure full parity with native `<button>` elements.
**Action:** When creating interactive dynamic elements that aren't natively focusable, always pair `tabindex="0"` and `role="button"` with a keydown listener for 'Enter' and 'Space' keys.
