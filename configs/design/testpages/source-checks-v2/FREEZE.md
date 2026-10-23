# source-checks-v2: freeze record

Built by `plant_key.py` (stdlib only; it never imports or runs a kernel) on 2026-10-23 at 12:30:53 PDT
(epoch 1792783853), in the worktree of Design queue task #143, before H16's widened kernels were copied
into this repository. At that moment `configs/design/bin/source_checks/` still held the d158dfa kernels:
`source_h1_kernel.py` sha256 7d6129239afc9b330bf2c174537da8c5a7d2286575f3ed4d5e4438e35d1d517c and
`headline_words_kernel.py` sha256 7cc97830ac75b4805c877ba1db67849d1974cd904e9cdc5074b6fa76fa65b714,
neither of which reads these pages (the old guard accepts id roots only).

File times at the freeze (local, PDT): `plant_key.py` 12:30:20.375; every fixture, INPUTS.json and
EXPECTED.jsonl 12:30:53.535 to 12:30:53.539. Git keeps no file times, so these are recorded here only.

What it holds: 4 public pages (`configs/design/testpages/html-fixtures/{harbor,pulse,rich,atlas}.html`)
x 6 variants (P0 the normalized page with Body marks, P1 a second visible h1, P2 the h1 demoted to h2,
P3 a hidden second h1, P4 a 15-word headline with its matching declaration, P5 a headline one word off
its declaration) = 24 fixtures, one environment (1440x900), so 24 records per check:

- A2-01 (one h1): 12 true (P0, P4, P5), 12 false (P1 and P3 count 2, P2 count 0), 0 guard refusals.
- A1-02 (headline words): 4 bound and within 12 words (P0), 4 bound at 15 words (P4), 16 unbound
  (P1, P2, P3, P5), 0 guard refusals.

The expected records are truth by construction from the checks' rules (see `plant_key.py`), frozen
here. Nothing in this folder may change after the freeze; `tests/test_design_source_checks.py` checks
every file below against its hash, and that no other file is in the folder. Check by hand with
`sha256sum -c` on the block below, from this folder.

```
7bb3909c39581cd2c7e19c9335cfcd71227a936d001553a08274afe2b7c7c63a  a1-02-headline-words/EXPECTED.jsonl
fee76c934c0ff344cf114db491ed96b3fa328e3176850745b4c8e5ca1557370f  a1-02-headline-words/INPUTS.json
8c9ac561cd5182cadd599ed21ba54a4c1a236619eb40e75fbc9899ab7de4df63  a2-01-source-h1/EXPECTED.jsonl
77f73ec94fdf7cd4383e848a48dd64ce3a1d70362fc64dd4e5da5eccba6f8678  a2-01-source-h1/INPUTS.json
066ac4cb4555df5c74e10dc2fc7ddaa53d245e2471a2d423c6f0c0e04658a6ea  fixtures/atlas-P0.html
ac1b66713aa282c02afffd54467896ef67b9f676229cef9d93deabcd29928c8d  fixtures/atlas-P1.html
61db9b9b9dd961e75b724fcbe26080751010810c794a324d9405b0f2d5f9503c  fixtures/atlas-P2.html
855224944e3367439fa37cd6b9a8bef502aae303680ae970aa4c1d6ba1e3ce95  fixtures/atlas-P3.html
265276203b59098590caa245437eadaec3ef3d8282be504b4f7b0c8fed760244  fixtures/atlas-P4.html
f89e25fcf1395bac042386476aad41d8a5ba77ff62f8c42b9d64f836ca4b5a69  fixtures/atlas-P5.html
0452af605c4583cc2b3cf91ef4d69df625951ee0a945dd20a1d425121b6cd360  fixtures/harbor-P0.html
507abd6dadf491473e0e530cf17e7c3178e2b6d11197ef382c53b0fa33465a38  fixtures/harbor-P1.html
5b382a7a930c7f06a60bb6796a232175c288d916f833a81bb95473dcb8879c71  fixtures/harbor-P2.html
4d99232c61891a5adddc7df09b8f6162a8ca31d02e72608a7dc0eda1a61acfea  fixtures/harbor-P3.html
f6a894458b11f1c605553d6bf064267826c893d15311b1bd8d34075357540199  fixtures/harbor-P4.html
fafa12b67f6f6fcff7d8a181ed84277a4aee90dd26a82fad71da339b1d7987fb  fixtures/harbor-P5.html
95d05ecd363556d7765f17fd99d2177c4a22e8b14a9cf0ad1d41d8687a04be69  fixtures/pulse-P0.html
b577247f172d791ac4830321d26809d68d65ed488dca18c88ce9db18ff143555  fixtures/pulse-P1.html
7ac8d13b780ddba2f005645ab7faf6af4ef959fc60182a0890b37d8ae08845e6  fixtures/pulse-P2.html
898f1e1550ce04d1715830a298814ce8802a4cd3d53a7dfc83a4acf32202cf4a  fixtures/pulse-P3.html
bad560c97bfc457fc9cc4a9aae56b3bf0ca3b8c12c7df079e38554e125ab1b6b  fixtures/pulse-P4.html
f60c625c4a6fe0957016a7c0df8d32431ae65dc58df1c16b9636de0a76219505  fixtures/pulse-P5.html
1c44af20b00ceabf25eb12cb82cbb62cdf50bc2fbd666863315e6be050c14a1d  fixtures/rich-P0.html
1b5e5936a99246cb10a330a782e620ef72a0b82bb1f49176f70d5279014e83db  fixtures/rich-P1.html
7c9a1849321c94ea2861ba8a4144ea13ad5136f6de67f2d4e67ff591754a5bf9  fixtures/rich-P2.html
9ad970b67573b0d988fabe31cced87944db3d2f99052687baadfd3151c4b4cff  fixtures/rich-P3.html
7583efe83a0ad4d2fd30bc882ecbc04911718573f68d261d47af4aa8ccf9fcfc  fixtures/rich-P4.html
c8c513b3630b31ed37dc6cd63623f6f7c26e23bf7db55c6f45225ecd0e1e130c  fixtures/rich-P5.html
1037938befa8bfaa3625fdf451d60bad72b443fc06b1147969447452e2670016  plant_key.py
```

The sha256 of that 29-line listing (as `sha256sum` prints it, sorted by path) is
892761089a4c70889e4656732c9e44f624fac96d29a5a433f3a9f30f8760d9c4.
