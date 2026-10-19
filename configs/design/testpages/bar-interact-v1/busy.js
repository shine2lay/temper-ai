// bar-interact-v1 slow-script plant (Design, queue #79): a parser-blocking script in the head that
// busy-waits 700 ms before anything can paint. Loaded as an external file because Lighthouse's
// simulated throttling puts external blocking scripts on the LCP path; the same work inline did not
// move simulated LCP (see docs/design-homepage-bar-interaction.md, "Changes to definitions").
function busy(ms) { const end = performance.now() + ms; let n = 0; while (performance.now() < end) { n += 1; } return n; }
busy(700);
