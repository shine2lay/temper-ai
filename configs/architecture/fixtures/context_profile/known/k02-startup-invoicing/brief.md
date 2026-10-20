Subject: Ledgerly: context for the rebuild

Hi,

Ledgerly lets freelancers send invoices, chase late payments and see who owes them money. We launched fourteen months ago. Today we have 140 paying customers on our $19-a-month plan and about 600 more on the free tier. Revenue is around $2,700 a month, growing slowly but steadily.

Customers send about 9,000 invoices a month in total. Most of the traffic comes at the end of each month, when people bill their clients: the last three working days of the month carry roughly 40% of the month's invoices.

The current app is a single Rails app on one rented server that I set up myself. It has gone down twice this year, once for most of a day, and two customers cancelled because of it. Customers do not have a written uptime promise, but they expect the app to be up when they bill, and losing an invoice they already sent would be very bad for us. I would rather lose a day of draft edits than a single sent invoice.

Payments: clients pay invoices by card through Stripe Checkout. We never see or store card numbers and we want to keep it that way; card data must stay with Stripe. We store our customers' names, emails, business addresses, their clients' names and emails, and the invoice amounts.

Team: me (Dana, CEO and the only full-time developer) and a contractor, Sam, who gives us about two days a week. Sam knows React well; I know Rails and Postgres. Neither of us wants to manage servers by hand any more.

Money: we can spend up to $25,000 on the rebuild, and the running cost should come down from the current $400 a month if possible, because margins are thin. The rebuild budget is fixed: our investor agreed to that amount and no more.

Most of our customers are in the UK and Ireland, with a few in the US. Our accountant says we have to keep invoices for six years for tax reasons.

What I care about, in order: first, nothing sent gets lost and the app stays up at month end; second, lower running costs; third, being able to ship small features every week without fear.

Things I don't know: whether we need to be ready for a large accounting firm that is talking to us about putting 300 of its own clients on Ledgerly next year. Nothing is signed.

Thanks,
Dana
