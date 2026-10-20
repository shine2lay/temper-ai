# RouteWise: architecture review request

RouteWise plans delivery routes for courier companies. Dispatchers load the day's parcels in the morning, RouteWise builds the routes, and drivers follow them in our driver app, which re-plans when a stop fails or traffic changes.

The system holds no personal data; it only deals with parcels and routes. That is how our sales team describes it, and it is what most of our customers believe.

## Business

We have 38 courier companies as customers, up from 12 a year ago, and we are now 14 people, 9 of them engineers. Customers pay per driver per month. Our contracts promise customers 99.5% monthly uptime during their operating hours, with service credits when we miss it.

## Load

On a weekday about 9,000 drivers are on shift on RouteWise, and we handle roughly 1.5 million stops a month. Most route building happens between 5am and 7am, when every depot loads its parcels at once. In the week before Christmas the number of stops roughly doubles.

## What the data really is

Each stop holds the recipient's name, delivery address and phone number, and sometimes a note such as "door code 4471". The driver app records each driver's GPS position every 10 seconds during a shift, and we keep the traces for 2 years to settle delivery disputes. Nobody has checked whether drivers' employment contracts mention this tracking, or whether 2 years is a period we can defend.

Our EU customers require that their data stays in the EU, and it is written into their contracts. About a third of our customers are in the EU; the rest are in the UK.

## Team and money

Hosting costs $28,000 a month. We have set aside $150,000 for this work. Our engineers know TypeScript, Node and PostgreSQL well; one of them has run Kubernetes before.

## What we want

First, fewer incidents during morning dispatch. Second, bring the hosting bill down. Third, make it easier to add a new customer's depot rules without code changes.
