"""Fixed local browser pages and frozen expected answers for capture v2."""
import json

CASES = {"short": "usable", "lazy": "usable", "sticky": "usable", "hero": "usable",
         "reject": "usable", "accept_only": "uncertain", "iframe": "usable",
         "blank": "incomplete", "broken": "incomplete", "endless": "incomplete", "blocked": "not usable",
         "overflow": "usable", "lazyfar": "usable", "carousel": "usable", "ticker": "uncertain",
         "marquee": "usable", "slide": "usable", "holding": "not usable"}
# First-screen answers where they matter for a repair (R10-R13); the rest follow CASES.
FIRST = {"lazyfar": "usable", "carousel": "usable", "ticker": "uncertain", "marquee": "usable",
         "slide": "usable", "overflow": "usable", "holding": "not usable"}
OVERFLOW_WIDTH = 1600
URL = "https://capture-fixture.example/"
SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="240"><rect width="400" height="240" fill="#008080"/><circle cx="200" cy="120" r="60" fill="#ffcc22"/></svg>'


def html(case):
    body = '<main><h1>A complete small homepage</h1><p>A useful service with clear information and a contact link.</p></main>'
    style, script = "", ""
    if case in ("lazy", "sticky", "hero", "endless", "lazyfar"):
        style += 'section{height:100vh;background:linear-gradient(110deg,#e8ecfc,#d0fcf0);padding:32px}section:nth-child(even){background:linear-gradient(110deg,#fcdfca,#f0dafa)}'
        body = '<main><section><h1>A complete generous hero</h1><p>Real visible content is not an incomplete blank homepage.</p></section>'
        if case == "lazy":
            body += '<section><h2>Below-fold lazy image</h2><img loading="lazy" src="/late.svg" width="300" height="180"><p>The image must finish loading here.</p></section>'
        elif case == "sticky":
            style += 'header{position:sticky;top:0;height:48px;background:rgb(255,0,100);z-index:9}main{padding:0!important}'
            body = '<header>ONE STICKY HEADER</header>' + body
            body += '<section><h2>Second content screen</h2><p>The header appears once in the full screenshot.</p></section>'
        elif case == "lazyfar":
            for n in range(2, 6):
                body += f'<section><h2>Content screen {n}</h2><p>Plain content between the hero and a far lazy image.</p></section>'
            body += '<section><h2>Far lazy image</h2><img loading="lazy" src="/late.svg" width="300" height="180"><p>Loads only once a visitor scrolls here.</p></section>'
        elif case == "endless":
            script = "addEventListener('scroll',()=>{if(scrollY+innerHeight>=document.body.scrollHeight-2){const s=document.createElement('section');s.innerHTML='<h2>Another feed screen</h2><p>More feed content appears on reaching the end.</p>';document.querySelector('main').append(s)}})"
        body += '</main><footer>End of this complete test homepage</footer>'
    if case == "blank":
        body = '<main><h1>Known damaged homepage</h1><p>Content above a genuinely missing region.</p><div style="height:90vh"></div><h2>Content below the missing region</h2><p>This large interior blank band must be reported.</p></main>'
    if case == "broken":
        body += '<img src="/broken.png" width="300" height="180">'
    if case == "overflow":
        # The text itself is wider than both viewports (clipped at the box), so it runs past the right edge.
        body += (f'<div style="position:absolute;left:0;top:420px;width:{OVERFLOW_WIDTH}px;overflow:hidden;white-space:nowrap;font-size:18px">'
                 + 'A deliberately unwrapped line that runs past the right edge of the screen for the overflow check. ' * 3 + '</div>')
    if case == "carousel":
        body += ('<div style="overflow:hidden;width:100%"><div style="display:flex"><img src="/late.svg" width="300" height="180">'
                 '<img loading="lazy" src="/late.svg?parked" width="300" height="180" style="margin-left:6000px;flex:none">'
                 '<img src="/broken.png" width="300" height="180" style="margin-left:3000px;flex:none"></div></div>')
    if case == "ticker":
        body += '<p id="ticker">Live count 0</p>'
        script = "let n=0;setInterval(()=>{document.getElementById('ticker').textContent='Live count '+(++n)},20)"
    if case == "marquee":
        body += '<p id="marquee" style="position:absolute;top:200px;left:-4000px;white-space:nowrap">Moving text kept far off screen</p>'
        script = "let n=0;setInterval(()=>{document.getElementById('marquee').style.left=(-4000+(++n%40)*20)+'px'},20)"
    if case == "slide":
        body += '<p id="slide" style="position:relative">A testimonial that slides sideways inside the screen</p>'
        script = "let n=0;setInterval(()=>{document.getElementById('slide').style.left=((++n%10)*12)+'px'},20)"
    if case == "holding":
        body = ('<main><h1>Sit tight</h1><p>This page will automatically refresh when it is your turn.</p>'
                '<p>Need help? Call 1-800-000-0000.</p></main>')
    if case == "blocked":
        body = '<main><h1>Access denied</h1><p>This request was blocked. No bypass is permitted.</p></main>'
    if case in ("reject", "accept_only", "iframe"):
        buttons = '<button onclick="this.closest(\'.cookie\').remove()">Accept all</button>'
        if case != "accept_only":
            buttons += '<button id="onetrust-reject-all-handler" onclick="this.closest(\'.cookie\').remove()">Reject all</button>'
        cookie = '<div class="cookie" role="dialog" style="position:fixed;bottom:0;left:0;right:0;background:#eedddd;padding:24px;z-index:90">We use cookies for optional analytics. ' + buttons + '</div>'
        if case == "iframe":
            import html as html_module
            inner = '<!doctype html><html><body>' + cookie + '</body></html>'
            body += '<iframe title="Cookie consent" style="position:fixed;bottom:0;left:0;width:100%;height:180px;border:0" srcdoc="' + html_module.escape(inner, quote=True) + '"></iframe>'
        else:
            body += cookie
    title = "Hang Tight! Routing to checkout..." if case == "holding" else "Known capture case " + case
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><title>' + title + '</title><style>'
            '*{box-sizing:border-box}body{margin:0;color:#123;font-family:sans-serif;background:white}main{padding:32px}h1{font-size:32px}p{font-size:18px}button{padding:16px;margin:8px}'
            + style + '</style></head><body>' + body + ('<script>' + script + '</script>' if script else '') + '</body></html>')


def setup_code(case):
    response = {"status": 403 if case == "blocked" else 200, "contentType": "text/html", "body": html(case)}
    return ("async context => {await context.route('**/*',async route=>{const u=route.request().url();"
            "if(u.includes('/late.svg')){await route.request().frame().page().waitForTimeout(80);return route.fulfill({status:200,contentType:'image/svg+xml',body:" + json.dumps(SVG) + "});}"
            "if(u.endsWith('/broken.png'))return route.fulfill({status:404,body:'missing'});"
            "return route.fulfill(" + json.dumps(response) + ");});}")
