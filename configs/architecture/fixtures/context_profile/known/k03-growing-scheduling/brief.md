# Shiftwise platform review: brief for architecture

## Company and product

Shiftwise sells shift scheduling and time tracking to restaurants and cafés. Managers build the weekly rota; staff swap shifts and clock in on their phones. We are four years old, with 380 business customers and about 45,000 staff who use the app each month. Annual recurring revenue passed $3.1M last quarter and has grown about 60% a year for two years. Engineering is 14 people in three teams (scheduling, payroll exports, mobile), plus one person who looks after infrastructure part of the time.

## Load today

- Around 2.5 million API requests on a normal weekday.
- Sunday evening is the busiest time by far: managers publish next week's rota between 6pm and 9pm, and request rates reach about 8 times the weekday average for those three hours.
- Clock-ins cluster at the start of shifts, especially 6-7am and 4-5pm local time.
- The main Postgres database is 900 GB and grows about 25 GB a month.

## Customers' demands

Our three largest customers are chains with 200 or more locations. Their contracts promise 99.9% monthly uptime for clock-in and give them service credits when we miss it. Two of them have asked for a SOC 2 Type II report before they renew next spring; without it, they will not renew. Several chains want single sign-on through their own identity providers.

Clock-in records feed payroll, so losing a confirmed clock-in is not acceptable: it means someone may be paid wrongly. The rota itself can be rebuilt from the last published version if we must, and an hour of lost draft edits would be annoying but tolerable.

## Data

We hold staff names, phone numbers, emails, availability, hours worked and pay rates. About a third of our customers are in Germany, France and the Netherlands, and their data must stay in the EU under our data processing agreements with them. The rest are in the US and Canada. Location is recorded at clock-in only, to show the employee is on site; we do not track people between clock-ins and we promised customers' works councils that we never will.

## What we want

The CTO's priorities for the next 18 months: reliability of clock-in first; then the ability for three teams to ship independently without stepping on each other; then keeping cloud costs in check, which are now $38,000 a month and rising faster than revenue.

## Open questions

We don't know yet how many of the 40 prospects in the sales pipeline will need EU hosting, or what the auditors will ask us to change for SOC 2.
