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
| `http://localhost:8000/*` | Detect and connect to Sauri on the same Mac, send pending recordings, and read the recording list and results. Recordings are not sent to an external server. |

## Data and privacy
The extension handles user-selected audio and video, microphone audio when enabled, the recorded tab's title and link, preferences, and a local credential. Media chunks and the queue stay in the browser until upload completes; chunks are removed after upload is confirmed. Received recordings and results remain in the local app. The credential is stored only in this profile and restricted to trusted extension contexts, never pages or content scripts. Information is not sold or used for advertising, credit decisions, or purposes unrelated to recording and reviewing meetings. The extension contains no analytics.

The public policy must cover these data types, retention, and deletion in Sauri. Its URL and contact details must be supplied by the owner rather than invented here. The `notifications` permission was removed: status is displayed in the interface without system notifications.
