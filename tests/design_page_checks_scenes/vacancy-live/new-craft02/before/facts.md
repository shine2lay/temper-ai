# Measured facts (design_capture)

Measured by axe-core 4.13.0 and design_measure.js in a real browser, per viewport desktop 1280x800. A measured problem is a fact; so is a measured pass (never report a listed pass as a failure). Whether a problem matters, and everything about hierarchy, wording, flow and consistency, is the reviewer's to judge from the screenshots. The full numbers per view are in facts/<page>-<viewport>.json.

## index.html

Title: Claybird Studio — pottery classes for beginners
Screenshots desktop (top to bottom, one screen each): shots/index-desktop-1.png, shots/index-desktop-2.png, shots/index-desktop-3.png, shots/index-desktop-4.png, shots/index-desktop-5.png

### Measured problems
- [desktop] empty column 568 px wide (48% of the 1184 px content width), on the right, 464 px tall beside "Three ways in" in classes (from 806 px) (page check: empty-column)
- [desktop] empty column 531 px wide (45% of the 1184 px content width), on the left, 320 px tall beside "Two hours, one skill at a time. You leave with clay under yo" in how (from 1609 px) (page check: empty-column)

### Measured passes (checked and fine: not failures)
- [desktop] all 3 interactive elements outside the header and footer navigation show a visible cue (border, fill, shadow, underline or icon) (page check: signifier)
- [desktop] no word run of 5+ words repeated in 3+ sections (or 8+ words in 2+), prose only (page check: repeated-copy)
- [desktop] under 24x24 px but meets WCAG 2.5.8 by the spacing exception (its 24 px circle touches no other target): `div.wrap.nav > ul.nav-links > li:nth-of-type(1) > a` "Classes" 60x22 px; nearest other target `div.wrap.nav > ul.nav-links > li:nth-of-type(2) > a` "How it works" 62 px from its centre
- [desktop] under 24x24 px but meets WCAG 2.5.8 by the spacing exception (its 24 px circle touches no other target): `div.wrap.nav > ul.nav-links > li:nth-of-type(2) > a` "How it works" 108x22 px; nearest other target `div.wrap.nav > ul.nav-links > li:nth-of-type(1) > a` "Classes" 86 px from its centre
- [desktop] under 24x24 px but meets WCAG 2.5.8 by the spacing exception (its 24 px circle touches no other target): `div.wrap.nav > ul.nav-links > li:nth-of-type(3) > a` "Prices" 51x22 px; nearest other target `div.wrap.nav > ul.nav-links > li:nth-of-type(2) > a` "How it works" 57.5 px from its centre
- [desktop] under 24x24 px but meets WCAG 2.5.8 by the spacing exception (its 24 px circle touches no other target): `div.wrap.nav > ul.nav-links > li:nth-of-type(4) > a` "Questions" 82x22 px; nearest other target `div.wrap.nav > ul.nav-links > li:nth-of-type(3) > a` "Prices" 73 px from its centre
- [desktop] under 24x24 px but meets WCAG 2.5.8 by the spacing exception (its 24 px circle touches no other target): `footer.footer > div.wrap.foot > div > a.mark` "Claybird" 53x22 px; nearest other target `div.wrap.foot > ul.foot-links > li:nth-of-type(1) > a` "Classes" 956.7 px from its centre
- [desktop] under 24x24 px but meets WCAG 2.5.8 by the spacing exception (its 24 px circle touches no other target): `div.wrap.foot > ul.foot-links > li:nth-of-type(1) > a` "Classes" 49x17 px; nearest other target `div.wrap.foot > ul.foot-links > li:nth-of-type(2) > a` "Prices" 48.5 px from its centre
- [desktop] under 24x24 px but meets WCAG 2.5.8 by the spacing exception (its 24 px circle touches no other target): `div.wrap.foot > ul.foot-links > li:nth-of-type(2) > a` "Prices" 39x17 px; nearest other target `div.wrap.foot > ul.foot-links > li:nth-of-type(1) > a` "Classes" 43.5 px from its centre
- [desktop] under 24x24 px but meets WCAG 2.5.8 by the spacing exception (its 24 px circle touches no other target): `div.wrap.foot > ul.foot-links > li:nth-of-type(3) > a` "Questions" 65x17 px; nearest other target `div.wrap.foot > ul.foot-links > li:nth-of-type(2) > a` "Prices" 56.5 px from its centre

### Text and structure (desktop)
Type styles (size weight: count): 76px 400: 1, 44px 400: 5, 24px 400: 18, 18px 600: 17, 18px 400: 14, 14px 600: 2, 14px 400: 11
Largest text: h1 76px/400 rgb(43,33,28) "Make something you’ll keep."; h2 44px/400 rgb(43,33,28) "Three ways in"; h2 44px/400 rgb(43,33,28) "How a class runs"; h2 44px/400 rgb(251,246,240) "Keep going after your course"; h2 44px/400 rgb(43,33,28) "Prices"
Headings: h1 76px/400 "Make something you’ll keep."; h2 44px/400 "Three ways in"; h3 24px/400 "Wheel basics"; h2 44px/400 "How a class runs"; h3 18px/600 "Arrive and settle in"; h3 18px/600 "Watch, then try"; h3 18px/600 "Shape now, trim later"; h3 18px/600 "Glaze and collect"; h2 44px/400 "Keep going after your course"; h2 44px/400 "Prices"; h2 44px/400 "Questions"
Tab order (13 stops): Claybird > Classes > How it works > Prices > Questions > Book a taster > Book a taster class > See how a class runs > Join open studio > Claybird > Classes > Prices > Questions
Landmarks: header, main, footer

### Page checks: facts that are not pass or fail
Pictures by section (desktop; img, svg, canvas, video and CSS background images; icons under 48 px left out; share = part of the section's area; a product mock-up built from page elements, such as a sample report card or a table, is not counted here: judge it from the screenshots):
- header (page chrome): 0 picture(s), 0% of the section
- hero: 1 picture(s), 18% of the section: svg 403x336 "Three handmade pots on a wooden shelf"
- classes: 0 picture(s), 0% of the section
- how: 0 picture(s), 0% of the section
- open-studio: 0 picture(s), 0% of the section
- prices: 0 picture(s), 0% of the section
- questions: 0 picture(s), 0% of the section
- footer (page chrome): 0 picture(s), 0% of the section
First screen covered by pictures: desktop 14%
Sections with no picture: classes, how, open-studio, prices, questions
Interactive elements checked for a visible cue: 3 (fill 2, underline 1); links in a header or footer navigation bar, known by their place: 10
Text over images, gradients or translucent layers measured from pixels: 0 text element(s) over all views
Dark colour scheme: not offered by the page.
