# Appearance System

This document defines the **appearance, preset, and customization system** for the LightningPiggyApp.
It is the **canonical source of truth** for how presets, partner themes, and advanced settings interact.

This document describes the intended appearance system and serves as a reference for appearance-related features.

---

## Design goals

The appearance system is designed to:

* Provide simple, one-tap presets for common use cases
* Allow deep customization via advanced settings
* Keep partner branding **visual-only**
* Avoid locking users into rigid modes
* Ensure predictable override and inheritance behavior
* Be easy to reason about and implement

---

## High-level model

Preset
→ (optional) Partner Theme
→ Advanced settings overrides
→ Runtime UI

### Core principles

* **Presets define defaults**
* **Partner Themes are visual presets**
* **Advanced settings always override presets**
* **No appearance option changes wallet or backend logic**

---

## Menu structure

Settings

* Wallet type
* Appearance

  * Presets

    * Lightning Piggy (default)
    * Nostr Zaps
    * Lightning Tips
    * Partner Themes (e.g.)

      * Partner #1
      * Partner #2
      * Partner #3
  * Advanced settings

    * Color theme

      * Hex color input
    * Confetti

      * Enabled (On / Off)
      * Style

        * Lightning Piggy
        * Nostr Zaps
        * Lightning Tips
        * Partner #1
        * Partner #2
        * Partner #3
    * QR code

      * Enabled (On / Off)
      * Size (Small / Medium / Large)
      * Placement

        * Top left
        * Top center
        * Top right
        * Center
        * Bottom left
        * Bottom center
        * Bottom right
      * Collapse on payment (On / Off)
      * Return to home after (seconds input)
    * Home screen text

      * Enabled (On / Off)
      * Text (input field)
      * Placement

        * Top left
        * Top center
        * Top right
        * Center
        * Bottom left
        * Bottom center
        * Bottom right
    * Home screen elements

      * Show recent payments (On / Off)
      * Show comments (On / Off)
      * Show Settings button (On / Off)

---

## Presets

Presets provide **predefined starting points** for appearance and layout.

### Base presets

* **Lightning Piggy** (default)
* **Nostr Zaps**
* **Lightning Tips**

Presets may define:

* Layout defaults
* QR visibility, size, and placement
* Home screen text behavior
* Default confetti style
* Default color theme

Presets do **not** modify wallet logic or backend behavior.

---

## Partner Themes

**Partner Themes are visual-only presets** representing supporters of the project.

### Inheritance rule (important)

**Partner Themes behave like the Lightning Piggy preset**, with only the **color theme** and **confetti style** overridden.

All other appearance and layout settings remain identical to Lightning Piggy unless explicitly modified by the user via Advanced settings.

### Purpose

Partner Themes:

* Provide visual branding for supporters
* Do not introduce new functionality
* Do not lock users into specific layouts

### Customization

After selecting a Partner Theme, users can still:

* Modify any Advanced setting
* Combine partner colors and confetti with other layouts
  (for example, a Lightning Tips layout with partner branding)

---

## Advanced settings

Advanced settings allow **fine-grained customization** and always take precedence over presets and partner themes.

---

### Color theme

* Single hex color input (for example `#RRGGBB`)
* Overrides preset or partner color theme
* Invalid or empty input falls back to preset color

---

### Confetti

Controls visual feedback when a payment is received.

* **Enabled**: Turns confetti on or off
* **Style**: Selects confetti theme (base or partner styles)

Confetti style selection is independent of the active preset.

---

### QR code

Controls QR visibility, layout, and behavior.

* **Enabled**: Show or hide the QR code
* **Size**: Small / Medium / Large
* **Placement**: One of several predefined screen positions
* **Collapse on payment**:
  When enabled, the QR code temporarily hides after a payment is received
* **Return to home after**:
  Number of seconds before returning to the default home screen
  (only active when *Collapse on payment* is enabled)

If *Collapse on payment* is disabled, the QR code remains visible during payment feedback.

---

### Home screen text

Controls optional text displayed on the home screen.

* **Enabled**: Show or hide text
* **Text**: User-defined string
* **Placement**: Same placement options as QR code

---

### Home screen elements

Visibility toggles for home screen UI elements:

* Show recent payments
* Show comments
* Show Settings button

**Important:** When the Settings button is hidden, an alternate method for accessing Settings must be available (for example, a double tap in the lower right corner or similar).

---

## Precedence rules (summary)

1. Preset is applied
2. Partner Theme (if selected) overrides preset visuals
3. Advanced settings override everything
4. Runtime UI reflects the final resolved configuration

---

## Non-goals

The appearance system intentionally does **not**:

* Modify wallet behavior
* Modify backend logic
* Enforce restrictions on user customization

---

## Notes for contributors

* This document defines **intent**
* GitHub issues define **implementation work**
* Feature requests related to appearance may reference relevant sections of this document when helpful
* These design concepts may evolve and should be discussed when changes are proposed.

---
