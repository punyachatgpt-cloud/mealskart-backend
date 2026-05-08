## 2026-05-08 - [Accessible Dynamic Cards]
**Learning:** Dynamically injected elements that are interactive must be explicitly made keyboard-accessible by adding 'role', 'tabindex', and 'keydown' listeners, as they don't inherit default button behavior.
**Action:** Always add 'role="button"', 'tabindex="0"', and 'keydown' (Enter/Space) listeners to dynamic card elements.
