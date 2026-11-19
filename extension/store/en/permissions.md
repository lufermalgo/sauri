# Permission justifications

| Permission | Justification |
| --- | --- |
| `tabCapture` | Capture audio and video from the tab the user chooses to record. |
| `offscreen` | Keep recording and saving media chunks even when the user closes the side panel. |
| `storage` | Keep recording and language settings, capture state, and the local Sauri connection credential in this browser without syncing it to a Google account. |
| `tabs` | Read the selected tab's URL and title, detect its closure to finish recording, and find an already opened review to avoid duplicates. No browsing history is collected. |
| `scripting` | Display recording controls and notices in the recorded tab when its page permits injection. |
| `activeTab` | Obtain temporary access after the user clicks the Sauri icon to capture that tab and insert its controls without permanent access to every site. |
| `alarms` | Automatically retry pending uploads and recover processing status when the app or browser is interrupted. |
| `sidePanel` | Show recording controls, settings, and the recording list without leaving the tab. |

## Host access

| Host | Justification |
| --- | --- |
| `https://meet.google.com/*` | Show the recording notice and controls in a Google Meet meeting. The permanent content script is limited to this site. |
| `http://localhost:41750/*` | Detect and connect to Sauri on the same Mac (its own port), send pending recordings, and read the recording list and results. Recordings are not sent to an external server. |
| `http://localhost:8000/*` | The same use with earlier versions of the app, which listen on this port, during the transition. The extension only talks to a program that identifies itself as Sauri. |

### Update from 0.9.1 (no new permission warning)
Chrome disables an updated extension until the user accepts new permissions that carry a warning ([Permission warnings](https://developer.chrome.com/docs/extensions/develop/concepts/permission-warnings)). For host access Chrome compares host names only, without port or path: `IsHostPrivilegeIncrease` relies on `GetDistinctHosts`, which keeps `pattern.host()` (Chromium source: `chrome/common/extensions/permissions/chrome_permission_message_provider.cc` and `extensions/common/permissions/permission_message_util.cc`). Adding `http://localhost:41750/*` keeps the already granted host `localhost`, so there is no escalation. `http://localhost/*` would keep the host too, but it covers every port ([Match patterns](https://developer.chrome.com/docs/extensions/develop/concepts/match-patterns): "Matches any localhost port"), so the two explicit ports are used as the narrowest choice. Still to check before submission: update an installed 0.9.1 package to 0.9.2 (Extension Update Testing Tool or a `.crx` signed with the same key) and confirm no dialog appears.

## Data and privacy
The extension handles user-selected audio and video, microphone audio when enabled, the recorded tab's title and link, preferences, and a local credential. Media chunks and the queue stay in the browser until upload completes; chunks are removed after upload is confirmed. Received recordings and results remain in the local app. The credential is stored only in this profile and restricted to trusted extension contexts, never pages or content scripts. Information is not sold or used for advertising, credit decisions, or purposes unrelated to recording and reviewing meetings. The extension contains no analytics.

The public policy must cover these data types, retention, and deletion in Sauri. Its URL and contact details must be supplied by the owner rather than invented here. The `notifications` permission was removed: status is displayed in the interface without system notifications.
