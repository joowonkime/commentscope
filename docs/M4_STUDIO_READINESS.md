# Studio 4 readiness and first-use QA

Checked November 24, 2026 KST against the published assignment and the TA's clarification about first-time and off-script use. The prototype is live on the same public origin. Reviewers can use it without installation, an account, a YouTube key or an OpenRouter key. The three prepared discussions are SBS (750 processed comments, 11 perspectives), Jubilee (180, 2) and CNBC (96, 4). [Public prototype](https://35.212.169.73/mvp) · [Official assignment](https://docs.google.com/document/d/1abUH5BCJjXQnEWujXDdby2AUpD-n28xEPGv8QfeT0zM/edit)

| Official criterion | Evidence available to a reviewer | What still depends on people or time |
|---|---|---|
| Project summary · 10% | Three sentences describe the problem, solution and distinguishing approach. The report names three tasks a reader can perform: inspect comment-based perspectives, trace common ground or disagreement, and record a personal judgment. | Staff judge clarity and the social value of these tasks. |
| Instructions · 20% | The English report has four captioned screenshots with numbered callouts. They cover selecting topics and sources, following a supporting turn, and saving and reopening a reflection. The presenter guide covers the wider feature set. | A first-time reader may interpret evidence and population shares differently from the team. |
| Implementation notes · 10% | Public HTTPS, anonymous repository access and the README were checked. The report lists generation and verification, frontend/backend, design, coding and QA tools, and browser/session requirements. | The service must remain usable until grading. Its scheduled window ends December 14 at 08:02 KST. The grader's actual completion date is unknown. |
| Prototype · 40% | Real provider calls produced grounded turns, a unanimous synthesis on Jubilee and a useful incomplete outcome on CNBC. Off-script browser testing included first use, alternative navigation, recovery, source access, persistence and keyboard/mobile operation. | Across these checks we observed partial replies and a withheld synthesis. Quality across arbitrary topics, novice task success and improvement over single agents have no established rate. |
| Individual reflections · 10% | The report has an insertion point. Each person is asked for their direct contribution, a difficulty and one specific implementation skill. | Each member must author their own text. Until all three are merged, the team archive is a draft. |
| Studio presentation · 10% | Four-slide English deck, presenter notes, a 6:25 live script, speaker handoffs and an explicitly labeled saved example are prepared. | All team members participate in the actual presentation. Maximum seven minutes, followed by about eight minutes for questions. Delivery and rehearsal remain human tasks. |

## Public browser checks

The three-speaker journey passed 25 assertions. A separate first-time shortcut passed nine. The counts describe specific assertions in automated Chromium sessions. They do not count human testers or estimate the probability of a successful visit.

| Off-script choice | Observed behavior |
|---|---|
| Try an invalid address and a valid video absent from the catalog | Both returned a suitable message. The visitor kept the current video and their draft. The browse button opened the three available videos. |
| Use keyboard, Back, Forward and Escape in Library | Library opened, closed and reopened. Focus and a typed draft were retained. One deliberately simulated catalog 503 recovered with Retry loading videos in the same dialog. |
| Be a new visitor when eight sessions are already retained | The old build returned 429 globally. The grading window now allows 64 active browser sessions. A fresh ordinary visitor received HTTP 201 beyond eight. The local default remains eight. |
| Skip the initial view and switch to Reflect before holding any chat | Writing one remaining question worked. A double-click saved one record. Start over preserved access through Library. A separate clean profile saw only its own empty history. This whole path made zero model requests. |
| Select 0, 1, 2, 3, then try 4 perspectives | The action was disabled with no choice. One offered 1:1. Eligible groups offered debate. The fourth selection was rejected while the first three remained selected. |
| Open a source and change language inside the dialog | The original comment remained verbatim. The interface labels followed the language setting. Four width checks at 320, 390, 768 and 1280 px found no horizontal overflow. |
| Double-click Start and refresh during a three-person debate | The public server received one debate start. The same room reopened, with two speaking slots per participant. The 54-second outcome was incomplete, and the same three speakers could be chosen for a follow-up conversation. |
| Save an unanswered question after that debate, close the browser and reopen Library | The exact saved words returned. Reopening the debate, reflection and follow-up picker issued zero writes. |
| Clear a current-opinion draft, leave Reflect and return | A focused browser regression verifies the empty draft is retained. The author can restore their own initial wording or keep editing. |

Two runs used the live provider during this review. The Jubilee teacher/detector question produced four turns, three full and one partial. Both agents accepted two claims. The advice to discuss the work and inspect drafts was explicitly generated reasoning. The source comments could not establish detector accuracy or student misconduct. The browser confirmed the accepted start. A test assertion ran before the restored screen had finished rendering, so the completed Jubilee transcript and acceptance records were verified in the operator's read-only record for that exact question. Browser recovery itself was demonstrated on the separate three-speaker run.

The CNBC group produced six turns, five full and one partial. All three agents participated twice. The conclusion listed an unanswered point and offered a follow-up conversation. The viewer saved a question manually. On the previous day's public CNBC two-person run, the agents ratified three claims in 53 seconds and answered a question addressed to the consensus agent. These are different rooms and questions.

| Public billing observation | Completed calls | USD |
|---|---:|---:|
| Jubilee two-speaker run, ledger delta | 14 | 0.066512704 |
| CNBC three-speaker run, ledger delta | 12 | 0.088427022 |
| Total during these two checks | 26 | 0.154939726 |

The shared evaluation ledger showed USD 0.323826560 charged out of its USD 2 window after these runs, with no outstanding charge. A balance observation is not a cost forecast for other questions. The hosting deadline and model spending cap still apply. [Operator and team QA](M4_TEAM_QA_HOSTING.md)

## Regression, access and release

- Isolated Chromium with synthetic provider results passed 27 seeded journey checks, 29 consensus checks, 24 no-consensus checks and 23 verification-hold checks. Scenarios include restoring the last room, paused work, links to parent evidence and saving/reopening reflections. The simulator supplies deterministic outcomes; real output quality is described above.
- The product suite passed 2,809 Python tests and the browser/JavaScript suites passed 27 checks. The public Before, Library, Explore, Converse and Reflect screens had zero automatic WCAG A/AA findings across ten viewport/language combinations. Eight scans left color contrast for manual review. Earlier targeted tests also checked contrast, focus and hit targets. These checks do not constitute an accessibility certification.
- The public interface includes a direct catalog entry and retry, clearer optional starting text and draft preservation. Only the new hosted plan raises browser-session capacity. The same store, money owner, spend scope, source bundles and deadline were retained. A versioned backend also validates the sole eligible TypeSafe endpoint under its published ZDR tag, with the original provider, model, context and price checks. Existing saved records and original comments were read on the new release. [Public interface revision](https://github.com/joowonkime/commentscope/tree/11939a57291439c006b112897802f73543315445) · [Backend revision](https://github.com/joowonkime/commentscope/tree/6198a0f5af37b934d50f6dea5fc04fb22c372967) · [OpenRouter routing documentation](https://openrouter.ai/docs/guides/routing/provider-selection)
- The assignment requires one ZIP with the team PDF and an images directory. The team should rehearse and assemble the individually authored sections before submission on **November 25 at 23:59 KST**. [English presenter guide](M4_PRESENTER_GUIDE_EN.md) · [M4 requirements](https://docs.google.com/document/d/1abUH5BCJjXQnEWujXDdby2AUpD-n28xEPGv8QfeT0zM/edit)
