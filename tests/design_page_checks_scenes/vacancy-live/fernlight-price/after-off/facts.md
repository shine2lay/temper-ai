# Measured facts (design_capture)

Measured by axe-core 4.13.0 and design_measure.js in a real browser, per viewport desktop 1280x800. A measured problem is a fact; so is a measured pass (never report a listed pass as a failure). Whether a problem matters, and everything about hierarchy, wording, flow and consistency, is the reviewer's to judge from the screenshots. The full numbers per view are in facts/<page>-<viewport>.json.

## index.html

Title: Fernlight — Keep your plants alive without the nagging.
Screenshots desktop (top to bottom, one screen each): shots/index-desktop-1.png, shots/index-desktop-2.png, shots/index-desktop-3.png, shots/index-desktop-4.png, shots/index-desktop-5.png, shots/index-desktop-6.png, shots/index-desktop-7.png, shots/index-desktop-8.png, shots/index-desktop-9.png

### Measured problems
- [desktop] empty column 388 px wide (35% of the 1124 px content width), on the middle, 384 px tall beside "No ads." in Price (from 4368 px) (page check: empty-column)
- [desktop] the same words repeat across sections (12 phrase(s)): "add a plant by photo" in Hero, Price, FAQ; "say which way the window faces and how far the plant sits from" in Hero, How it works, FAQ; "the day a plant needs water" in Value, How it works, FAQ; "east window 1 m away" in Value, How it works, Sample care plan; "plant window and season together set the schedule" in How it works, FAQ; "the seasons change the schedule changes with" in How it works, FAQ; "log the watering with one tap and it goes quiet until the next one" in How it works, FAQ; "how often to water it" in Sample care plan, FAQ (page check: repeated-copy)

### Measured passes (checked and fine: not failures)
- [desktop] all 3 interactive elements outside the header and footer navigation show a visible cue (border, fill, shadow, underline or icon) (page check: signifier)
- [desktop] 29 text element(s) over an image, gradient or translucent layer pass contrast measured from the pixels behind their letters; closest: `div.wrap.price-grid > div.price-copy:nth-of-type(1) > div.price-notes > p.lead:nth-of-type(1)` "Your first 5 plants cost nothing. You pi" 4.87:1 (needs 4.5:1) (page check: text-over-image)

### Text and structure (desktop)
Type styles (size weight: count): 87.04px 400: 2, 60px 400: 1, 56.32px 400: 2, 53.76px 400: 6, 43.52px 400: 3, 35.84px 400: 3, 33.28px 400: 2, 30px 400: 2, 28px 400: 9, 25.6px 400: 3, 24px 400: 2, 20.48px 700: 10, 20px 400: 1, 19.2px 400: 6, 18px 700: 5, 17px 700: 20, 17px 400: 24, 16px 400: 2, 16px 700: 20
Largest text: span 87.04px/400 rgb(251,241,222) "Keep your plants alive"; span 87.04px/400 rgb(198,232,106) "without the nagging."; p 60px/400 rgb(126,47,28) "Monstera"; p 56.32px/400 rgb(43,27,20) "$0"; p 56.32px/400 rgb(43,27,20) "$3"
Headings: h1 87.04px/400 "Keep your plants alive without the nagging."; h2 53.76px/400 "For anyone who has watered too much, or too little"; h3 25.6px/400 "Set by your window and the season"; h3 25.6px/400 "One tap, then quiet"; h3 25.6px/400 "A care card for every plant"; h2 53.76px/400 "Your window and the season set the schedule."; h3 20.48px/700 "Add a plant"; h3 20.48px/700 "Describe its spot"; h3 20.48px/700 "Fernlight sets the schedule"; h3 20.48px/700 "Water on watering day"; h2 53.76px/400 "Stop guessing when to water."; h3 16px/700 "WATERING SCHEDULE"; h3 16px/700 "FEEDING"; h2 53.76px/400 "What does it cost?"; h3 33.28px/400 "Free"; h3 33.28px/400 "Fernlight Plus"; h3 16px/700 "PRICE"; h2 53.76px/400 "Questions, answered plainly."; h3 20.48px/700 "Will it nag me?"; h3 20.48px/700 "How does it know when to water?"; h3 20.48px/700 "Will it tell me exactly when to water?"; h3 20.48px/700 "Which plants can I add?"; h3 20.48px/700 "What is in the sample care plan?"; h3 20.48px/700 "What does it cost?"; h2 53.76px/400 "One quiet reminder, on the day it counts."
Tab order (14 stops): Fernlight > How it works > Care plan > Price > Questions > See a sample care plan > See a sample care plan > Read how your schedule works > See a sample care plan > Fernlight > How it works > Care plan > Price > Questions
Landmarks: header, nav, main, footer, nav

### Page checks: facts that are not pass or fail
Pictures by section (desktop; img, svg, canvas, video and CSS background images; icons under 48 px left out; share = part of the section's area; a product mock-up built from page elements, such as a sample report card or a table, is not counted here: judge it from the screenshots):
- Header (page chrome): 0 picture(s), 0% of the section
- Hero: 4 picture(s), 31% of the section: svg 473x544 (aria-hidden), svg 107x214, svg 209x251, svg 98x151
- Value: 0 picture(s), 0% of the section
- How it works: 1 picture(s), 14% of the section: svg 499x376 "Plan of a room from above: light falls through the east wind"
- Sample care plan: 10 picture(s), 2% of the section: svg 56x60 (aria-hidden), svg 56x60 (aria-hidden), svg 56x60 (aria-hidden), svg 56x60 (aria-hidden)
- Price: 0 picture(s), 0% of the section
- FAQ: 1 picture(s), 1% of the section: svg 80x96 (aria-hidden)
- Closing CTA: 1 picture(s), 9% of the section: svg 416x208 (aria-hidden)
- Footer (page chrome): 0 picture(s), 0% of the section
First screen covered by pictures: desktop 26%
Sections with no picture: Value, Price
Interactive elements checked for a visible cue: 3 (border 2, fill 2, icon 1, shadow 2, underline 1); links in a header or footer navigation bar, known by their place: 11
Text over images, gradients or translucent layers measured from pixels: 29 text element(s) over all views
Dark colour scheme: not offered by the page.
