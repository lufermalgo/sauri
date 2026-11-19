# Chrome Web Store Listing — Sauri

Last updated: 2026-11-19. Version: 0.9.2. Status: draft, not submitted.

## Store listing
Name: Sauri. Category: Productivity. Primary language: Spanish, with English localization.
Single purpose, short and detailed descriptions: [Spanish](store/es/listing.md), [English](store/en/listing.md).

## Graphics and assets
Store icon: `public/icons/icon-128.png` (128 × 128 PNG).
Current screenshots at 1280 × 800 or 640 × 400 are pending: show the recording panel, app-unavailable notice, and recording controls. No new screenshots are included in this unit.

## Permission justifications
One justification for each of the eight permissions and three host patterns in `manifest.json`:
[Spanish](store/es/permissions.md), [English](store/en/permissions.md).
No notifications permission or broad host access.

## Privacy and data use
The extension handles selected audio/video, optional microphone audio, recorded-tab title/link, preferences, and the local pairing credential. These stay on the device; uploads target the local app. No analytics, advertising, sale of data, credit use, or unrelated data use. Pending media is retained until successful upload; uninstalling or clearing extension data can lose pending media. See the localized permission documents for retention details. Do not claim that no personal data is handled: recordings can contain personal communications and sensitive page content.

## Privacy policy and developer information
Owner must supply a public privacy policy URL, publisher name, contact email, and support URL. These are not verified or invented by this delivery.

## Distribution
Owner intends public Chrome Web Store distribution; owner handles registration, fee, and submission. No publication was performed.

## Version history
| Version | Date | Changes | Status |
| --- | --- | --- | --- |
| 0.9.2 | 2026-11-19 | Finds the desktop app on its new port 41750 and, during the transition, on 8000. Adds the host pattern `http://localhost:41750/*`: same host as before, so Chrome shows no new permission warning (see the permission documents). | Draft |
| 0.9.1 | 2026-11-18 | Automatic desktop pairing without sign-in; offline queue retained; notifications permission removed. | Draft |

## Review notes and packaging
`npm run build -w extension` produces `extension/dist/sauri-extension.zip`. Only built runtime files are included, not source, secrets, dependencies, or this store material. Requires the system `zip` command (available on macOS).

Before submission: owner supplies the missing public/contact fields and screenshots; confirms the production extension ID is allowed by the local app (`SAURI_EXTENSION_ORIGINS`). The known development ID is `ilnkkojmkfnbdilogldabpodoobfigce`; a store-assigned ID is not verified here. Install the generated package with the allowed ID and verify pairing and recording on the real Mac app before submission.
