# Rigshare: architecture brief, compiled by the CTO's office

Rigshare is an online marketplace where construction companies rent heavy equipment (excavators, cranes, loaders) from rental firms. Rental firms list machines; contractors book them by the day or week and pay through the platform.

## Numbers

We are three years old. 220 rental firms list about 1,900 machines, and about 3,100 bookings are made each month, almost all in the Netherlands and Belgium. Annual revenue reached $1.4M and roughly doubled last year. Bookings peak on Monday mornings, when site managers plan their week: about a quarter of the week's bookings come in before noon on Monday.

## Team and money

Engineering is nine people: six backend developers (Python and Postgres), two frontend developers and one engineer who handles infrastructure and on-call. On-call is a single person, which has become a worry. The engineering budget for this year is $1.2M, people included. Hosting costs about $14,000 a month.

## Rules

Payments run through an escrow service from a licensed payment provider. Our lawyers are clear that we must not hold customers' money ourselves, because that would require a payment licence we do not have. We store company names, contact people, phone numbers and booking histories; bank details stay with the payment provider. Customers in the EU are covered by GDPR, and the German launch adds no new rule beyond that as far as our lawyers know.

## Priorities: where we disagree

The board has said that the CEO makes the final call on priorities, and her ranking is the one this review should use. She ranks them:

1. Launch in Germany before the June trade fair, where most German rental firms meet buyers.
2. Keep the platform up, especially on Monday mornings.
3. Keep hosting costs from growing faster than revenue.

The CTO disagrees. His view is that reliability should come first: Monday-morning slowdowns have cost us two large rental firms this year, and he wants three months to pay down technical debt before any launch.

The head of sales wants a third thing: an enterprise contract with Baumann Group, a German rental chain with 4,000 machines, which would need single sign-on and an API for their fleet system. Sales says Baumann "is basically signed"; no contract exists yet.

The CTO has asked the board to revisit the ranking. The board has not answered yet.

## Open questions

Whether Baumann signs, and when, decides whether we need single sign-on and an API this year. We also do not know how much German traffic to expect; the CEO's plan says 1,000 bookings a month in the first year, the CTO thinks less.
