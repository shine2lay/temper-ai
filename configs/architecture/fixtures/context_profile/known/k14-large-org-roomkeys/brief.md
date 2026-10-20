# CabinetLedger: a small tool inside a large organisation

Harbor Research employs 18,000 people across many divisions. CabinetLedger is not a company-wide platform: it is the facilities team's internal register for the keys to locked specimen cabinets. Forty facilities staff use it. They have used it for six years, the need is proven, and both staff numbers and request volume have stayed flat for three years. No expansion is planned. The organisation's size does not create a large workload for this tool.

## Current system and use

A small Django application and SQLite database run on one internal virtual machine. Facilities staff use a browser to record who collected a cabinet key and when it was returned. There are about 90 transactions per working day, with no more than four people using the tool at once. Most activity is at the start of the morning shift. The tool reads staff identities from the organisation's Entra ID tenant; it owns neither that identity provider nor its directory.

The page sometimes feels slow when a clerk checks a key back in. Nobody has measured the delay or agreed how fast it needs to be. The facilities manager says this matters because a queue at the desk delays laboratory access. There is no numeric response-time promise to extract from this brief.

## Non-negotiable boundaries

The security office requires sign-in through Entra ID, multifactor authentication, and access limited to the facilities group. Company audit policy requires an append-only access log retained for seven years. Identifiable staff records must stay in the organisation's UK data centre. These controls and the retention period are mandatory, even though the traffic is low. The register contains employee identifiers and cabinet identifiers; it contains no research samples or patient records. There is no named attack or security incident.

## Delivery and support

One internal developer knows Python and Django and can give the tool one day each week. Central IT supports the virtual machine during office hours; there is no overnight pager. The approved change budget is $8,000. The virtual machine is already funded, but finance has not assigned a monthly allowance for this tool. Facilities can use its paper key ledger during an outage; records entered before an outage must not be lost. There is no agreed restoration deadline.

The facilities manager ranks simpler upkeep first, better response speed second, and lower running cost third. The director's suggestion to open the tool to every researcher is only an idea for next year; it is not approved and must not be treated as present demand.
