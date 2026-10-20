# Measured facts (design_capture)

Measured by axe-core 4.13.0 and design_measure.js in a real browser, per viewport desktop 1280x800. A measured problem is a fact; so is a measured pass (never report a listed pass as a failure). Whether a problem matters, and everything about hierarchy, wording, flow and consistency, is the reviewer's to judge from the screenshots. The full numbers per view are in facts/<page>-<viewport>.json.

## index.html

Title: Loamwise: weekly kitchen compost pickup
Screenshots desktop (top to bottom, one screen each): shots/index-desktop-1.png, shots/index-desktop-2.png, shots/index-desktop-3.png, shots/index-desktop-4.png, shots/index-desktop-5.png, shots/index-desktop-6.png
Screenshots desktop-dark (top to bottom, one screen each): shots/index-desktop-dark-1.png, shots/index-desktop-dark-2.png, shots/index-desktop-dark-3.png, shots/index-desktop-dark-4.png, shots/index-desktop-dark-5.png, shots/index-desktop-dark-6.png

### Measured problems
- [desktop] empty column 477 px wide (43% of the 1120 px content width), on the left, 560 px tall beside "What can go in?" in Questions (from 3014 px) (page check: empty-column)

### Measured passes (checked and fine: not failures)
- [desktop+desktop-dark] all 6 interactive elements outside the header and footer navigation show a visible cue (border, fill, shadow, underline or icon) (page check: signifier)
- [desktop] 5 text element(s) over an image, gradient or translucent layer pass contrast measured from the pixels behind their letters; closest: `div.wrap > div.hero-text:nth-of-type(1) > div.actions > a:nth-of-type(2)` "See how it works" 5.69:1 (needs 4.5:1) (page check: text-over-image)
- [desktop-dark] 5 text element(s) over an image, gradient or translucent layer pass contrast measured from the pixels behind their letters; closest: `section.hero:nth-of-type(1) > div.wrap > div.hero-text:nth-of-type(1) > p.eyebrow:nth-of-type(1)` "KITCHEN COMPOST PICKUP" 9.16:1 (needs 4.5:1) (page check: text-over-image)
- [desktop] no word run of 5+ words repeated in 3+ sections (or 8+ words in 2+), prose only (page check: repeated-copy)
- [desktop+desktop-dark] under 24x24 px but meets WCAG 2.5.8 by the spacing exception (its 24 px circle touches no other target): `header.site-header > div.wrap > nav.site-nav > a:nth-of-type(1)` "How it works" 91x23 px; nearest other target `header.site-header > div.wrap > nav.site-nav > a:nth-of-type(2)` "Prices" 73.5 px from its centre
- [desktop+desktop-dark] under 24x24 px but meets WCAG 2.5.8 by the spacing exception (its 24 px circle touches no other target): `header.site-header > div.wrap > nav.site-nav > a:nth-of-type(2)` "Prices" 41x23 px; nearest other target `header.site-header > div.wrap > nav.site-nav > a:nth-of-type(1)` "How it works" 48.5 px from its centre
- [desktop+desktop-dark] under 24x24 px but meets WCAG 2.5.8 by the spacing exception (its 24 px circle touches no other target): `header.site-header > div.wrap > nav.site-nav > a:nth-of-type(3)` "Questions" 69x23 px; nearest other target `header.site-header > div.wrap > nav.site-nav > a:nth-of-type(2)` "Prices" 62.5 px from its centre
- [desktop+desktop-dark] under 24x24 px but meets WCAG 2.5.8 by the spacing exception (its 24 px circle touches no other target): `footer.site-footer > div.wrap > nav > a:nth-of-type(1)` "How it works" 89x23 px; nearest other target `footer.site-footer > div.wrap > nav > a:nth-of-type(2)` "Prices" 68.5 px from its centre
- [desktop+desktop-dark] under 24x24 px but meets WCAG 2.5.8 by the spacing exception (its 24 px circle touches no other target): `footer.site-footer > div.wrap > nav > a:nth-of-type(2)` "Prices" 40x23 px; nearest other target `footer.site-footer > div.wrap > nav > a:nth-of-type(1)` "How it works" 44 px from its centre
- [desktop+desktop-dark] under 24x24 px but meets WCAG 2.5.8 by the spacing exception (its 24 px circle touches no other target): `footer.site-footer > div.wrap > nav > a:nth-of-type(3)` "hello@loamwise.example" 168x23 px; nearest other target `footer.site-footer > div.wrap > nav > a:nth-of-type(2)` "Prices" 108 px from its centre

### Text and structure (desktop)
Type styles (size weight: count): 56px 600: 1, 40px 600: 7, 22px 600: 6, 22px 400: 1, 18px 600: 10, 18px 400: 22, 15px 600: 3, 15px 800: 4, 15px 400: 5
Largest text: h1 56px/600 rgb(46,36,25) "Your food scraps, collected every week and turned "; h2 40px/600 rgb(46,36,25) "How a pickup works"; h2 40px/600 rgb(46,36,25) "What your scraps become"; h2 40px/600 rgb(46,36,25) "What it costs"; p 40px/600 rgb(90,74,58) "$6"
Headings: h1 56px/600 "Your food scraps, collected every week and turned "; h2 40px/600 "How a pickup works"; h3 22px/600 "Fill the caddy"; h3 22px/600 "Put the bin out on Tuesday"; h3 22px/600 "We swap it"; h2 40px/600 "What your scraps become"; h2 40px/600 "What it costs"; h3 22px/600 "Weekly"; h3 22px/600 "Every other week"; h2 40px/600 "Questions"; h2 40px/600 "Start with one Tuesday"
Tab order (13 stops): Loamwise home > How it works > Prices > Questions > Book a pickup > See how it works > Choose weekly > Choose every other week > hello@loamwise.example > Book a pickup > How it works > Prices > hello@loamwise.example
Landmarks: header, nav, main, footer, nav

### Text and structure (desktop-dark): where it differs
Largest text: h1 56px/600 rgb(241,232,218) "Your food scraps, collected every week and turned "; h2 40px/600 rgb(241,232,218) "How a pickup works"; h2 40px/600 rgb(241,232,218) "What your scraps become"; h2 40px/600 rgb(241,232,218) "What it costs"; p 40px/600 rgb(210,196,174) "$6"
Tab order (0 stops): 

### Page checks: facts that are not pass or fail
Pictures by section (desktop; img, svg, canvas, video and CSS background images; icons under 48 px left out; share = part of the section's area; a product mock-up built from page elements, such as a sample report card or a table, is not counted here: judge it from the screenshots):
- Header (page chrome): 0 picture(s), 0% of the section
- Hero: 1 picture(s), 21% of the section: svg 475x410 "A green kitchen caddy with a sealed lid, full of peels, coff"
- How it works: 3 picture(s), 24% of the section: svg 352x211 "The caddy inside the cupboard under the sink, next to a roll", svg 352x211 "The full bin on the front step before the round, with a cloc", svg 352x211 "A small electric van; the driver leaves a washed bin and tak"
- What it makes: 1 picture(s), 27% of the section: svg 528x352 "Chart: about 180 kg of scraps in a year become about 60 kg o"
- Prices: 0 picture(s), 0% of the section
- Questions: 0 picture(s), 0% of the section
- Start: 0 picture(s), 0% of the section
- Footer (page chrome): 0 picture(s), 0% of the section
First screen covered by pictures: desktop 20%
Sections with no picture: Prices, Questions, Start
Interactive elements checked for a visible cue: 6 (border 2, fill 2, underline 2); links in a header or footer navigation bar, known by their place: 7
Text over images, gradients or translucent layers measured from pixels: 10 text element(s) over all views
Dark colour scheme: the page offers one; captured as view desktop-dark (prefers-color-scheme: dark).
