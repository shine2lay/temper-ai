# Context playbook: what people prefer and trust, by product, page and user

Version 1.0, 2026-10-04. Design queue #37 (owner m02639). Generated from the Design research playbook (~/design-lab/research/ui-preferences/playbook.json); edit that file, not this one.

Pick the context closest to the page being designed (product x page x user). Use 'styles.preferred' as the starting style family, stay inside 'avoid', and check the design against the listed measures. Evidence ids (E###) point to evidence.jsonl; confidence says how much the evidence carries the advice (high = A/B evidence that fits this context directly; medium = A/B evidence from a neighbouring context or mixed findings; low = mostly C/D or extrapolated). Where evidence is thin, test with users before committing.

## Rules for every context

- The first screen is judged in about 50 ms on visual complexity and typicality: keep the first view calm and recognisable for its category; put novelty in details, not structure. (E001, E002, E005, E025; confidence high)
- Every interactive element needs a visible signifier (shape, border, shadow or colour that says clickable); flat without signifiers costs scanning time. (E055, E056, E057; confidence high)
- Never place text on translucent or busy backgrounds without a solid scrim that keeps WCAG contrast. (E067, E068, E100; confidence medium)
- Light mode is the default for reading; offer dark mode, and test small text in dark mode especially. (E060, E061, E063, E059; confidence high)
- Motion: 100-500 ms, ease-out, animate changes of view not data over time, no parallax or large scroll effects without a reduced-motion path. (E088, E089, E080, E082, E090, E091, E092, E093; confidence medium)
- Waits: real speed first; then show the next content early, a moderate-speed progress animation, and percent-done for waits over a few seconds. (E087, E077, E078, E074, E084, E086; confidence high)
- No dark patterns: visible prices and fees, equal-weight reject and cancel, no trick questions or obstruction; they lift short-term numbers and cost trust. (E032, E033, E035, E039, E037; confidence high)
- Colour meaning claims are weak: choose colour for contrast, grouping and consistency, not for psychological effects. (E101, E102, E100; confidence high)
- Judge daily tools after repeated use, not first sight; first-impression and preference votes overstate novelty. (E020, E160, E163, E161; confidence medium)

## Contexts

- [RollCall: expert trader's main workspace (dashboard, chart, positions) on desktop](#rollcall-trader-workspace)
- [RollCall: data tables (watchlists, orders, trade history) for the expert](#rollcall-trader-tables)
- [RollCall: learner's first run and onboarding](#rollcall-learner-onboarding)
- [RollCall: lessons and explanations for learners](#rollcall-learner-lessons)
- [RollCall: order entry and confirmation (any user)](#rollcall-order-entry)
- [RollCall: mobile check-ins (positions, alerts) on the go](#rollcall-mobile-check)
- [Temper: developer console (workflow runs, logs, agent graphs)](#temper-dev-console)
- [Temper: AI agent output, review and correction screens](#temper-ai-results)
- [Temper: marketing and landing pages for a developer audience](#temper-marketing)
- [Marketing and landing pages (consumer or business)](#marketing-landing-general)
- [SaaS and B2B apps: settings, admin and forms](#saas-b2b-settings)
- [Empty states in any app](#empty-states)
- [E-commerce product pages and checkout](#ecommerce-checkout)
- [Health information and services](#health-info)
- [News, editorial and long reading](#news-editorial)
- [Education and children's products](#education-kids)
- [Government and public services](#government-public)
- [Luxury and fashion brands](#luxury-fashion)
- [Portfolios and agencies](#portfolio-agency)
- [Social, video and entertainment feeds](#social-entertainment)
- [Any product with many older users (45+)](#older-adults-any)
- [Games and game-like interfaces](#games)

### RollCall: expert trader's main workspace (dashboard, chart, positions) on desktop
<a id="rollcall-trader-workspace"></a>

Product: trading and finance app. Page: dashboard. Users: expert owner-trader, daily use. Device: desktop, large screen. Confidence: **medium**.

- **Styles:** preferred flat 2.0 / restrained Material with clear signifiers; classical aesthetics (ordered, aligned, grid); acceptable dark theme variant for long sessions and dim rooms. Experts gain from dense, well-grouped displays and lose speed from novice scaffolding; classical order is the part of beauty that is also usable (E132, E131, E022, E045).
- **Density:** High but grouped: many numbers per view, separated by alignment and spacing between groups; grouping helps experts make fewer errors (E132). Clutter measured, not guessed (E173).
- **Depth:** Minimal: one layer of elevation for panels and menus; signifiers on every control (E055, E057).
- **Motion:** Almost none on data: no animated trends, no confetti; brief transitions only when a view changes (E080, E082, E127).
- **Colour:** Neutral base, one accent; gains and losses by colour plus sign or icon (not colour alone); contrast checked by number (E100, E101).
- **Type:** Tabular figures, 14-16 px minimum for numbers, clear hierarchy by weight; line length irrelevant for tables but labels must be readable (E094, E097).
- **Imagery:** None decorative; charts are the imagery.
- **Avoid:** gamified rewards (confetti, badges, streaks) that raise trading volume (E127, E128); attention lists like 'top movers' as the main entry point (E125, E126); animated tickers for analysis (E080); glass panels under numbers (E067)
- **Trust signals:** exact timestamps and data source on every figure; fees and costs visible before any action (E053, E026); calm, typical finance layout (E002, E041)
- **Test with users:** Owner uses it for a week, then SUS and a task-time check on 5 key tasks (E161, E179); first-click test on new layouts (E184).
- **Evidence:** E132, E131, E022, E045, E173, E055, E057, E080, E082, E127, E128, E125, E126, E100, E101, E094, E097, E067, E053, E026, E002, E041, E161, E179, E184

### RollCall: data tables (watchlists, orders, trade history) for the expert
<a id="rollcall-trader-tables"></a>

Product: trading and finance app. Page: data table. Users: expert. Device: desktop. Confidence: **medium**.

- **Styles:** preferred plain grid tables, classical order; acceptable compact and comfortable density toggle. Tables serve find, compare, view-edit and act tasks (E154); grouping dense data helps (E132).
- **Density:** Compact rows by default with a density toggle; zebra or row separators, right-aligned numbers (E132, E154).
- **Depth:** Flat rows; sticky header and first column for orientation.
- **Motion:** Highlight a changed value briefly (under 500 ms) and settle; no continuous flashing (E088, E093).
- **Colour:** Colour only for state (gain/loss/alert) and always with a second cue (E100).
- **Type:** Monospaced or tabular numerals; readable identifier in the first column (E154).
- **Imagery:** None.
- **Avoid:** hiding columns behind hover-only menus (E114, E115); colour as the only signal; animated reordering while the user reads
- **Trust signals:** exact values and units; sort and filter state always visible
- **Test with users:** Find and compare tasks timed with the owner; five-user rounds for new layouts (E181).
- **Evidence:** E154, E132, E088, E093, E100, E114, E115, E181

### RollCall: learner's first run and onboarding
<a id="rollcall-learner-onboarding"></a>

Product: trading and finance app. Page: onboarding. Users: novice learners. Device: mobile and desktop. Confidence: **medium**.

- **Styles:** preferred friendly flat 2.0 with warm accents and real explanations; acceptable light illustration for concepts. Warm design helps learning and motivation (E134); novices need guidance that experts do not (E131).
- **Density:** Low: one idea per screen, generous spacing; progressive disclosure toward the expert view (E131, E133).
- **Depth:** Clear cards and buttons with obvious signifiers (E055).
- **Motion:** Short transitions that show where things go; nothing celebratory around trades (E127, E082).
- **Colour:** Warm, friendly accents allowed on learning content, not on trade actions (E134, E127).
- **Type:** 16-18 px body, short lines (E094, E097).
- **Imagery:** Explanatory diagrams over decorative stock (E072).
- **Avoid:** deck-of-cards tutorials before use (E152); hedonic gamification of trading (E127, E128); price-trend push notifications by default for beginners (E129)
- **Trust signals:** plain-language risk and fee disclosure up front (E053); who runs the service and how to reach them (E026)
- **Test with users:** Five learners per round, three rounds (E182); comprehension checks, not only liking; desirability words (E183).
- **Evidence:** E134, E131, E133, E055, E127, E128, E129, E082, E094, E097, E072, E152, E053, E026, E182, E183

### RollCall: lessons and explanations for learners
<a id="rollcall-learner-lessons"></a>

Product: trading education. Page: content / lesson. Users: novice learners. Device: mobile and desktop. Confidence: **medium**.

- **Styles:** preferred editorial reading layout with warm, friendly graphics; acceptable light illustration. Pleasant colours and friendly faces in learning graphics raise comprehension and transfer (E134, E135); people scan, so structure must carry meaning (E141, E142).
- **Density:** Low to medium; headings, bullets, bold key terms (E142).
- **Depth:** Flat content; interactive examples with clear affordances.
- **Motion:** Animated transitions to explain changes in a chart are fine (E082); avoid animated data playback for analysis (E080).
- **Colour:** Warm accents in graphics (E134).
- **Type:** 18 px or larger body for long text (E094); line length controlled (E097).
- **Imagery:** Diagrams and real examples; faces in learning graphics can help (E134).
- **Avoid:** walls of text (E141, E149); parallax storytelling (E090, E091)
- **Trust signals:** author and date on lessons; sources for claims
- **Test with users:** Comprehension quiz after reading; five-user think-aloud rounds (E182).
- **Evidence:** E134, E135, E141, E142, E082, E080, E094, E097, E149, E090, E091, E182

### RollCall: order entry and confirmation (any user)
<a id="rollcall-order-entry"></a>

Product: trading and finance app. Page: form / confirmation. Users: expert and learner. Device: desktop and mobile. Confidence: **high**.

- **Styles:** preferred plain, high-contrast form with one primary action; acceptable none. Form guidelines make forms faster and more satisfying (E145); costs hidden until late drive abandonment and distrust (E146, E053).
- **Density:** Only needed fields (E147); review step shows every cost.
- **Depth:** Primary button solid, secondary outlined; clear focus states.
- **Motion:** Instant feedback (under 0.1 s) on submit, then status (E085).
- **Colour:** No celebratory colour after a trade (E127).
- **Type:** Numbers large and exact.
- **Imagery:** None.
- **Avoid:** confetti or reward animations after trades (E127, E128); pre-ticked options or trick wording (E035); hidden fees (E032)
- **Trust signals:** total cost and risk shown before confirm (E053, E146); undo or cancel window where possible
- **Test with users:** Error-rate and time on scripted orders; first-click test (E184).
- **Evidence:** E145, E146, E147, E053, E085, E127, E128, E035, E032, E184

### RollCall: mobile check-ins (positions, alerts) on the go
<a id="rollcall-mobile-check"></a>

Product: trading and finance app. Page: mobile summary. Users: expert and learner. Device: phone, one-handed. Confidence: **medium**.

- **Styles:** preferred platform-native flat 2.0 / Material, bottom tab bar; acceptable expressive emphasis on the one key action (E166). Attention on the move comes in seconds-long bursts (E113); most people use one hand (E108); hidden navigation is slower (E115).
- **Density:** One glanceable summary per screen; details one tap away.
- **Depth:** Bottom sheets and cards with clear signifiers.
- **Motion:** Minimal; no motion that encourages impulsive trades.
- **Colour:** Gain/loss with sign and icon.
- **Type:** 16 px minimum; key number large.
- **Imagery:** None.
- **Avoid:** hamburger-only navigation (E114, E115); targets under about 9 mm / 44 px (E110, E111, E123); one-tap trading from notifications; phones increase lottery-like buying (E130)
- **Trust signals:** last-updated time; same numbers as desktop
- **Test with users:** One-handed task tests on the owner's phone; reach checked against thumb model (E109).
- **Evidence:** E113, E108, E115, E114, E166, E110, E111, E123, E130, E109

### Temper: developer console (workflow runs, logs, agent graphs)
<a id="temper-dev-console"></a>

Product: developer and AI tool. Page: dashboard / logs. Users: developers, experts. Device: desktop. Confidence: **medium**.

- **Styles:** preferred restrained flat 2.0, classical grid, light and dark themes; acceptable dark default if users ask; test small text in dark (E061). Expert tools favour dense, grouped information and shortcuts (E132, E133); dashboards must be designed for their genre (E143, E144).
- **Density:** High, grouped; monitoring vs analysis views separated (E143, E144).
- **Depth:** Minimal; panels and popovers only.
- **Motion:** Status changes animated briefly; streaming logs without flashing (E088, E093).
- **Colour:** Status colours plus icons; neutral base (E100).
- **Type:** Monospace for logs and ids, 13-14 px minimum in dark mode, larger in light (E061).
- **Imagery:** None decorative.
- **Avoid:** hiding key actions in menus (E114); small grey-on-black text (E061, E060); onboarding carousels (E152)
- **Trust signals:** exact run ids, timestamps, costs; clear errors with cause and next step
- **Test with users:** Five developer tasks per round, keyboard-shortcut discoverability (E133, E181).
- **Evidence:** E132, E133, E143, E144, E088, E093, E100, E061, E060, E114, E152, E181

### Temper: AI agent output, review and correction screens
<a id="temper-ai-results"></a>

Product: AI product. Page: results / review. Users: developers, owners. Device: desktop. Confidence: **medium**.

- **Styles:** preferred plain document-like layout, clear provenance blocks; acceptable none. AI guidelines: say what the AI can do and how well, make correction efficient, explain (E137); confidence displays help calibrate trust (E138).
- **Density:** Medium; result first, evidence one click away.
- **Depth:** Distinguish AI-generated content from human-verified with a consistent container style.
- **Motion:** Streaming text is fine; no fake typing delays (E087).
- **Colour:** One colour for AI uncertainty or warnings, consistent.
- **Type:** Readable body 16 px (E094).
- **Imagery:** None.
- **Avoid:** human-like persona naming on complex tasks (E051, E052); overclaiming certainty
- **Trust signals:** confidence or test status shown (E138); sources and run ids; easy edit and retry (E137)
- **Test with users:** Owner review sessions; measure correction time and trust calibration, not liking.
- **Evidence:** E137, E138, E087, E094, E051, E052

### Temper: marketing and landing pages for a developer audience
<a id="temper-marketing"></a>

Product: developer and AI tool. Page: home / landing. Users: developers evaluating tools. Device: desktop first, mobile. Confidence: **medium**.

- **Styles:** preferred typical SaaS/dev-tool layout with one expressive accent (MAYA); editorial / Swiss type-led layout; acceptable dark hero if text contrast holds. Typical-for-category pages win first impressions (E002) and novelty must sit in a familiar frame (E025); content predicts return visits (E014).
- **Density:** Low to medium above the fold; real product screenshots and code examples (E072).
- **Depth:** Light: subtle elevation for product shots.
- **Motion:** Small, purposeful; no scroll-jacking or parallax (E090, E091).
- **Colour:** Brand accent on a neutral base.
- **Type:** Large headline, 16-18 px body (E094).
- **Imagery:** Real product UI and real code, not abstract 3D or stock (E072, E073).
- **Avoid:** anti-design and chaotic layouts (E071); showcase-only polish that says nothing (E169); busy hero sections (E005)
- **Trust signals:** who builds it, docs, pricing visible (E026, E053); real examples and results
- **Test with users:** Five-second test for the message, first-click test on the main CTA, reaction cards (E183, E184).
- **Evidence:** E002, E025, E014, E072, E073, E090, E091, E094, E071, E169, E005, E026, E053, E183, E184

### Marketing and landing pages (consumer or business)
<a id="marketing-landing-general"></a>

Product: any. Page: home / landing. Users: first-time visitors. Device: mobile and desktop. Confidence: **high**.

- **Styles:** preferred minimalism with clear hierarchy; flat 2.0; editorial; acceptable expressive accents, bold colour for younger audiences (E165). Appeal and trust are judged in 50 ms (E001, E015); low complexity and typicality win (E002); design look is the most-cited credibility cue (E027).
- **Density:** Low above the fold; most attention stays in the first two screens (E118).
- **Depth:** Subtle; real buttons for CTAs (E055).
- **Motion:** Little; no parallax (E091, E092).
- **Colour:** Contrast-led; don't rely on colour psychology (E101).
- **Type:** Headline scale plus 16-18 px body.
- **Imagery:** Real people and real product; faces raise warmth (E029, E073).
- **Avoid:** stock photos of generic people (E073); dark patterns and fake urgency (E035, E039); busy hero (E005)
- **Trust signals:** contact details, real team, clear pricing (E026, E053)
- **Test with users:** Five-second and first-click tests; A/B only on real traffic after novelty fades (E163, E184).
- **Evidence:** E001, E015, E002, E027, E118, E055, E091, E092, E101, E029, E073, E035, E039, E005, E026, E053, E163, E184, E165

### SaaS and B2B apps: settings, admin and forms
<a id="saas-b2b-settings"></a>

Product: SaaS / B2B. Page: settings / forms. Users: work users. Device: desktop. Confidence: **medium**.

- **Styles:** preferred flat 2.0 / Material with standard patterns; acceptable none. Pattern-breaking expressive concepts tested worse (E167); form guidelines speed completion (E145).
- **Density:** Medium; group related settings; labels above fields (E145).
- **Depth:** Cards per section; clear signifiers (E055).
- **Motion:** Instant feedback on save (E085).
- **Colour:** Neutral; semantic colours for errors.
- **Type:** 14-16 px.
- **Imagery:** None.
- **Avoid:** unlabelled icons (E167); hidden navigation on desktop (E114)
- **Trust signals:** clear save state and undo
- **Test with users:** Task success and SUS after tasks (E179).
- **Evidence:** E167, E145, E055, E085, E114, E179

### Empty states in any app
<a id="empty-states"></a>

Product: any app. Page: empty state. Users: new and returning. Device: any. Confidence: **low**.

- **Styles:** preferred product's own style; one clear next action; acceptable light illustration. Empty states teach and lead to the key task (E153); intentional space is fine but must not look broken (E104).
- **Density:** Low, but intentional: explanation plus one action.
- **Depth:** One primary button (E055).
- **Motion:** None needed.
- **Colour:** Neutral.
- **Type:** Short headline and one sentence.
- **Imagery:** Optional small illustration; informative beats decorative (E072).
- **Avoid:** blank screens with no explanation; onboarding carousels instead (E152)
- **Trust signals:** say why it is empty and what will appear
- **Test with users:** First-click test on the empty state (E184).
- **Evidence:** E153, E104, E055, E072, E152, E184

### E-commerce product pages and checkout
<a id="ecommerce-checkout"></a>

Product: e-commerce. Page: product / checkout. Users: shoppers. Device: mobile and desktop. Confidence: **high**.

- **Styles:** preferred clean flat 2.0, product photography first; acceptable none. Abandonment comes from extra costs, trust and forced accounts (E146); checkout should have 12-14 fields (E147).
- **Density:** Product page rich in information; checkout minimal (E147).
- **Depth:** Clear buttons; trust badges near payment.
- **Motion:** Minimal; fast pages win clicks (E087).
- **Colour:** High contrast CTA.
- **Type:** 16 px+ on mobile.
- **Imagery:** Informative product photos and real people; decorative stock ignored (E072, E029).
- **Avoid:** forced account creation (E146); hidden costs and dark patterns (E031, E032); fake urgency (E035)
- **Trust signals:** total price early, guest checkout, returns policy (E146, E053)
- **Test with users:** Checkout usability rounds; Baymard-style field count (E147).
- **Evidence:** E146, E147, E087, E072, E029, E031, E032, E035, E053

### Health information and services
<a id="health-info"></a>

Product: health. Page: information / service. Users: patients, carers. Device: any. Confidence: **high**.

- **Styles:** preferred calm classical layout, clear authority signals; acceptable none. Poor design gets health sites rejected fast; credibility and authority decide trust; ads lower it (E028, E136).
- **Density:** Low to medium; plain language.
- **Depth:** Minimal.
- **Motion:** Minimal; respect reduced motion (E092, E093).
- **Colour:** High contrast; calm palette.
- **Type:** Large body for older readers (E098, E151).
- **Imagery:** Real clinicians and patients over stock (E073).
- **Avoid:** advertising on content pages (E136); low contrast and small text (E151)
- **Trust signals:** author credentials, review dates, owner of the site (E136, E026)
- **Test with users:** Include older and low-vision users (E151).
- **Evidence:** E028, E136, E092, E093, E098, E151, E073, E026

### News, editorial and long reading
<a id="news-editorial"></a>

Product: news / editorial. Page: article / index. Users: readers. Device: mobile and desktop. Confidence: **high**.

- **Styles:** preferred editorial / Swiss typographic layout; acceptable dark reading mode as an option. People read 20-28% of words and scan; formatting prevents F-pattern loss (E141, E142); multimedia did not raise credibility (E157).
- **Density:** Medium; clear headings and summaries.
- **Depth:** Flat.
- **Motion:** None in text; no autoplay (E139).
- **Colour:** Light background for long reading (E060, E061).
- **Type:** 18 px+ body (E094); controlled line length (E097).
- **Imagery:** Informative photos with captions (E072).
- **Avoid:** autoplay video (E139); parallax features (E090)
- **Trust signals:** bylines, dates, sources (E157)
- **Test with users:** Comprehension and scanning tests.
- **Evidence:** E141, E142, E157, E139, E060, E061, E094, E097, E072, E090

### Education and children's products
<a id="education-kids"></a>

Product: education / kids. Page: learning screens. Users: children and teens. Device: tablet, phone. Confidence: **medium**.

- **Styles:** preferred warm, colourful, illustrated, age-specific; acceptable expressive / maximal within clear structure. Warm design boosts learning and motivation, most for children (E134, E135); children need age-narrow design (E150); teens hate clutter (E149).
- **Density:** Low; big targets.
- **Depth:** Obvious, physical-looking buttons for young children (E066 shows skeuomorphic cues help less experienced users).
- **Motion:** Playful feedback ok, short (E088).
- **Colour:** Bright and warm (E134).
- **Type:** Large; few words for young children.
- **Imagery:** Friendly characters and faces (E134).
- **Avoid:** dense text (E149); dark patterns aimed at children (E038)
- **Trust signals:** parent-facing information separate
- **Test with users:** Test by age band (E150).
- **Evidence:** E134, E135, E150, E149, E066, E088, E038

### Government and public services
<a id="government-public"></a>

Product: government. Page: service flows. Users: everyone, incl. access needs. Device: any. Confidence: **medium**.

- **Styles:** preferred plain classical (GOV.UK-like); acceptable none. Accessibility over elegance (E155); older users need contrast and large targets (E151); forms guidelines (E145).
- **Density:** One thing per page.
- **Depth:** Flat with strong signifiers (E055).
- **Motion:** None.
- **Colour:** High contrast.
- **Type:** Large body (E094).
- **Imagery:** Rarely.
- **Avoid:** any decoration that costs contrast (E067)
- **Trust signals:** official identity, clear contact
- **Test with users:** Include access needs and older adults (E151).
- **Evidence:** E155, E151, E145, E055, E094, E067

### Luxury and fashion brands
<a id="luxury-fashion"></a>

Product: luxury / fashion. Page: brand / shop. Users: affluent shoppers. Device: mobile first. Confidence: **low**.

- **Styles:** preferred minimal, generous white space, editorial photography; acceptable expressive aesthetics for brand character (E046). White space carries prestige meaning (E159); some luxury shoppers see e-commerce tools as cheapening (E158).
- **Density:** Low, intentional space.
- **Depth:** Minimal.
- **Motion:** Slow, subtle; reduced-motion path (E093).
- **Colour:** Restrained.
- **Type:** Distinctive display type, readable body.
- **Imagery:** Large, high-quality photography.
- **Avoid:** discount-store patterns; low contrast thin type for body (E060)
- **Trust signals:** heritage, craftsmanship, service contact
- **Test with users:** Reaction cards for brand words (E183).
- **Evidence:** E159, E158, E046, E093, E060, E183

### Portfolios and agencies
<a id="portfolio-agency"></a>

Product: portfolio / agency. Page: showcase. Users: clients, designers. Device: desktop. Confidence: **low**.

- **Styles:** preferred expressive, brutalist or editorial as a statement; acceptable maximalism. Expressive aesthetics signal originality (E046); brutalism can work, anti-design rarely (E071); showcase taste differs from users' (E169).
- **Density:** Varies by concept.
- **Depth:** Free.
- **Motion:** Allowed with reduced-motion fallback (E092, E093).
- **Colour:** Free; contrast still checked.
- **Type:** Distinctive.
- **Imagery:** The work itself.
- **Avoid:** unusable navigation (E114); motion that cannot be turned off (E093)
- **Trust signals:** real clients and outcomes
- **Test with users:** Five-second test for the intended impression.
- **Evidence:** E046, E071, E169, E092, E093, E114

### Social, video and entertainment feeds
<a id="social-entertainment"></a>

Product: social / entertainment. Page: feed. Users: consumers, young adults. Device: phone. Confidence: **medium**.

- **Styles:** preferred expressive Material / bold colour for young audiences; acceptable dark theme for media. Young users prefer expressive design (E165); autoplay and recommendations reduce agency (E139).
- **Density:** Medium; media first.
- **Depth:** Layered sheets ok.
- **Motion:** Micro-interactions ok; respect reduced motion (E093).
- **Colour:** Bold.
- **Type:** Short text.
- **Imagery:** User content.
- **Avoid:** autoplay without control (E139); dark patterns (E036)
- **Trust signals:** clear controls over what is shown
- **Test with users:** Agency and satisfaction measures, not only time spent (E139).
- **Evidence:** E165, E139, E093, E036

### Any product with many older users (45+)
<a id="older-adults-any"></a>

Product: any. Page: any. Users: older adults. Device: any. Confidence: **high**.

- **Styles:** preferred clear, colourful-enough, flat 2.0 with strong signifiers; acceptable skeuomorphic cues for key controls (E066). Older users do not want plainer (E008, E009) but need large text, contrast and big targets (E151, E098).
- **Density:** Medium; no clutter.
- **Depth:** Clear affordances (E066).
- **Motion:** Minimal; vestibular issues common after 40 (E092).
- **Colour:** Colour welcome; contrast by number.
- **Type:** 16-18 px+ body (E098, E094).
- **Imagery:** Real people.
- **Avoid:** small low-contrast text (E151, E061); parallax (E092)
- **Trust signals:** clear contact and help
- **Test with users:** Recruit 45+ users; SUS after tasks (E179).
- **Evidence:** E008, E009, E151, E098, E066, E092, E094, E061, E179

### Games and game-like interfaces
<a id="games"></a>

Product: games. Page: HUD / menus. Users: players, novice to expert. Device: any. Confidence: **low**.

- **Styles:** preferred genre-typical style; expressive allowed; acceptable minimal HUD for experts. Removing the HUD raised expert immersion; the right interface depends on expertise (E156); expertise reversal (E131).
- **Density:** Adjustable by expertise.
- **Depth:** Free.
- **Motion:** Free with motion-sickness options (E092).
- **Colour:** Free; contrast for text.
- **Type:** Readable at distance.
- **Imagery:** Genre art.
- **Avoid:** fixed dense HUD for all players
- **Trust signals:** fair, visible rules
- **Test with users:** Playtests by expertise level.
- **Evidence:** E156, E131, E092

## Evidence cited

Evidence entries cited by this playbook, from the Design research base (~/design-lab/research/ui-preferences/evidence.jsonl, 184 claims). Grades: A peer-reviewed large/replicated, B peer-reviewed single study or large rigorous industry research, C industry/vendor research, D opinion and guidance. A and B quotes were re-checked against their sources on 2026-10-04.

- **E001** (A, Q1) People judge a web page's visual appeal within about 50 ms, and 50 ms ratings agree closely with 500 ms ratings: the first screen's look is judged before anything is read. Source: Lindgaard, Fernandes, Dudek & Brown 2006, Attention web designers: You have 50 milliseconds to make a good first impression!, Behaviour & Information Technology 25(2), 2006; n = 3 lab studies (participant counts not in abstract); repeated ratings of web home pages. https://doi.org/10.1080/01449290500330448
- **E002** (A, Q1) Visual complexity and prototypicality shape aesthetic ratings within the first 50 ms; pages with low visual complexity that look like a typical site of their kind are rated most appealing. Source: Tuch, Presslaber, Stöcklin, Opwis & Bargas-Avila 2012, The role of visual complexity and prototypicality regarding first impression of websites, International Journal of Human-Computer Studies 70(11), 2012; n = Study 1 n = 59 lab participants rating 119 real website screenshots (plus 267 online raters for stimulus selection); Study 2 at 17-50 ms. https://static.googleusercontent.com/media/research.google.com/en//pubs/archive/38315.pdf
- **E005** (B, Q1) High visual complexity costs the most appeal; low and medium complexity are liked about equally, so the 'inverted U' (moderate is best) is weak: the rule is avoid busy, not avoid simple. Source: Reinecke et al. 2013, Predicting users' first impressions of website aesthetics (CHI 2013), CHI 2013, 2013; n = 548 volunteers, 450 websites. https://www.eecs.harvard.edu/~kgajos/papers/2013/reinecke13aesthetics.pdf
- **E008** (A, Q2) In the 40,000-person LabintheWild data, older people preferred more visual complexity, not less; people aged 12-40 did not differ much. Source: Reinecke & Gajos 2014, Quantifying visual preferences around the world, CHI 2014, 2014; n = about 2.4 million ratings, nearly 40,000 participants. https://www.eecs.harvard.edu/~kgajos/papers/2014/reinecke14visual.pdf
- **E009** (A, Q2) Older participants found plain, colourless websites less appealing than any other age group did. Source: Reinecke & Gajos 2014, Quantifying visual preferences around the world, CHI 2014, 2014; n = nearly 40,000 participants. https://www.eecs.harvard.edu/~kgajos/papers/2014/reinecke14visual.pdf
- **E014** (A, Q1) Users say content matters most; aesthetics drives the first impression, but only content predicted intention to revisit or recommend (aesthetics added only a small effect in a replication). Source: Thielsch, Blotenberg & Jaron 2014, User evaluation of websites: From first impression to recommendation, Interacting with Computers 26(1), 2014; n = Study 1 n = 330; Study 2 n = 300 (4 websites); Study 3 n = 512 (42 websites). https://doi.org/10.1093/iwc/iwt033
- **E015** (B, Q7) Judgements of trustworthiness and usability made from a 50 ms glimpse of a home page are largely driven by its visual appeal. Source: Lindgaard, Dudek, Sen, Sumegi & Noonan 2011, An exploration of relations between visual appeal, trustworthiness and perceived usability of homepages, ACM Transactions on Computer-Human Interaction 18(1), 2011; n = 3 experiments (counts not in abstract), 50 ms exposures. https://doi.org/10.1145/1959022.1959023
- **E020** (B, Q1) Over seven weeks of real use (110 people, a coffee machine), visual aesthetics had no effect on user experience, including perceived usability: the beauty effect can fade with repeated use. Source: Sauer & Sonderegger 2022, Visual aesthetics and user experience: A multiple-session experiment, International Journal of Human-Computer Studies 165, 2022; n = 110 participants, 7 weekly sessions. https://doi.org/10.1016/j.ijhcs.2022.102837
- **E022** (B, Q1) Visual clarity (order, alignment, low complexity) explains much of why people who find an interface beautiful also find it usable. Source: Schrepp, Otten, Blum & Thomaschewski 2021, What causes the dependency between perceived aesthetics and perceived usability?, International Journal of Interactive Multimedia and Artificial Intelligence 6(6), 2021; n = two large online studies (counts not in abstract). https://doi.org/10.9781/ijimai.2020.12.005
- **E025** (B, Q8) Most advanced, yet acceptable (MAYA): typicality and novelty both raise aesthetic preference, but they suppress each other, so the best designs are new within a familiar frame. Source: Hekkert, Snelders & van Wieringen 2003, 'Most advanced, yet acceptable': typicality and novelty as joint predictors of aesthetic preference in industrial design, British Journal of Psychology 94(1), 2003; n = 3 studies of consumer products (counts not in abstract). https://doi.org/10.1348/000712603762842147
- **E026** (A, Q7) In a 1,400-person US/European study of 51 site elements, credibility rose most with a 'real-world feel' (address, people, organisation), ease of use, visible expertise, trustworthiness and tailoring; commercial pushiness and amateurism hurt it. Source: Fogg, Marshall, Laraki, Osipovich, Varma, Fang, Paul & Rangnekar 2001, What makes Web sites credible? A report on a large quantitative study, CHI 2001, 2001; n = over 1,400 participants (US and Europe), 51 site elements. https://doi.org/10.1145/365024.365037
- **E027** (A, Q7) When 2,684 people judged live sites' credibility, the site's visual 'design look' was the thing they mentioned most (46% of comments), ahead of information structure and focus. Source: Fogg, Soohoo, Danielson, Marable, Stanford & Tauber 2003, How do users evaluate the credibility of Web sites? A study with over 2,500 participants, DUX 2003 (ACM), 2003; n = 2,684 participants. https://doi.org/10.1145/997078.997097
- **E028** (B, Q3) On health sites, poor design appeal made people reject a site quickly (mistrust), while the credibility of the information and personalised content decided which sites they kept and trusted. Source: Sillence, Briggs, Fishwick & Harris 2004, Trust and mistrust of online health sites, CHI 2004, 2004; n = 15 women facing a risky health decision, 4 weekly sessions. https://doi.org/10.1145/985692.985776
- **E029** (B, Q7) Photos of people with visible faces made shopping sites feel more appealing and warmer (social presence), which in turn raised trust; the images did not raise trust directly. Source: Cyr, Head, Larios & Pan 2009, Exploring human images in website design: a multi-method approach, MIS Quarterly 33(3), 2009; n = controlled experiment in Canada, Germany and Japan (count not in abstract). https://doi.org/10.2307/20650308
- **E031** (A, Q7) Dark patterns are common: a crawl of about 11,000 shopping sites found 1,818 instances of 15 types, 183 sites using outright deception, and 22 vendors selling them as ready-made features. Source: Mathur, Acar, Friedman, Lucherini, Mayer, Chetty & Narayanan 2019, Dark patterns at scale: findings from a crawl of 11K shopping websites, Proceedings of the ACM on Human-Computer Interaction 3 (CSCW), 2019; n = about 53,000 product pages from about 11,000 shopping sites. https://doi.org/10.1145/3359183
- **E032** (A, Q7) Dark patterns work: in representative US samples, mild dark patterns more than doubled sign-ups for a dubious service and aggressive ones nearly quadrupled them. Source: Luguri & Strahilevitz 2021, Shining a light on dark patterns, Journal of Legal Analysis 13(1), 2021; n = two large-scale experiments with representative samples of US consumers. https://doi.org/10.1093/jla/laaa006
- **E033** (A, Q7) Aggressive dark patterns caused a strong backlash in mood toward the company; mild ones did not, which is why mild manipulation persists unnoticed. Source: Luguri & Strahilevitz 2021, Shining a light on dark patterns, Journal of Legal Analysis 13(1), 2021; n = representative US samples, two experiments. https://doi.org/10.1093/jla/laaa006
- **E035** (A, Q7) The most effective manipulations were hidden information, trick questions and obstruction; 'act now' urgency messages did not increase purchases of a costly service. Source: Luguri & Strahilevitz 2021, Shining a light on dark patterns, Journal of Legal Analysis 13(1), 2021; n = representative US samples. https://doi.org/10.1093/jla/laaa006
- **E036** (B, Q7) 95% of 240 popular mobile apps contained at least one dark pattern (seven types on average), and most of 589 users did not recognise them unless told what to look for. Source: Di Geronimo, Braz, Fregnan, Palomba & Bacchelli 2020, UI dark patterns and where to find them: a study on mobile applications and user perception, CHI 2020, 2020; n = 240 apps; online experiment with 589 users. https://doi.org/10.1145/3313831.3376600
- **E037** (B, Q7) Consent pop-up design changes choices a lot: removing 'reject' from the first layer raised consent by 22-23 points; only 11.8% of popular UK consent pop-ups met minimal legal requirements. Source: Nouwens, Liccardi, Veale, Karger & Kagal 2020, Dark patterns after the GDPR: scraping consent pop-ups and demonstrating their influence, CHI 2020, 2020; n = 680 consent designs scraped from top 10,000 UK sites; field experiment with 40 participants. https://doi.org/10.1145/3313831.3376321
- **E038** (B, Q7) People know dark patterns exist, but knowing does not help them resist; younger people spot them more often yet are unsure of the harm. Source: Bongard-Blanchy, Rossi, Rivas, Doublet, Koenig & Lenzini 2021, 'I am definitely manipulated, even when I am aware of it. It's ridiculous!' Dark patterns from the end-user perspective, DIS 2021 (ACM), 2021; n = 406 survey respondents. https://doi.org/10.1145/3461778.3462086
- **E039** (B, Q7) A shop built with five dark patterns annoyed shoppers more, and annoyance went with lower trust in the brand. Source: Voigt, Schlögl & Groth 2021, Dark patterns in online shopping: of sneaky tricks, perceived annoyance and respective brand trust, HCI International 2021 (LNCS), 2021; n = n = 204. https://doi.org/10.1007/978-3-030-77750-0_10
- **E041** (B, Q3) For online banking, visual design factors (title, menu, main image, colour) can be deliberately tuned to raise felt trustworthiness. Source: Kim & Moon 1998, Designing towards emotional usability in customer interfaces: trustworthiness of cyber-banking system interfaces, Interacting with Computers 10(1), 1998; n = four studies with Korean bank staff, developers and customers (late teens to early forties). https://doi.org/10.1016/s0953-5438(97)00037-4
- **E045** (B, Q1) People judge website looks on two separate dimensions: classical aesthetics (orderly, clear, clean, symmetrical, close to usability rules) and expressive aesthetics (creative, original, fascinating, special effects, convention-breaking). Source: Lavie & Tractinsky 2004, Assessing dimensions of perceived visual aesthetics of web sites, International Journal of Human-Computer Studies 60(3), 2004; n = four studies (Study 1 n = 125 engineering students; confirmatory sample n = 192 plus hold-out). https://www.ise.bgu.ac.il/faculty/noam/papers/04_tl_nt_ijhcs.pdf
- **E046** (B, Q4) Expressive aesthetics is the designer's creativity and originality, including the ability to break conventions; it is distinguishable from classical clarity and is what gives a design character. Source: Lavie & Tractinsky 2004, Assessing dimensions of perceived visual aesthetics of web sites, International Journal of Human-Computer Studies 60(3), 2004; n = four studies. https://www.ise.bgu.ac.il/faculty/noam/papers/04_tl_nt_ijhcs.pdf
- **E051** (B, Q3) Investors relied more on an unnamed robo-advisor than a named one; giving an algorithm a human name backfired when the task looked complex. Source: Hodge, Mendoza & Sinha 2021, The effect of humanizing robo-advisors on investor judgments, Contemporary Accounting Research 38(1), 2021; n = two experiments (counts not in abstract). https://doi.org/10.1111/1911-3846.12641
- **E052** (B, Q3) A robo-advisor reduced investors' disposition effect, but adding human-like social design (a name, chat language) made decisions worse because people asked it for advice less. Source: Back, Morana & Spann 2023, When do robo-advisors make us better investors? The impact of social design elements on investor behavior, Journal of Behavioral and Experimental Economics 103, 2023; n = two consequential induced-value experiments (counts not in abstract). https://doi.org/10.1016/j.socec.2023.101984
- **E053** (C, Q7) NN/g's Singapore study found the same four trust factors across Western and Asian users as Nielsen listed in 1999: design quality, up-front disclosure (prices, fees, policies before sign-up), comprehensive current content, and links to the rest of the web. Source: Harley 2016, Trustworthiness in web design: 4 credibility factors (Nielsen Norman Group), Nielsen Norman Group article, 2016; n = qualitative usability study in Singapore (count not stated). https://www.nngroup.com/articles/trustworthy-design/
- **E055** (B, Q4) In a 71-person eyetracking experiment on 9 page pairs, pages whose clickable elements had weak (flat) signifiers took 22% longer to scan than the same pages with strong signifiers. Source: Moran 2017, Flat UI elements attract less attention and cause uncertainty (Nielsen Norman Group), Nielsen Norman Group study report, 2017; n = 71 general web users, 9 page pairs, between-subjects. https://www.nngroup.com/articles/flat-ui-less-attention-cause-uncertainty/
- **E056** (B, Q4) The same eyetracking study found 25% more fixations on weak-signifier pages, meaning more searching before people found what to click. Source: Moran 2017, Flat UI elements attract less attention and cause uncertainty (Nielsen Norman Group), Nielsen Norman Group study report, 2017; n = 71 general web users. https://www.nngroup.com/articles/flat-ui-less-attention-cause-uncertainty/
- **E057** (D, Q4) 'Flat 2.0' (mostly flat with subtle shadows, highlights and layers) is recommended over pure flat because it restores depth cues that tell people what can be clicked. Source: Moran 2015, Flat design: its origins, its problems, and why flat 2.0 is better for users (Nielsen Norman Group), Nielsen Norman Group article, 2015; n = n/a. https://www.nngroup.com/articles/flat-design/
- **E059** (C, Q4) Review of the research: people with normal vision read and see detail better in light mode; some people with cataracts and similar conditions may do better in dark mode. Source: Budiu 2020, Dark mode vs. light mode: which is better? (Nielsen Norman Group), Nielsen Norman Group article (research review), 2020; n = review of lab studies. https://www.nngroup.com/articles/dark-mode/
- **E060** (B, Q4) Dark text on a light background beat light-on-dark for both younger (18-33) and older (60-85) adults in acuity and proofreading; the authors recommend positive polarity for all ages. Source: Piepenbrock, Mayr, Mund & Buchner 2013, Positive display polarity is advantageous for both younger and older adults, Ergonomics 56(7), 2013; n = younger (18-33) and older (60-85) adults (counts not in abstract). https://doi.org/10.1080/00140139.2013.790485
- **E061** (B, Q5) The light-mode reading advantage grows as text gets smaller, so small text on dark backgrounds is the worst case. Source: Piepenbrock, Mayr & Buchner 2014, Positive display polarity is particularly advantageous for small character sizes, Human Factors 56(5), 2014; n = lab sample (count not in abstract), 4 character sizes 8-14 pt. https://doi.org/10.1177/0018720813515509
- **E063** (B, Q4) At night with a dim screen, reading in dark mode reduced measured eye fatigue (blink rate, pupil), yet people still preferred light mode out of habit; everyone preferred higher text contrast. Source: Xie, Song, Liu, Wang & Yu 2021, Study on the effects of display color mode and luminance contrast on visual fatigue, IEEE Access 9, 2021; n = lab sample (count not in abstract), 2 x 6 design. https://doi.org/10.1109/access.2021.3061770
- **E066** (B, Q2) Older adults (15, interviewed and tested on banking prototypes) preferred a flat online-banking design to a skeuomorphic one, although the skeuomorphic one helped them more than it helped younger adults. Source: Ellis & Marshall 2019, Can skeuomorphic design provide a better online banking user experience for older adults?, Multimodal Technologies and Interaction 3(3), 2019; n = 15 older adults plus 17 younger adults (20-25) as validation. https://doi.org/10.3390/mti3030063
- **E067** (D, Q4) Apple's Liquid Glass (iOS 26) was criticised by NN/g for obscuring content: translucent controls over busy backgrounds lower text contrast, and floating controls crowd and shrink tap targets. Source: Budiu 2025, Liquid Glass is cracked, and usability suffers in iOS 26 (Nielsen Norman Group), Nielsen Norman Group article, 2025; n = n/a (expert review). https://www.nngroup.com/articles/liquid-glass/
- **E068** (D, Q5) Text placed over images or translucent layers is a long-known contrast problem; Liquid Glass makes it routine. Source: Budiu 2025, Liquid Glass is cracked, and usability suffers in iOS 26 (Nielsen Norman Group), Nielsen Norman Group article, 2025; n = n/a. https://www.nngroup.com/articles/liquid-glass/
- **E071** (D, Q4) Brutalism (raw, deliberately plain) can work in visual design, but anti-design (deliberately chaotic, convention-breaking) should be avoided for most products. Source: Moran 2017, Brutalism and antidesign (Nielsen Norman Group), Nielsen Norman Group article, 2017; n = n/a. https://www.nngroup.com/articles/brutalism-antidesign/
- **E072** (B, Q4) Eyetracking shows people study photos that carry information (products, real people) and ignore decorative feel-good images. Source: Nielsen 2010 (reviewed 2026), Photos as web content (Nielsen Norman Group), Nielsen Norman Group article (eyetracking studies), 2010; n = NN/g eyetracking studies (counts not stated). https://www.nngroup.com/articles/photos-as-web-content/
- **E073** (B, Q7) Users ignore stock photos of generic people but look at photos of real people who actually work at the company. Source: Nielsen 2010 (reviewed 2026), Photos as web content (Nielsen Norman Group), Nielsen Norman Group article (eyetracking studies), 2010; n = NN/g eyetracking studies. https://www.nngroup.com/articles/photos-as-web-content/
- **E074** (B, Q5) Progress bars with animated ribbing that moves backwards and slows down made the same wait feel 11% shorter than a plain solid bar. Source: Harrison, Yeo & Hudson 2010, Faster progress bars: manipulating perceived duration with visual augmentations, CHI 2010, 2010; n = lab participants (count not in abstract), series of paired comparisons. https://doi.org/10.1145/1753326.1753556
- **E077** (B, Q5) In animated transitions on a phone, showing the next screen's content earlier mattered more for feeling fast than any other transition variable tested. Source: Huhtala, Sarjanoja, Mäntyjärvi, Isomursu & Häkkilä 2010, Animated UI transitions and perception of time: a user study on animated effects on a mobile screen, CHI 2010, 2010; n = user study (count not in abstract). https://doi.org/10.1145/1753326.1753527
- **E078** (B, Q5) Across several experiments, moderate-speed wait animations made waits feel shortest, compared with no animation, slow or fast animation (a U-shaped, not linear, effect). Source: Ding & Kyung 2025, Optimizing animation speed: convex effects on perceived waiting time and digital customer experience, Journal of Consumer Research, 2025; n = multiple experiments (1a-6) incl. field tests (counts not in abstract). https://doi.org/10.1093/jcr/ucaf037
- **E080** (B, Q5) For analysing trends, animated charts were the slowest and least accurate; static traces and small multiples were significantly faster, and small multiples most accurate. Source: Robertson, Fernandez, Fisher, Lee & Stasko 2008, Effectiveness of animation in trend visualization, IEEE Transactions on Visualization and Computer Graphics 14(6), 2008; n = lab study (count not in abstract). https://doi.org/10.1109/TVCG.2008.125
- **E082** (B, Q5) Well-designed animated transitions between chart states (e.g. bar to pie, re-sorting) significantly improved people's ability to follow what changed. Source: Heer & Robertson 2007, Animated transitions in statistical data graphics, IEEE Transactions on Visualization and Computer Graphics 13(6), 2007; n = two controlled experiments (counts not in abstract). https://doi.org/10.1109/TVCG.2007.70539
- **E084** (B, Q5) Feedback while waiting makes web users willing to wait longer; without it, the tolerable wait for retrieving information is about 2 seconds. Source: Nah 2004, A study on tolerable waiting time: how long are Web users willing to wait?, Behaviour & Information Technology 23(3), 2004; n = experimental study (count not in abstract). https://doi.org/10.1080/01449290410001669914
- **E085** (D, Q5) Classic response-time limits: about 0.1 s feels instant, about 1 s keeps the flow of thought, about 10 s is the limit of attention. Source: Nielsen 1993, Response times: the 3 important limits (Nielsen Norman Group, from Usability Engineering), Usability Engineering (book), NN/g article, 1993; n = n/a (synthesis of Miller 1968, Card et al. 1991). https://www.nngroup.com/articles/response-times-3-important-limits/
- **E086** (D, Q5) Use a progress indicator for anything over about 1 second; looping spinners only for short waits, percent-done bars for long ones. Source: Sherwin 2014, Progress indicators make a slow system less insufferable (Nielsen Norman Group), Nielsen Norman Group article, 2014; n = n/a. https://www.nngroup.com/articles/progress-indicators/
- **E087** (A, Q5) In a large Yahoo search log, of two identical result pages people clicked more on the one served faster; in a lab study, users of a fast system noticed added delays more than users of a slow one. Source: Arapakis, Bai & Cambazoglu 2014, Impact of response latency on user behavior in web search, SIGIR 2014, 2014; n = controlled user study plus large-scale Yahoo query log. https://doi.org/10.1145/2600428.2609627
- **E088** (D, Q5) Most UI animations should last 100-500 ms: about 100 ms for simple feedback (toggles, checkboxes), 200-300 ms for larger moves; at 500 ms they start to feel like a drag. Source: Laubheimer 2020, Executing UX animations: duration and motion characteristics (Nielsen Norman Group), Nielsen Norman Group article, 2020; n = n/a. https://www.nngroup.com/articles/animation-duration/
- **E089** (D, Q5) Ease-out curves (fast start, gentle stop) make UI motion feel responsive; linear motion looks unnatural. Source: Laubheimer 2020, Executing UX animations: duration and motion characteristics (Nielsen Norman Group), Nielsen Norman Group article, 2020; n = n/a. https://www.nngroup.com/articles/animation-duration/
- **E090** (B, Q5) With 86 students, a parallax-scrolling site was rated more fun than the same site without parallax, but not better on usability, satisfaction or visual appeal. Source: Frederick, Mohler, Vorvoreanu & Glotzbach 2015, The effects of parallax scrolling on user experience in web design, Journal of Usability Studies 10(2), 2015; n = 86 (43 per group). https://uxpajournal.org/
- **E091** (B, Q5) Two of the 43 people using the parallax site got motion sickness and had significant usability problems. Source: Frederick, Mohler, Vorvoreanu & Glotzbach 2015, The effects of parallax scrolling on user experience in web design, Journal of Usability Studies 10(2), 2015; n = 86 (43 saw parallax). https://uxpajournal.org/
- **E092** (A, Q5) In a US national health survey (n=5,086), 35.4% of adults aged 40+ had measurable vestibular (balance) dysfunction, rising with age. Source: Agrawal, Carey, Della Santina, Schubert & Minor 2009, Disorders of balance and vestibular function in US adults (NHANES 2001-2004), Archives of Internal Medicine 169(10), 2009; n = 5,086 US adults aged 40+. https://doi.org/10.1001/archinternmed.2009.66
- **E093** (C, Q5) WCAG 2.2 success criterion 2.3.3 (AAA): motion triggered by interaction must be possible to turn off unless it is essential. Source: W3C 2023, Understanding SC 2.3.3 Animation from Interactions (WCAG 2.2), W3C Recommendation (WCAG 2.2) understanding document, 2023; n = n/a. https://www.w3.org/WAI/WCAG22/Understanding/animation-from-interactions.html
- **E094** (B, Q5) In an eye-tracking study of 104 people reading Wikipedia, readability rose with font size and comprehension was better at 18 and 26 pt; the authors recommend 18 pt or larger for text-heavy sites. Source: Rello, Pielot & Marcos 2016, Make it big! The effect of font size and line spacing on online readability, CHI 2016, 2016; n = 104. https://doi.org/10.1145/2858036.2858204
- **E097** (A, Q5) A review of on-screen text layout research found the number of characters per line is the key variable for line length. Source: Dyson 2004, How physical text layout affects reading from screen, Behaviour & Information Technology 23(6), 2004; n = review of empirical studies. https://doi.org/10.1080/01449290410001715714
- **E098** (B, Q2) Older adults found 14-point fonts more legible than 12-point and preferred them. Source: Bernard, Liao & Mills 2001, The effects of font type and size on the legibility and reading time of online text by older adults, CHI 2001 Extended Abstracts, 2001; n = older adults (count not in abstract). https://doi.org/10.1145/634067.634173
- **E100** (B, Q5) Text-background colour pairs with higher contrast ratio were generally more readable. Source: Hall & Hanna 2004, The impact of web page text-background colour combinations on readability, retention, aesthetics and behavioural intention, Behaviour & Information Technology 23(3), 2004; n = 136. https://doi.org/10.1080/01449290410001669932
- **E101** (A, Q5) A major review of colour psychology warns that the field is young and that strong recommendations for practice are not yet warranted. Source: Elliot & Maier 2014, Color psychology: effects of perceiving color on psychological functioning in humans, Annual Review of Psychology 65, 2014; n = review. https://doi.org/10.1146/annurev-psych-010213-115035
- **E102** (B, Q5) People like colours associated with things they like (blues with sky and clean water) and dislike colours tied to unpleasant things (browns with rot): colour preference is learned association. Source: Palmer & Schloss 2010, An ecological valence theory of human color preference, PNAS 107(19), 2010; n = lab ratings (count not in abstract). https://doi.org/10.1073/pnas.0906172107
- **E104** (B, Q5) On 20 news pages, white-space preferences differed by age, education and other traits; nobody preferred very high (90%) or very low (50%) white-space ratios. Source: Ko & Liu 2019, Old and young users' white space preferences for online news web pages, IEEE Access 7, 2019; n = survey sample (count not in abstract), 20 pages from 10 Chinese and English news sites. https://doi.org/10.1109/access.2019.2913407
- **E108** (C, Q6) In 1,333 street observations of phone use (780 touching the screen), 49% held the phone in one hand, 36% cradled it in one hand and tapped with the other, and 15% used two hands. Source: Hoober 2013, How do users really hold mobile devices? (UXmatters), UXmatters (practitioner field study), 2013; n = 1,333 observations, 780 interacting with the screen. https://www.uxmatters.com/mt/archives/2013/02/how-do-users-really-hold-mobile-devices.php
- **E109** (B, Q6) The screen area a gripping thumb can reach depends on screen size, hand size and where the index finger rests behind the phone, and can be predicted with a model (fit on 20 people). Source: Bergström-Lehtovirta & Oulasvirta 2014, Modeling the functional area of the thumb on mobile touchscreen surfaces, CHI 2014, 2014; n = 20. https://doi.org/10.1145/2556288.2557354
- **E110** (B, Q6) For one-handed thumb use, targets of about 9.2 mm (single taps) and 9.6 mm (tap sequences) were large enough without hurting speed, errors or preference. Source: Parhi, Karlson & Bederson 2006, Target size study for one-handed thumb use on small touchscreen devices, MobileHCI 2006, 2006; n = two-phase lab study (count not in abstract). https://doi.org/10.1145/1152215.1152260
- **E111** (D, Q6) NN/g's rule from this research: interactive elements should be at least 1 cm x 1 cm, with enough spacing, to avoid slow taps and fat-finger errors. Source: Harley 2019, Touch targets on touchscreens (Nielsen Norman Group), Nielsen Norman Group article, 2019; n = n/a. https://www.nngroup.com/articles/touch-target-size/
- **E113** (B, Q6) On the move, people's attention to a phone breaks into bursts of a few seconds, versus spans of over 16 seconds in the lab. Source: Oulasvirta, Tamminen, Roto & Kuorelahti 2005, Interaction in 4-second bursts: the fragmented nature of attentional resources in mobile HCI, CHI 2005, 2005; n = semi-naturalistic field study (count not in abstract), nine urban situations. https://doi.org/10.1145/1054972.1055101
- **E114** (B, Q6) In a quantitative study (179 users, 6 sites), people on desktop used hidden (hamburger) navigation in only 27% of cases versus 48-50% for visible or combined navigation. Source: Pernice & Budiu 2016, Hamburger menus and hidden navigation hurt UX metrics (Nielsen Norman Group), Nielsen Norman Group study report, 2016; n = 179 users, 6 websites, desktop and phone. https://www.nngroup.com/articles/hamburger-menus/
- **E115** (B, Q6) Hidden navigation also made tasks slower: at least 39% slower on desktop and 15% slower on phones (versus combined navigation). Source: Pernice & Budiu 2016, Hamburger menus and hidden navigation hurt UX metrics (Nielsen Norman Group), Nielsen Norman Group study report, 2016; n = 179 users. https://www.nngroup.com/articles/hamburger-menus/
- **E118** (B, Q3) In NN/g eyetracking (120 people, 130,000+ fixations on long pages), 57% of viewing time was above the fold and 74% within the first two screenfuls. Source: Fessenden 2018, Scrolling and attention (Nielsen Norman Group), Nielsen Norman Group study report, 2018; n = 120 participants, 130,000+ fixations. https://www.nngroup.com/articles/scrolling-and-attention/
- **E123** (C, Q6) WCAG 2.2 success criterion 2.5.8 (AA) requires pointer targets of at least 24 by 24 CSS pixels, or enough spacing around smaller ones. Source: W3C 2023, Understanding SC 2.5.8 Target Size (Minimum) (WCAG 2.2), W3C Recommendation (WCAG 2.2) understanding document, 2023; n = n/a. https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html
- **E125** (A, Q3) Robinhood users trade more on attention (top movers, hot stocks) than other retail investors; their intense buying predicts negative returns of -4.7% over 20 days for the most-bought stocks. Source: Barber, Huang, Odean & Schwarz 2022, Attention-induced trading and returns: evidence from Robinhood users, Journal of Finance, 2022; n = Robinhood holdings and trading data (large sample), with Robinhood outages as natural experiments. https://doi.org/10.1111/jofi.13183
- **E126** (A, Q3) The same paper attributes part of Robinhood users' attention-driven trading to the app's own features, not only to the users it attracts. Source: Barber, Huang, Odean & Schwarz 2022, Attention-induced trading and returns: evidence from Robinhood users, Journal of Finance, 2022; n = Robinhood account data. https://doi.org/10.1111/jofi.13183
- **E127** (B, Q3) In a randomised online experiment, hedonic gamification (confetti, badges) raised trading volume by 5.17%, and people with lower financial literacy preferred the gamified platforms. Source: Chapkovski, Khapko & Zoican 2024, Trading gamification and investor behavior, Management Science, 2024; n = randomized online experiment (count not in abstract). https://doi.org/10.1287/mnsc.2022.02650
- **E128** (B, Q3) Participants with lower financial literacy chose platforms with hedonic gamification such as confetti and achievement badges. Source: Chapkovski, Khapko & Zoican 2024, Trading gamification and investor behavior, Management Science, 2024; n = randomized online experiment. https://doi.org/10.1287/mnsc.2022.02650
- **E129** (B, Q3) Price-trend notifications helped investors with accurate beliefs learn but reinforced the mistakes of those with wrong beliefs. Source: Chapkovski, Khapko & Zoican 2024, Trading gamification and investor behavior, Management Science, 2024; n = randomized online experiment. https://doi.org/10.1287/mnsc.2022.02650
- **E130** (C, Q6) Comparing trades by the same investors across devices, smartphones increased buying of riskier, lottery-like assets and chasing past returns; the effect was not caused by screen size or nudges and did not fade. Source: Kalda, Loos, Previtero & Hackethal 2021, Smart(phone) investing? A within investor-time analysis of new technologies and trading behavior, NBER Working Paper 28363, 2021; n = transaction-level data from two German banks. https://doi.org/10.3386/w28363
- **E131** (A, Q2) Instructional techniques that help inexperienced learners can lose their benefit and even hurt more experienced ones (the expertise reversal effect). Source: Kalyuga, Ayres, Chandler & Sweller 2003, The expertise reversal effect, Educational Psychologist, 2003; n = review of many experiments. https://doi.org/10.1207/S15326985EP3801_4
- **E132** (B, Q2) Reformatting dense spacecraft displays gave large speed and accuracy gains for non-experts, while experts got fewer errors but no speed change. Source: Burns, Warren & Rudisill 1986, Formatting space-related displays to optimize expert and nonexpert user performance, CHI 1986 (ACM SIGCHI Bulletin), 1986; n = experts and non-experts (count not in abstract). https://doi.org/10.1145/22339.22383
- **E133** (A, Q2) Expert shortcuts are often left unused: people tend to stay with slower methods they already know, so interfaces must actively support the novice-to-expert transition. Source: Cockburn, Gutwin, Scarr & Malacria 2014, Supporting novice to expert transitions in user interfaces, ACM Computing Surveys, 2014; n = survey of the research literature. https://doi.org/10.1145/2659796
- **E134** (A, Q3) A meta-analysis of 33 samples (2,924 learners) found that friendly faces and pleasant colours in learning graphics improved retention, comprehension and transfer (d about 0.3-0.4). Source: Brom, Stárková & D'Mello 2018, How effective is emotional design? A meta-analysis on facial anthropomorphisms and pleasant colors during multimedia learning, Educational Research Review, 2018; n = 33 independent samples, N = 2,924. https://doi.org/10.1016/j.edurev.2018.09.004
- **E135** (A, Q3) In that meta-analysis the warm design raised intrinsic motivation more for children than for older learners, and only weakly raised liking. Source: Brom, Stárková & D'Mello 2018, How effective is emotional design?, Educational Research Review, 2018; n = 33 samples, N = 2,924. https://doi.org/10.1016/j.edurev.2018.09.004
- **E136** (A, Q3) A systematic review of 73 studies on health websites found consensus that design, clear layout, interactive features and the owner's authority raise trust, while advertising lowers it. Source: Sbaffi & Rowley 2017, Trust and credibility in web-based health information: a review and agenda for future research, Journal of Medical Internet Research, 2017; n = 73 studies (from 3,827 records). https://doi.org/10.2196/jmir.7579
- **E137** (B, Q3) 18 guidelines for AI products (make clear what the AI can do and how well, support efficient correction, explain why) were validated with 49 designers testing 20 popular AI products. Source: Amershi et al. 2019, Guidelines for human-AI interaction, CHI 2019, 2019; n = 49 design practitioners, 20 AI products. https://doi.org/10.1145/3290605.3300233
- **E138** (B, Q3) Showing a confidence score helped people calibrate their trust in an AI model, but local explanations were problematic and calibration alone did not improve joint decisions. Source: Zhang, Liao & Bellamy 2020, Effect of confidence and explanation on accuracy and trust calibration in AI-assisted decision making, FAT* 2020 (ACM), 2020; n = two human experiments (counts not in abstract). https://doi.org/10.1145/3351095.3372852
- **E139** (B, Q3) In a survey of 120 YouTube users, autoplay and recommendations mainly reduced people's sense of agency, while playlists and search supported it. Source: Lukoff et al. 2021, How the design of YouTube influences user sense of agency, CHI 2021, 2021; n = 120 survey respondents plus 13 co-design sessions. https://doi.org/10.1145/3411764.3445467
- **E141** (B, Q3) From the same data, NN/g estimates people read at most 28% of the words on an average web page, more likely about 20%. Source: Nielsen 2008, How little do users read? (Nielsen Norman Group), Nielsen Norman Group article (analysis of Weinreich et al. data), 2008; n = 25 users' logged page views. https://www.nngroup.com/articles/how-little-do-users-read/
- **E142** (B, Q3) Eyetracking shows people often scan text-heavy pages in an F shape, which is bad for users and businesses; good formatting (headings, bullets, bolded keywords) prevents it. Source: Pernice 2017 (reviewed 2026), F-shaped pattern of reading on the web: misunderstood, but still relevant (Nielsen Norman Group), Nielsen Norman Group study report, 2017; n = NN/g eyetracking studies (e.g. heatmap of 45+ people). https://www.nngroup.com/articles/f-shaped-pattern-reading-web-content/
- **E143** (B, Q3) A systematic review of 144 dashboards found eight groups of design patterns and distinct genres (narrative, analytical, embedded), each with trade-offs in screen space, interaction and information shown. Source: Bach et al. 2022, Dashboard design patterns, IEEE Transactions on Visualization and Computer Graphics (VIS 2022), 2022; n = 144 dashboards; workshop with 23 participants. https://doi.org/10.1109/tvcg.2022.3209448
- **E144** (B, Q3) Dashboards differ widely in goals, interaction and practice, so 'dashboard' is not one design problem; the authors build a design space of dashboard types. Source: Sarikaya, Correll, Bartram, Tory & Fisher 2019, What do we talk about when we talk about dashboards?, IEEE Transactions on Visualization and Computer Graphics (VIS 2018), 2019; n = analysis of dashboard examples and literature. https://doi.org/10.1109/TVCG.2018.2864903
- **E145** (B, Q3) Applying 20 form-design guidelines to real company forms led to faster completion, fewer submission attempts, fewer eye movements and higher satisfaction (eyetracking experiment, N = 65). Source: Seckler, Heinz, Bargas-Avila, Opwis & Tuch 2014, Designing usable web forms: empirical evaluation of web form improvement guidelines, CHI 2014, 2014; n = 65. https://doi.org/10.1145/2556288.2557265
- **E146** (B, Q3) Baymard's survey of US shoppers: after excluding 'just browsing', 40% abandoned over extra costs, 19% over not trusting the site with their card, 18% over forced account creation and 17% over a long or complicated checkout. Source: Baymard Institute 2025-26, Cart abandonment rate statistics, Baymard Institute research (quantitative survey and benchmark), 2026; n = quantitative survey of US online shoppers (n on Baymard's methodology page) plus 50 abandonment studies. https://baymard.com/lists/cart-abandonment-rate
- **E147** (B, Q3) Baymard's testing shows an ideal checkout needs only 12-14 form elements, yet the average US checkout shows 23.48 by default. Source: Baymard Institute 2025-26, Cart abandonment rate statistics, Baymard Institute research, 2026; n = large-scale checkout usability testing plus benchmark database. https://baymard.com/lists/cart-abandonment-rate
- **E149** (B, Q2) Teens dislike tiny font sizes as much as adults do, and nothing puts them off more than a cluttered screen full of text. Source: Kendrick & Nielsen 2019, Teenager's UX: designing for teens (Nielsen Norman Group), Nielsen Norman Group study report, 2019; n = 100 teens. https://www.nngroup.com/articles/usability-of-websites-for-teenagers/
- **E150** (B, Q2) NN/g's research with children aged 3-12 found they need a different design style and content targeted narrowly by age, although much of what helps adults helps children too. Source: Sherwin & Nielsen 2019, Children's UX: usability issues in designing for young people (Nielsen Norman Group), Nielsen Norman Group study report, 2019; n = three study rounds with children 3-12 in the US and other countries. https://www.nngroup.com/articles/childrens-websites-usability-issues/
- **E151** (B, Q2) In NN/g testing, people's ability to use websites declined by about 0.8% a year between ages 25 and 60; older users are hurt by small text, low contrast and tiny targets. Source: Kane 2019, Usability for older adults: challenges and changes (Nielsen Norman Group), Nielsen Norman Group study report, 2019; n = 123 participants aged 65+ over three rounds (5 countries). https://www.nngroup.com/articles/usability-for-senior-citizens/
- **E152** (C, Q3) NN/g recommends skipping app onboarding where possible: its research on deck-of-cards tutorials found they did not improve task performance. Source: Kendrick 2020, Mobile-app onboarding: an analysis of components and techniques (Nielsen Norman Group), Nielsen Norman Group article, 2020; n = n/a (cites NN/g tutorial study). https://www.nngroup.com/articles/mobile-app-onboarding/
- **E153** (D, Q3) Empty states are a chance to show system status, teach the product and give a direct path to the key task. Source: Kaplan 2021, Designing empty states in complex applications: 3 guidelines (Nielsen Norman Group), Nielsen Norman Group article, 2021; n = n/a. https://www.nngroup.com/articles/empty-state-interface-design/
- **E154** (D, Q3) Data tables should support four tasks: find records, compare data, view or edit one row, and act on records; the first column should be a readable identifier and columns ordered by importance. Source: Laubheimer 2022, Data tables: four major user tasks (Nielsen Norman Group), Nielsen Norman Group article, 2022; n = n/a. https://www.nngroup.com/articles/data-tables/
- **E155** (D, Q3) GOV.UK's design principles put accessibility above elegance: 'If we have to sacrifice elegance - so be it.' Source: Government Digital Service 2012 (updated 2019), Government design principles (GOV.UK), GOV.UK guidance, 2012; n = n/a. https://www.gov.uk/guidance/government-design-principles
- **E156** (B, Q2) Removing the heads-up display in a shooter game increased immersion for expert players through more cognitive involvement and sense of control; the right interface depends on expertise. Source: Iacovides, Cox, Kennedy, Cairns & Jennett 2015, Removing the HUD: the impact of non-diegetic game elements and expertise on player involvement, CHI PLAY 2015, 2015; n = lab study with two game versions (count not in abstract). https://doi.org/10.1145/2793107.2793120
- **E157** (B, Q3) For online news, traditional credibility factors still matter and hyperlinking mattered for index-type sites, but multimedia and interactivity did not change credibility. Source: Chung, Nam & Stefanone 2012, Exploring online news credibility: the relative influence of traditional and technological factors, Journal of Computer-Mediated Communication, 2012; n = survey of news readers (count not in abstract). https://doi.org/10.1111/j.1083-6101.2011.01565.x
- **E158** (B, Q3) Luxury consumers are split on brand websites: some see e-commerce and interactive tools as a loss of prestige or exclusivity, and attitudes follow whether they buy luxury for themselves or to show others (42 interviews). Source: Veg-Sala & Geerts 2023, Consumers' expectations toward luxury brands' websites, Qualitative Market Research, 2023; n = 42 semi-structured interviews. https://doi.org/10.1108/qmr-03-2023-0032
- **E159** (B, Q5) White space in advertising carries a historically built meaning that both ad makers (creative directors) and ordinary consumers share and understand. Source: Pracejus, Olsen & O'Guinn 2006, How nothing became something: white space, rhetoric, history, and meaning, Journal of Consumer Research, 2006; n = historical analysis plus interviews with creative directors and consumers. https://doi.org/10.1086/504138
- **E160** (B, Q8) Over two weeks of real use (60 mobile-phone users), the boost that an attractive design gave to perceived usability faded as people used it more. Source: Sonderegger, Zbinden, Uebelbacher & Sauer 2012, The influence of product aesthetics and usability over the course of time: a longitudinal field experiment, Ergonomics, 2012; n = 60 mobile phone users, 3 sessions over 2 weeks. https://doi.org/10.1080/00140139.2012.672658
- **E161** (B, Q10) Because aesthetics sways usability ratings in one-off tests, the authors advise multi-session (longitudinal) usability tests. Source: Sonderegger, Zbinden, Uebelbacher & Sauer 2012, The influence of product aesthetics and usability over the course of time, Ergonomics, 2012; n = 60. https://doi.org/10.1080/00140139.2012.672658
- **E163** (B, Q8) The novelty effect (higher use right after launch) appears both when a new system arrives and again whenever an existing system is changed, so short trials overstate the appeal of anything new. Source: Koch, von Luck, Schwarzer & Draheim 2018, The novelty effect in large display deployments: experiences and lessons-learned for evaluating prototypes, ECSCW 2018 (European Society for Socially Embedded Technologies), 2018; n = own field deployments plus literature review. https://doi.org/10.18420/ecscw2018_3
- **E165** (C, Q8) Google reports well-applied expressive design was preferred across all ages, most strongly (up to 87%) by 18-24 year olds. Source: Google Design 2025, Expressive design: Google's UX research, Google Design library, 2025; n = company studies. https://design.google/library/expressive-material-design-google-research
- **E166** (C, Q8) In Google's eyetracking test of 10 apps, people found key controls up to four times faster in the expressive versions, mainly because primary actions were larger, coloured and placed near use. Source: Google Design 2025, Expressive design: Google's UX research, Google Design library, 2025; n = lab eyetracking with a diverse group across 10 apps (count not given). https://design.google/library/expressive-material-design-google-research
- **E167** (C, Q8) Google also found expressive concepts that broke familiar patterns (unlabelled icons, scattered album art instead of a list) looked modern but scored worse on usability, and unfamiliarity lowered results. Source: Google Design 2025, Expressive design: Google's UX research, Google Design library, 2025; n = company usability tests. https://design.google/library/expressive-material-design-google-research
- **E169** (D, Q8) A design leader argued that Dribbble-style showcase work rewards surface polish: much of it looks the same across product types and ignores real problems. Source: Adams 2014, The dribbblisation of design (Intercom blog), Intercom blog, 2014; n = n/a. https://www.intercom.com/blog/the-dribbblisation-of-design/
- **E173** (A, Q9) Feature Congestion, a computational measure of visual clutter that works on any screenshot, is a widely used stand-in for how hard a display is to search. Source: Rosenholtz, Li & Nakano 2007, Measuring visual clutter, Journal of Vision, 2007; n = visual search experiments (counts in paper). https://doi.org/10.1167/7.2.17
- **E179** (A, Q10) Ten years of SUS data across many products showed the scale is robust and versatile, and the authors added an adjective rating and guidance on what counts as an acceptable score. Source: Bangor, Kortum & Miller 2008, An empirical evaluation of the System Usability Scale, International Journal of Human-Computer Interaction, 2008; n = nearly 10 years of SUS data from many products. https://doi.org/10.1080/10447310802205776
- **E181** (A, Q10) Across 11 studies, usability problem discovery follows a Poisson model; for a medium project the best benefit-to-cost ratio came at about four evaluators or users. Source: Nielsen & Landauer 1993, A mathematical model of the finding of usability problems, INTERCHI 1993, 1993; n = 11 studies. https://doi.org/10.1145/169059.169166
- **E182** (C, Q10) NN/g's rule: five users find about 85% of a design's usability problems; three small rounds of five beat one study of fifteen, while quantitative studies need about 20 users. Source: Nielsen 2000, Why you only need to test with 5 users (Nielsen Norman Group), Nielsen Norman Group article, 2000; n = based on Nielsen & Landauer 1993 model. https://www.nngroup.com/articles/why-you-only-need-to-test-with-5-users/
- **E183** (C, Q10) The Microsoft Desirability Toolkit (product reaction cards) has people pick the five words, from 118, that best describe a design; NN/g recommends cutting the list to about 25 for online surveys of visual appeal. Source: Moran 2016, Using the Microsoft Desirability Toolkit to test visual appeal (Nielsen Norman Group), Nielsen Norman Group article, 2016; n = n/a (method; original Benedek & Miner 2002 at Microsoft). https://www.nngroup.com/articles/microsoft-desirability-toolkit/
- **E184** (C, Q10) When first clicks went down the right path, 87% of users eventually succeeded at the task; after a wrong first click only 46% did. Source: Sauro 2011, Getting the first click right (MeasuringU), MeasuringU article, 2011; n = cites earlier research (Bailey & Wolfson). https://measuringu.com/first-click/
