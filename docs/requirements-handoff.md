# CommentScope — Implementation Handoff and Project Requirements

**Last consolidated:** 2026-10-07  
**Team:** 527 — Yoonjae Oh, Jiyoon Lee, Joowon Kim  
**Purpose:** This is the single handoff document for the next implementation-design session. It separates (1) requirements already imposed by the course and the Milestone 2 design, (2) current project decisions, and (3) implementation decisions that are intentionally still open.

**Current implementation status:** No application repository or working MVP exists in this workspace at the time of this handoff. The next session begins implementation/design work; it should not assume that any diagram, PPT, report paragraph, or generated slide is executable code.

---

## 1. Project in one paragraph

CommentScope helps a viewer of one discussion-heavy YouTube video reconstruct and inspect distinct perspectives in a **sampled comment discussion**. Rather than returning one overall summary, it presents a small, dynamically determined set of evidence-bounded Perspective Agents. Each agent represents one recurring perspective found in an assigned set of comments; it is **not** a real person, demographic group, or public opinion. Users can discover perspectives, compare their reasons and conditions, ask the same question across perspectives, and inspect the original comments supporting a response. The central design hypothesis is that separating evidence and interaction state across perspectives preserves meaningful disagreement better than a single model that synthesizes everything into one answer.

---

## 2. Non-negotiable course requirements

These are requirements from the course master document, not optional product ideas.

### Milestone 3 — Low-fidelity prototype

**Studio:** October 29, 2026. **Report due:** October 30, 2026, 23:59.

- Use a digital prototyping tool (normally Figma), not a polished HTML/JS product.
- The prototype may use hard-coded realistic data, Wizard-of-Oz behavior, or fake results.
- It must support a complete end-to-end scenario covering **at least three distinct, connected user tasks**.
- Test it with **at least three people** who are not classmates and do not already know the project; participants should be close to the target user where possible.
- Use a think-aloud protocol.
- Live-demo the scenario in a seven-minute studio presentation; every member speaks.
- The report must include: revised problem statement; three or more user-level tasks; a ≤1-paragraph tool summary; accessible prototype link; intentional non-implementation/design choices; representative screenshots; detailed task instructions; and user-test observations.
- The observation section must report participant background, **10 or more** concrete usability problems organized by task/theme, participant IDs (`P1`, `P2`, …), severity (high/medium/low), and a proposed response for every issue.
- Every member submits the separate peer/self-feedback form.

### Milestone 4 — High-fidelity prototype

**Studio:** November 24, 2026. **Report due:** November 25, 2026, 23:59.

- Build a **fully functional, interactive** system ready for target-user testing.
- Support a complete end-to-end scenario and at least **three distinct, connected tasks**.
- The multi-agent pipeline must actually work; a static mockup alone is not enough.
- Provide a live prototype URL that remains available while grading occurs. Course staff will run it for heuristic evaluation.
- Provide a Git repository URL and concise README explaining the code/main implementation areas.
- List external libraries/frameworks and coding-support tools.
- Include screenshots/callouts and clear instructions focused on the important interactions.
- Each member writes an individual reflection: concrete contribution, difficulty, and one implementation skill learned.

### Milestone 5 — final showcase and report

**Presentations:** December 8 and 10, 2026. **Final report due:** December 18, 2026, 23:59.

- Present the system and support a working in-class demo session.
- The pitch must cover problem, core tasks, solution/difference, interface walkthrough, deployment/user findings, and limitations/future work.
- Final team report: representative annotated screenshots; ≤300-word quality argument; ≤300-word deployment summary with real-user results and visual aids; ≤500-word discussion connected to social-computing concepts.
- The deployment summary **must not use the team members’ own results as user results**.
- Each member submits an individual reflection (≤300 words) through the separate form.

---

## 3. Problem, target user, and scope boundaries

### Problem statement to preserve

> Because YouTube presents discussion-heavy videos’ comments as individually ranked items and separate reply threads, viewers struggle to reconstruct and compare distinct perspectives, reasons, and conditions, limiting informed interpretation of contested issues.

### Target user

A viewer who has watched a discussion-heavy YouTube video and wants to understand **how and why** other viewers interpreted the issue differently.

### In scope

- One YouTube video at a time.
- A fixed/sampled set of comments, retaining reply relationships and source identifiers.
- A small dynamic set of recurring, sufficiently supported perspectives.
- Perspective discovery, comparison, question answering, and source inspection.
- An initial user opinion only as an optional comparison aid, not as a requirement to start.

### Explicitly out of scope

- Estimating public opinion, demographic opinion, or the beliefs of all YouTube users.
- Treating an agent as a real commenter or social group.
- Posting to YouTube, contacting commenters, or moderating comments.
- Persuading a user to change their opinion or deciding which position is correct.
- Supporting every video, every language, or unlimited comments in the first prototype.
- Full production-grade YouTube integration, authentication, accounts, recommendation, or long-term personalization.

### Required wording discipline

Use: **sampled comments**, **recurring perspective**, **evidence-bounded**, **source-grounded**, **may help users identify/compare/inspect**.

Avoid: “public opinion,” “agent represents real people,” “MAS eliminates bias,” “the system broadens understanding,” “the system changes the user’s view,” or “clustering produces ground truth.”

---

## 4. Core user tasks

The Milestone 2 pitch committed to four conceptual tasks. Milestones 3 and 4 require at least three working, connected tasks. Do not silently change the reported flow; if scope must shrink, keep a coherent subset and document the choice.

### Task 1 — Discover distinct perspectives

**User goal:** View the major claims, reasons, conditions, and uncertainty in the sampled discussion without manually reconstructing the structure from ranked comments and reply threads.

**Expected output:** A viewpoint overview/card set. Each card exposes a short stance, important reasons/conditions, confidence or uncertainty where appropriate, and representative source comments.

### Task 2 — Compare perspectives with an initial view or a common question

**User goal:** Select two or more perspectives, optionally alongside an initial opinion, and see where their claims align, differ, or depend on different conditions.

**Expected output:** Side-by-side comparison cards. The system must not collapse the answers into a forced consensus.

### Task 3 — Deep-dive through a follow-up question

**User goal:** Ask one or more selected perspectives a follow-up question and explore the reasoning behind their stance.

**Expected output:** Separate source-grounded answers. In one-to-many interaction, agents answer independently by default; cross-agent response occurs only if the user requests it.

### Task 4 — Verify and reflect

**User goal:** Inspect the original comment/reply context behind a card or answer and decide whether the interpretation is credible; optionally revisit an earlier opinion.

**Expected output:** Claim-level links to original comment context. If reflection is included, the system may propose what stayed the same, changed, or remains unresolved, but the user confirms/edits/rejects those links and the system never judges the user’s final opinion.

### Recommended functional MVP for Milestones 3–4

Implement Tasks **1, 2, and 3** end-to-end as the minimum. Treat the source-inspection part of Task 4 as mandatory trust infrastructure for the first three tasks. Full reflection is the first feature to cut or simplify if time is limited.

---

## 5. What makes this a multi-agent system

### User-facing MAS contract

The project is not “one LLM writing in several personas.” It must preserve these properties:

1. Each Perspective Agent has an assigned evidence set (comment/claim IDs plus reply context).
2. Each Perspective Agent maintains a separate interaction state/history.
3. An agent answers only from its own evidence boundary. When evidence is insufficient, it abstains or expresses uncertainty rather than borrowing unsupported content from another perspective.
4. A Controller routes the same user question to selected agents and displays independent outputs side by side. It does not manufacture a consensus answer.
5. An Auditor evaluates draft answer–citation support and can cause a visible behavioral change: `approve`, `revise`, `add_uncertainty`, or `abstain`.

The same base model may power several agents. The MAS distinction comes from separated state/evidence, independently produced outputs, and a verification role that can reject a draft—not from model diversity alone.

### Required agent responsibilities

| Component | Required responsibility | Not allowed to do |
|---|---|---|
| Perspective Agent | Explain one evidence-bounded perspective; provide claim/reason/condition and citations; maintain its own dialogue state | Speak for public opinion, invent source support, silently use other clusters |
| Auditor | Check whether a claim is supported by cited comments; identify overgeneralization; approve/revise/uncertainty/abstain | Produce a final consensus, decide which view is correct, impersonate a Perspective Agent |
| Controller/UI | Route questions, collect structured outputs, render comparisons, open source evidence | Merge perspective answers into its own interpretation unless a separate, cited feature is later designed |

### Offline clustering layer: current decision

Comment cleaning, deduplication, embedding, and candidate clustering are **not automatically agents**. They may be ordinary preprocessing.

An optional **agent-assisted clustering** layer is permitted if it adds distinct, inspectable roles:

```text
Claim extraction → candidate clusters → Cluster Auditor → accepted/split/merged/uncertain clusters
```

If this layer is implemented, its purpose is quality control, not the primary justification for the project being MAS. It must leave a trace of its input, proposal, and decision. If it is not implemented, describe clustering honestly as preprocessing and keep the user-facing Perspective-Agent/Auditor layer as the primary MAS contribution.

---

## 6. Proposed end-to-end architecture

```text
Video URL / prepared comment sample
        │
        ▼
Ingestion and preprocessing (non-agent by default)
  retain comment ID, author pseudonym/ID if needed, timestamp, likes,
  parent/reply links, text, language; remove exact duplicates/spam
        │
        ▼
Claim-unit extraction (optional in MVP, recommended for quality)
  one comment may yield multiple claim units
  {claim text, issue, stance, reason, condition, source comment ID}
        │
        ▼
Candidate clustering
  semantic candidates; do not force every comment/claim into a cluster
        │
        ▼
Cluster quality gate
  keep / split / merge / uncertain; only supported, distinct candidates become perspectives
        │
        ▼
Perspective specifications
  label, evidence IDs, representative comments, reason/condition summary, uncertainty
        │
        ├─────────────┬─────────────┬─────────────┐
        ▼             ▼             ▼             ▼
Perspective A   Perspective B   Perspective C   Perspective D
  own sources      own sources      own sources      own sources
  own state        own state        own state        own state
        └─────────────┴───────┬─────┴─────────────┘
                              ▼
                   draft structured answers
                              ▼
                         Auditor
                 approve / revise / uncertainty / abstain
                              ▼
               comparison + chat + source-inspection UI
```

### Minimum persistent data model

| Entity | Minimum fields |
|---|---|
| `Video` | `video_id`, title, URL, retrieval date, language, sampling rule |
| `Comment` | `comment_id`, `parent_id`, text, timestamp, likes if available, reply link/context, collection status |
| `ClaimUnit` | `claim_id`, source `comment_id`, claim text, issue, stance, reason, condition, extraction confidence |
| `CandidateCluster` | `cluster_id`, member claim IDs, provisional label, coherence/confidence, status (`candidate/accepted/split/merged/uncertain`) |
| `PerspectiveSpec` | `perspective_id`, title, stance, assigned evidence IDs, reasons/conditions, representative citations, uncertainty note |
| `AgentSession` | `perspective_id`, session/user ID, dialogue history, timestamp |
| `AnswerDraft` | question, perspective ID, claim/reason/condition fields, citation IDs, draft text |
| `AuditDecision` | draft ID, decision, failures, required revision, checked citation IDs |

No answer should be rendered without a traceable `PerspectiveSpec`, `AnswerDraft`, and `AuditDecision` (or an explicit documented fallback during early MVP work).

---

## 7. Perspective formation and cluster-quality requirements

### Why whole-comment clustering is insufficient

One comment can contain a stance plus a condition, two distinct claims, sarcasm, or a reply-specific rebuttal. The unit to group should ideally be a **claim/argument unit**, not necessarily an entire comment.

Example: “Regulation is necessary, but small startups need an exception.”

- issue: AI regulation
- stance: conditional support
- reason: safety/accountability
- condition: avoid disproportionate burden on small startups

This must not be automatically merged with unconditional support merely because both comments have a positive sentiment toward regulation.

### Perspective formation rule

A cluster can become a Perspective Agent only when it is:

1. **Distinct:** a single agent summary would not erase a material difference from another accepted cluster.
2. **Supported:** it has enough interpretable source units/comments to cite.
3. **Coherent:** its members do not contain a substantial internal contradiction that should become a separate perspective or condition.
4. **Traceable:** representative source comments and relevant reply context are retained.

Otherwise retain it as `uncertain`, `mixed`, or an unrepresented outlier rather than forcing it into the nearest agent.

### Practical validation plan

Do not evaluate clustering only by asking the same LLM to rate its own output. Use human spot checks.

| Question | Lightweight measurement |
|---|---|
| Is a cluster internally coherent? | Sample within-cluster claim pairs; two human raters judge whether they express the same perspective. |
| Are two neighboring clusters meaningfully distinct? | Sample close cross-cluster pairs; raters judge whether merging would hide a meaningful difference in stance, reason, or condition. |
| Are meaningful minority views retained? | Compare manually identified low-frequency perspectives with accepted clusters or explicit `uncertain` handling. |
| Does the card/agent faithfully represent its sources? | Show a generated card/answer with cited comments; raters judge claim–citation support and overgeneralization. |

Useful metrics later: within-cluster pair agreement (coherence), cross-cluster separation, coverage/recall of manually found perspectives, claim–citation support rate, abstention rate, and unsupported-claim rate.

---

## 8. Evaluation and baseline requirements

### Research/design question

> With the same comment sample, retrieval tools, and comparable computation budget, does an evidence-bounded Multi-Agent System help users identify, compare, and verify viewpoints better than a Strong Single-Agent?

### Required comparison conditions for a meaningful MAS claim

| Condition | Definition |
|---|---|
| Non-AI baseline | Existing YouTube-style ranked comments/reply threads; users browse themselves. |
| Strong Single-Agent baseline | One model receives the same comment sample, retrieval/citation capability, and comparable budget; it can summarize, answer questions, and self-check. Do not weaken it artificially. |
| Proposed MAS | Separated Perspective Agents with bounded evidence/state plus an Auditor that can reject/revise outputs. |

### System-level measures

- Recall/coverage of manually identified distinct perspectives.
- Recall of conditional and low-frequency perspectives.
- Claim–citation support accuracy.
- Unsupported/overgeneralized claim rate.
- Cluster coherence and cross-cluster separation.
- Latency and API cost (report honestly; cost need not be optimized first).

### User-level measures

- Number of perspectives, reasons, and conditions correctly identified under a time limit.
- Accuracy when explaining the difference between two perspectives.
- Success rate and time for locating source evidence behind an interpretation.
- Task completion time, perceived understanding, trust calibration, and cognitive load.

Do **not** use “the user changed their opinion” as the main success metric.

---

## 9. UI and interaction requirements

The UI needs enough structure to make the MAS difference observable, rather than hiding it behind a chat box.

### Essential screens/states

1. **Input/setup:** video URL or prepared sample selection; optional initial opinion and/or broad question.
2. **Perspective overview:** a limited set of cards; card title, stance, core reason(s), condition(s), source count/representative citations, and uncertainty.
3. **Comparison:** select two or more cards; show independent answers or structured fields side by side; no automatic consensus.
4. **Deep dive:** one selected agent or multi-select agent conversation. Clearly show which perspective is answering.
5. **Evidence inspection:** open original comment and enough reply context to check interpretation; return to the relevant card/answer.
6. **Optional reflection:** initial vs. current view and user-confirmed links to relevant interactions.

### Essential interaction rules

- The user always knows which perspective is speaking.
- Every important agent claim is linked to at least one source comment/claim unit where possible.
- An agent shows uncertainty or abstains when evidence is insufficient.
- Parallel answers remain visually separate.
- The user can inspect, disagree with, or leave a view unresolved.
- A Perspective Agent is labeled as a perspective from sampled comments, not as a person.

---

## 10. Data, safety, and feasibility constraints

### Data constraints

- Start with one carefully chosen discussion-heavy video and a small fixed comment sample; do not begin with broad crawling.
- Preserve parent/reply relationships because conditions and rebuttals often occur in replies.
- Record the sample/retrieval rule so results are reproducible (e.g., date, Top/Newest/reply sampling, count, language).
- Decide one primary prototype language before implementation. Do not claim general multilingual performance.
- Use public comment content only for the project purpose, minimize retained account-identifying information, and avoid exposing unnecessary usernames in the prototype/user study.

### Scope/risk controls

| Risk | Required mitigation |
|---|---|
| Wrong cluster becomes a fake “viewpoint” | Treat clusters as revisable candidates; use source inspection, uncertainty, and split/merge handling. |
| Low-frequency view is discarded as noise | Do not use frequency alone; preserve distinct, supported low-frequency views or explicitly mark uncertainty. |
| Agents hallucinate a generalization | Citation gate plus Auditor decision; cite/abstain rather than fill gaps. |
| Same-model errors are correlated | State this limitation; use separated sources/state, deterministic checks where possible, and human spot checks. |
| Interface encourages confirmation bias | Default to overview/parallel comparison; make contrasting perspectives easy to inspect. |
| Feature scope exceeds the semester | Build one-video, three-task, source-grounded MVP before optional reflection, multi-video support, or production crawling. |

---

## 11. Current ownership and schedule contract

This is the ownership shown in the Milestone 2 timeline. Confirm changes with the team before changing names or task boundaries.

| Person | Primary ownership |
|---|---|
| Jiyoon Lee | Interaction flow, low-fi/high-fi UI, Reflect task, usability-test protocol and synthesis |
| Yoonjae Oh | Comment ingestion/filtering/clustering, source traceability, Discover and Deep-Dive interaction |
| Joowon Kim | Perspective-Agent architecture, evidence boundaries, Compare interaction, integration and high-fi refinement |
| All | Scope/acceptance criteria, milestone reviews, final user study, bug triage, demo/report |

### Working milestones

| Period | Required outcome |
|---|---|
| Oct 7–18 | Confirm MVP scope, dataset strategy, three end-to-end tasks, low-fi interaction flow, and evaluation scenario. |
| Oct 19–30 | Working low-fi prototype, three think-aloud participants, 10+ categorized usability findings, M3 report. |
| Oct 31–Nov 13 | Implement source data pipeline, perspective specs, comparison, and initial audit loop. |
| Nov 14–25 | Accessible high-fi system with three working tasks, repository/README, screenshots/instructions, individual reflections, M4 report. |
| Nov 26–Dec 10 | Real-user deployment/testing, fixes, demo video or reliable live walkthrough, final showcase. |
| By Dec 18 | Final report and individual reflections. |

---

## 12. Decisions deliberately left for the implementation-design session

These are not missing requirements; they are choices to resolve before coding architecture.

1. **Data acquisition:** official YouTube API, manually prepared sample, or both? What is the exact sample/reply strategy?
2. **Prototype language:** Korean, English, or constrained bilingual support?
3. **Argument unit:** comment-level MVP versus claim-unit extraction. Recommended: retain whole comments but design the schema so claim units can be added.
4. **Candidate clustering method:** embeddings plus density/community clustering, LLM structured grouping, or hybrid.
5. **Cluster quality gate:** MVP rules for minimum evidence, coherence checks, `uncertain`, split, and merge.
6. **Auditor implementation:** prompt-based audit, deterministic citation/coverage checks, or hybrid. Define what causes revision versus abstention.
7. **Agent persistence:** per-session in-memory history versus stored session history; define privacy/retention policy.
8. **Stack/deployment:** frontend, backend, database/vector store, model provider, hosting, API-key handling, and demo fallback.
9. **MVP task cut line:** whether reflection is a functional task or a low-fi-only/optional feature after source inspection is complete.
10. **Evaluation protocol:** videos/dataset, annotation guide, rater plan, baseline implementation, task prompts, and participant recruitment.

---

## 13. Definition of done for the first functional MVP

The following demo should work without manual storytelling from a developer:

1. Open one prepared video/comment sample.
2. See a small set of clearly labeled perspectives with representative source comments.
3. Select at least two perspectives and ask the same question.
4. Receive two visibly separate answers, each restricted to its own cited evidence.
5. See an audit result that can approve, revise, add uncertainty, or abstain.
6. Open a cited comment/reply context from each answer.
7. Complete the flow with a sensible failure state when evidence is insufficient.

The following are **not** necessary for the first functional MVP: accounts, recommendation systems, multiple-video comparison, perfect automated clustering, fully open-ended group debate, public deployment at scale, or opinion-change measurement.

---

## 14. Immediate next-session agenda

1. Read Sections 4–7 first; decide the three-task functional MVP.
2. Choose data/sample strategy and write the `Comment`/`ClaimUnit`/`PerspectiveSpec` schema.
3. Choose the smallest architecture that preserves independent evidence boundaries and the Auditor’s authority.
4. Define the first end-to-end demo dataset and acceptance tests.
5. Choose stack and repository structure.
6. Create low-fi screens from the essential UI states in Section 9.
7. Write down any design change that differs from this document and why; do not silently lose the core MAS boundary.

---

## 15. Document authority, links, and known divergences

### 15.1 What a new session should treat as authoritative

| Priority | Document / source | How to use it |
|---|---|---|
| 1 | **This handoff, especially Sections 16.1–16.9** | Latest implementation agreement. It overrides earlier internal drafts when they conflict. |
| 2 | [Official course master document](https://docs.google.com/document/d/1abUH5BCJjXQnEWujXDdby2AUpD-n28xEPGv8QfeT0zM/edit) | Official deliverables, dates, and rubric requirements for M3–M5. |
| 3 | [M2 final presentation](https://docs.google.com/presentation/d/1KBcB5HLzECaMoTwPQtJQzupOlisMYTGpcUpemT_NHjw/edit?slide=id.p#slide=id.p) and [M2 final report tab](https://docs.google.com/document/d/1Q_KmqUlsSWrqj8tjpZ2qOOde7CMDL29qiT-2mA0im2Q/edit?tab=t.wl6a6le5fydh) | Historical submitted/presented artifact: preserve the project narrative, but do not let older wording override later engineering decisions. |
| 4 | [DP1 feedback sheet](https://docs.google.com/spreadsheets/d/1HX0fgL8QptQ63IY1y6Hhxhq9Y5D-M48B91jto8ouwdI/edit?gid=163948747#gid=163948747) and local feedback files | Rationale for avoiding repeated weaknesses: explain why the problem matters; distinguish MAS from personas; do not overclaim outcomes; make visual text readable. |
| 5 | `milestone-2/Milestone2_팀공유용_전체베이스.md` and `research/problem-and-related-work/` | Design rationale and related-work evidence. Consult when writing a report/paper, not as the latest implementation specification. |
| 6 | `archive/` and earlier ideation files | Historical research trail only. Do not use to make current product decisions unless reopening ideation deliberately. |

### 15.2 Local files worth opening in a new session

- Official M2 rubric and context: `milestone-2/requirements/Milestone2_공식요건_및_채점기준.md`
- M2 system/agent rationale: `milestone-2/Milestone2_팀공유용_전체베이스.md`
- M1 MAS justification and prior presentation material: `milestone-1/final/Milestone1_주원파트_영문_복붙용.txt` and `research/problem-and-related-work/`
- Report audit and prior grader feedback: `milestone-2/report/최종보고서_타임라인_복붙용_및_채점점검.txt`
- Final timeline asset: `milestone-2/report/CommentScope_Timeline_and_Responsibilities_Gantt.png`

### 15.3 Known divergences that are already resolved by this handoff

| Earlier artifact says | Current implementation agreement |
|---|---|
| M2 deck/report may use an older problem sentence ending in “shallow, one-sided understanding.” | Use the problem statement in Section 3 for future implementation/papers; historical slides are not rewritten retroactively. |
| Earlier drafts suggest 300 comments or Korean-only as an MVP default. | Target a research corpus of about 1,000 comments/threads; accept multilingual input with user-selected UI/output language and original citations preserved. |
| Earlier M2 language treats filtering/clustering as non-agent preprocessing. | It remains non-agent by default. A narrow offline Cluster Auditor is allowed and will be justified only if V0/V1/V2 evaluation shows value. |
| Some report/storyboard material fixes 6–7 agents or makes every cluster an agent. | Only accepted, sufficiently supported, coherent clusters become full Perspective Agents; rare/uncertain views remain inspectable without an agent. |
| Earlier timeline assigns a final fixed set of four tasks. | Reflection remains part of the intended product, but the exact three-task functional MVP is intentionally deferred until the Perspective Factory is tested. |
| Early documents assume a YouTube crawler or straightforward API-backed public service. | The current scope is a frozen research corpus and a research MVP. Automated crawling/public service expansion is not a current requirement and requires separate platform-policy/data-use review. |

This handoff document is a planning contract, not evidence that a function has already been implemented or evaluated.

---

## 16. Implementation-default specification (added after ambiguity review)

This section converts the earlier design into a buildable default. It is the recommended starting contract for the implementation owner. A team member may propose a change, but the blocking decisions in Section 16.5 must be explicitly agreed before architecture work proceeds.

### 16.1 Comment collection: MVP research contract and policy boundary

**Important scope correction:** CommentScope should be built first as a **research MVP over a small, frozen dataset**, not as a public YouTube-analysis service. Queueing, accounts, arbitrary public-video URLs, broad crawling, and service-scale caching are not requirements for the course or a first paper prototype.

**Do not make an automated YouTube crawler the default collection method.** YouTube’s Terms prohibit accessing the service through automated means such as scrapers unless permitted by YouTube or applicable law. The official YouTube API is technically able to read comment threads, but its developer policies also restrict aggregation, storage, and derived use of API data. A team project should not assume that an API key converts a comment-analysis product into a policy-compliant public service. A future public deployment therefore needs separate platform-policy/legal review or an appropriately authorized data source.

**Default MVP data mode:** a small, versioned research snapshot (`DatasetSnapshot`) selected in advance for a study/demo. It may contain comments collected or licensed through a process the team has separately verified with course staff/platform rules. The prototype accepts a prepared dataset ID, not arbitrary user-submitted YouTube URLs. Do not store/display unnecessary usernames or author profiles.

**Dataset contract:**

- One discussion-heavy video per snapshot; choose one primary language.
- Target approximately **1,000 source comments/threads** for the first research dataset. The architecture should remain testable below 10,000 source comments, but no claim of large-scale service support is made.
- Store: text needed for analysis, parent/reply relation, snapshot date, sample rule, source video ID/URL, and pipeline version.
- Do not claim the dataset is exhaustive, representative of public opinion, or continuously current.
- The UI labels the corpus as “sampled comments from one video” and returns users to the original source for verification.

**Optional feasibility spike, not a product commitment:** if course staff confirm the permitted research use, a developer-only script can test the official YouTube Data API against one video. `commentThreads.list` supports `videoId`, `time`/`relevance` ordering, plain-text output, pagination, and at most 100 threads per call. Thread responses may omit replies, so `comments.list(parentId=...)` is needed when full context is required. This spike must not block the functional prototype and must not be exposed as an open public ingestion service.

**If a permitted API snapshot is used, sampling rule:** request a bounded number of top-level threads from both `relevance` and `time`, deduplicate by comment ID, record origin/rank and collection timestamp, and construct a fixed corpus of approximately 1,000 source comments/threads. The mixed order reduces dependence on one ranking but is not population sampling.

**Official references checked on 2026-10-07:** [YouTube Terms — automated access restriction](https://www.youtube.com/t/terms), [YouTube Data API developer policies](https://developers.google.com/youtube/terms/developer-policies), [commentThreads.list](https://developers.google.com/youtube/v3/docs/commentThreads/list), [comment implementation guide](https://developers.google.com/youtube/v3/guides/implementation/comments), and [comments.list](https://developers.google.com/youtube/v3/docs/comments/list).

### 16.2 Concrete clustering pipeline

The system must not cluster by sentiment alone. A perspective is operationalized as a sufficiently supported combination of **issue + stance + reason and/or condition**.

```text
Comment snapshot
  → normalization / exact-deduplication / obvious non-discussion filter
  → claim-unit extraction (one comment may produce 0..n units)
  → structured fields: issue, stance, reason, condition, source comment ID
  → embedding and candidate-neighbor retrieval
  → candidate clusters of compatible units
  → cluster quality gate: keep / split / merge / rare-or-uncertain
  → PerspectiveSpec objects
  → user-facing Perspective Agents
```

**Stage A — normalize and retain, do not erase evidence**

- Normalize whitespace and URLs; retain the original displayed text separately.
- Exact duplicates may be collapsed for analysis but retain a count and source IDs.
- Filter only clearly empty, spam-like, or non-discussion material. Do not remove a low-frequency opinion merely because it is unpopular or short.
- Preserve source IDs and reply links throughout every transformation.

**Stage A.5 — perspective eligibility gate**

The product’s purpose is to expose **meaningful diversity of interpretation**, not to turn every distinct string into a conversational perspective. Before candidate clustering, assign every retained item one of the following statuses:

| Status | Handling |
|---|---|
| `argument_or_experience` | Contains an interpretable claim, reason, condition, or relevant lived experience; eligible for claim extraction and perspective formation. |
| `contextual_reaction` | A reply such as “I agree” or “exactly” that may support a parent claim but has no standalone interpretation; attach to parent context if resolvable, never create a standalone perspective. |
| `question_or_request` | A relevant question without a stated position; retain as context or a possible user prompt, but do not cluster as a viewpoint by default. |
| `non_substantive` | First-comment notices, generic cheering, meme-only reactions, off-topic conversation, or content with no recoverable interpretation; retain only for provenance/counting, exclude from perspective formation. |
| `spam_or_duplicate` | Obvious promotion, repeated boilerplate, or duplicate text; exclude from analysis while retaining an audit count. |
| `unclear` | The model cannot safely determine whether the item contributes an interpretation; do not force it into a perspective. |

This gate must be conservative: a low-like, short, or unpopular comment is **not** automatically non-substantive. The criterion is whether it offers an interpretable position/reason/condition relevant to the focal issue. Human spot checks must measure false removals, especially for low-frequency views and multilingual items.

**Stage B — claim-unit extraction**

Use a structured model call (batched if necessary) to extract zero or more units from a comment:

```json
{
  "source_comment_id": "...",
  "units": [
    {
      "claim_text": "short faithful paraphrase",
      "issue": "what is being discussed",
      "stance": "support | oppose | conditional | mixed | neutral | unclear",
      "reason": "why, if stated",
      "condition": "when/for whom, if stated",
      "confidence": 0.0
    }
  ]
}
```

Extraction is allowed to return `unclear` or no unit. It must not invent a reason/condition absent from the text. This stage can be a single structured model workflow; it does not need to be called a user-facing agent.

**Stage C — candidate clusters**

- Embed `claim_text` together with issue/stance metadata.
- Never place obviously incompatible stances in one candidate cluster merely because they use the same topic words.
- First partition/group by issue where possible; within an issue, cluster compatible stance/reason/condition units using semantic similarity.
- Generate a human-readable provisional label from the cluster evidence, not from a generic topic label.
- A comment with two claims may contribute two distinct claim units. A claim unit belongs to at most one accepted PerspectiveSpec in the MVP, so evidence boundaries remain inspectable.

**Stage D — cluster quality gate**

For every candidate cluster, inspect representative members and nearest competing clusters. The gate returns one of `accept`, `split`, `merge`, `rare`, or `uncertain`.

- `accept`: at least **3 distinct source comments** support a coherent perspective, and representative comments can be cited.
- `split`: materially incompatible stance, reason, or condition would be hidden by one card.
- `merge`: two candidates differ only in wording and a single card would not hide a material distinction.
- `rare`: a distinct perspective has fewer than 3 sources. Preserve it in a collapsed “rare/uncertain perspectives” section; do not silently discard it.
- `uncertain`: evidence is ambiguous, contradictory, too weak, or extraction confidence is low. Do not create a conversational agent for it in the MVP.

The gate may initially be an LLM-powered Cluster Auditor with a strict structured output. It is an **offline quality-control agent**, not the main claim for why the product is MAS. Log the evidence IDs, proposed operation, and rationale.

**UI consequence:** only accepted, sufficiently supported clusters become full Perspective Agents. Distinct but low-support items remain discoverable in a separate `Rare or unresolved perspectives` section with their original comments, but they do not receive a conversational agent that would falsely imply a stable group viewpoint.

**Stage E — card and agent creation**

An accepted cluster becomes a `PerspectiveSpec` containing: title, issue, stance, concise claim, reasons, conditions, evidence IDs, representative comment IDs, and uncertainty/coverage notes. The corresponding Perspective Agent can access only this object and its referenced source text/reply context.

### 16.3 MVP application architecture and a deliberately deferred service path

The high-fi deliverable should be a small runnable application over prepared snapshots, not a public multi-tenant service. A single local/server process is enough.

```text
Browser
  SELECT /analyses/:dataset_id {optional initial_view}
       ↓
API server loads a versioned prepared DatasetSnapshot
       ↓
Pipeline: preprocess → cluster → audit → PerspectiveSpecs
       ↓
Local database/JSON saves artifacts for the study session
       ↓
Browser receives completed analysis
       ↓
Overview / compare / ask / inspect-source endpoints read the snapshot
```

**Minimum endpoints:**

| Endpoint | Responsibility |
|---|---|
| `GET /analyses/:dataset_id` | Return snapshot metadata, sampling disclosure, and accepted perspectives. |
| `POST /analyses/:id/compare` | Route a common prompt/initial view to selected Perspective Agents; return independent audited cards. |
| `POST /analyses/:id/conversations` | Ask one or several agents a follow-up question; retain separate per-agent state. |
| `GET /analyses/:id/evidence/:comment_id` | Return permitted source comment/reply context and the link back to YouTube. |

**MVP storage:** versioned JSON plus SQLite (or just JSON during the first vertical slice) is sufficient, provided evidence IDs and audit decisions are retained for the demo/study. A vector store is optional; a local similarity index is adequate for one-video datasets. Do not introduce a distributed queue, multiple services, user accounts, rate limits, or public multi-tenancy before the core flow works.

**What can become a later service only after separate data/policy review:**

1. Obtain a platform-compliant, authorized data-acquisition method before accepting arbitrary public URLs.
2. Add snapshot expiry/deletion and a privacy notice before storing any external-user data.
3. Add a queue/worker only when multiple concurrent analyses are genuinely needed.
4. Add persistent retrieval/vector infrastructure only after it is a measured bottleneck.
5. Add multilingual or multi-video analysis only after a one-language, one-video study has validated the core mechanism.

### 16.4 Recommended build phases

| Phase | What works | Purpose |
|---|---|---|
| 0 — low-fi | Prepared comment snapshot and hard-coded PerspectiveSpecs in Figma | Validate whether users understand cards, comparison, evidence links, and task flow. |
| 1 — vertical slice | One prepared JSON sample → 3–5 manually reviewed PerspectiveSpecs → separate agents/auditor → comparison UI | Prove source boundary, audit loop, and interaction before API complexity. |
| 2 — automatic pipeline | Prepared snapshot → preprocessing/candidate clusters → human/developer inspection → PerspectiveSpecs | Prove clustering and audit feasibility without coupling the demo to external collection. |
| 3 — automatic perspective formation | Structured claim extraction + embeddings + cluster gate + agent creation | Replace manual PerspectiveSpecs while retaining logs and fallback. |
| 4 — research-prototype hardening | Failure states, deployment, fallback datasets, and evaluation instrumentation | Make the high-fi demo reliable and testable. |

The required implementation order is **not** “build the most intelligent clustering first.” First prove the end-to-end user experience with traceable evidence; then automate perspective formation without breaking that contract.

### 16.5 Decisions the implementation owner needs explicit team agreement on

The implementation owner should not be expected to infer these from a pitch slide. Record one answer for each before building Phase 1.

| Decision | Recommended default | Why agreement is needed |
|---|---|---|
| Language policy | **Multilingual input; UI/output follows the selected UI language; original citations remain visible** | Requires multilingual embeddings, language identification, and an explicit translation/quality policy. “All languages” must be a best-effort input goal, not an equal-quality claim. |
| Data source and permission | **Prepared, versioned research snapshots; no automated crawler/public URL ingestion** | Determines whether the corpus can be used safely and whether the demo is reproducible. |
| User input in high-fi | **Choose one prepared dataset; keep 2 fallback samples** | Removes platform/API failure from the core demo while preserving the end-to-end analysis experience. |
| Comment sample | **About 1,000 source comments/threads for the first dataset; architecture smoke-tested below 10,000** | Sets a realistic analysis budget while keeping the research question broader than a tiny hand-picked example. |
| Data retention | **Keep only the study/demo snapshot; minimize author identifiers; set deletion/expiry** | Determines schema, privacy statement, and deployment risk. |
| Functional core | **To be validated after the first cluster/agent prototype; M3/M4 must still implement at least three connected tasks** | Task boundaries should follow what the evidence-bounded agent pipeline can genuinely support. |
| Reflection feature | **Retain it as a design requirement; decide its minimum functional form after the cluster/agent prototype** | Reflection is part of the intended experience, but should not delay validation of perspective formation. |
| Perspective formation | **Claim extraction + embedding candidates + offline Cluster Auditor; manual fallback** | Decides interfaces between pipeline, model calls, and UI. |
| Agent policy | **Separate evidence/state; Auditor may reject/revise/abstain** | This is the non-negotiable MAS boundary and affects every API/UI response. |
| Model/API and budget owner | **One provider/key owner and server-side secret handling** | Required before team members can test the shared prototype. |
| Evaluation dataset | **3 fixed discussion-heavy videos plus a small labeled subset** | Needed to test clustering, baseline, and later user tasks fairly. |

### 16.6 What the team may defer without blocking implementation

- Exact clustering algorithm/library and hyperparameters.
- Whether the Cluster Auditor is an LLM prompt, a second model, or hybrid rules.
- Persistent versus in-memory agent history beyond one study session.
- Visual styling, account/login, social sharing, recommendation, and general public launch.
- Multiple languages, complete reply retrieval for every thread, and multi-video analysis.

### 16.7 Acceptance tests for the implementation owner

Before calling a vertical slice complete, demonstrate all of the following using one fixed sample:

1. The same user question sent to Perspective A and B produces two separate outputs, each containing only IDs from its own evidence set.
2. If a draft makes a claim not supported by its cited evidence, the Auditor returns `revise`, `add_uncertainty`, or `abstain`; the unapproved draft is not shown as final.
3. A user can open every displayed citation and see the original text plus available parent/reply context.
4. A `rare` or `uncertain` candidate is not silently relabeled as a confident major perspective.
5. Analysis metadata displays video ID, retrieval time, sample size, sampling rule, and pipeline version.
6. An invalid URL, comments-disabled video, and model/API failure each show a recoverable UI state.
7. The prepared fallback sample can complete the full demo without any live external API call.

### 16.8 First engineering target: the Perspective Factory

The first implementation target is **not** the final UI and not open-ended multi-agent chat. It is the Perspective Factory: a repeatable process that turns approximately 1,000 multilingual source comments into a reviewable set of PerspectiveSpecs.

```text
Frozen multilingual comment snapshot
        │
        ▼
1. Retain provenance and normalize text
        │
        ▼
2. Claim Extractor
   comment → zero or more structured claim units
        │
        ▼
3. Multilingual embedding + candidate grouping
   retrieve semantically close, stance-compatible claim units
        │
        ▼
4. Cluster Review
   inspect cohesion, near-neighbor clusters, rare views, and citations
   → accept / split / merge / rare / uncertain
        │
        ▼
5. PerspectiveSpec Builder
   accepted cluster → title, claim, reasons, conditions, source IDs, uncertainty
        │
        ▼
6. User-facing Perspective Agent
   receives only this PerspectiveSpec and its allowed evidence
```

#### Multilingual policy

- Preserve the original comment text and detected language for every source.
- Use a multilingual embedding model so semantically similar claims can become candidates even when they are expressed in different languages.
- Generate a card/agent response in the user-selected UI language, but show the original cited comment. If translation is displayed, label it as a translation and allow users to return to the original text.
- Do not claim that all languages have equal extraction, translation, or clustering quality. Unsupported/low-confidence language cases must be eligible for `uncertain` rather than forced into a confident perspective.

#### Two possible structures for the Factory

**Structure A — pipeline plus one Cluster Auditor (recommended first build)**

```text
structured claim extraction → embedding candidates → deterministic clusterer
                                                ↓
                                      Cluster Auditor
                                   accept / split / merge / uncertain
```

The extractor and clusterer are tools/pipeline stages. The Auditor is an offline agent with a narrow role. This is the smallest structure that lets the team inspect whether model-assisted review improves cluster quality without building a complicated agent society before the user-facing MAS exists.

**Structure B — multi-agent cluster construction (research extension)**

```text
Claim Proposal Agents (data shards)
        ↓ proposals
Cluster Builder
        ↓ candidate clusters
Boundary Auditor + Minority/Coverage Auditor
        ↓ split / merge / rare / uncertain recommendations
Coordinator records final PerspectiveSpecs
```

This can be a genuine temporary MAS even though it runs before a user arrives: agents have separate evidence shards/roles, exchange explicit artifacts, and their decisions affect final cluster membership. However, it adds a second research claim: that multi-agent cluster construction is better than a simpler pipeline. Do not adopt Structure B until Structure A is measured and a clear failure of Structure A justifies the extra complexity.

#### First experiment before task/UI decisions

Run the same frozen corpus through these three variants and manually inspect a stratified sample of output clusters:

| Variant | Question it answers |
|---|---|
| V0: raw multilingual embeddings + clustering | Is semantic clustering alone already coherent enough? |
| V1: structured claim units + embeddings + clustering | Does extracting issue/stance/reason/condition reduce mixed clusters? |
| V2: V1 + Cluster Auditor | Does an explicit review agent improve split/merge/rare handling enough to justify its complexity? |

Record cluster count, source-comment coverage, number of rare/uncertain items, within-cluster coherence, near-cluster separation, and claim–citation support. Two human raters should review a manageable sample rather than attempting to label all 1,000 comments. Only after this experiment should the team freeze: (a) whether the Auditor is part of the implemented pipeline, (b) how many accepted perspectives appear in the UI, and (c) which user tasks are technically credible for Milestone 3/4.

### 16.9 Decision log — current team direction

| Item | Current direction | Status |
|---|---|---|
| End-to-end pipeline | Claim extraction, candidate clustering, review/audit, PerspectiveSpec creation, and Perspective Agents are all intended components; build them in phases rather than as one first commit. | Agreed direction |
| Corpus scale | First research corpus around 1,000 comments/threads; keep designs testable below 10,000. | Agreed direction |
| Languages | Multilingual input is desired. Output/UI language is a user setting; original source text remains inspectable. | Agreed direction; quality policy still needed |
| Cluster study | Run V0 (embedding), V1 (structured claims), V2 (+ Auditor) on the same corpus. | Agreed direction |
| Task scope | Do not freeze the final three-task implementation until the Perspective Factory is tested. Course still requires ≥3 connected functional tasks at M3/M4. | Deferred intentionally |
| Reflection | Keep as a product requirement, but phase its implementation after the perspective pipeline is stable. | Agreed direction |
| What counts as a perspective | Only a meaningful, traceable, sufficiently supported interpretation becomes a full agent. Spam/non-substantive material is excluded; rare meaningful views remain visible without becoming a full agent. | Design rule adopted |
| MAS contribution claim | Decide whether the offline Cluster Auditor is a research contribution only after V0/V1/V2 evidence. User-facing evidence-bounded agents and audit authority remain the core hypothesis. | Deferred intentionally |
