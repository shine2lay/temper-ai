# ReadAlong: hosting and data review

ReadAlong is a reading app for primary schools in England. Children aged 6 to 11 read a short book aloud into a tablet; the app listens, highlights words they struggle with, and gives their teacher a weekly report.

## Scale

ReadAlong is used by 1,200 schools and about 140,000 pupils. Reading happens between 9am and 3pm on school days, and most sessions fall between 9am and 11am. Recordings add about 2 TB of new audio a month. We have run for four years and have a support desk and an on-call rota of three engineers.

## What we promised schools

Our contracts with schools, which follow the ICO's Children's Code, say:
- We collect only each pupil's first name, class and reading level, and nothing else about them.
- A pupil's data, recordings included, is deleted within 30 days of the school telling us the pupil has left.
- Recordings are deleted after 90 days.
- All pupil data stays in UK data centres.

These terms are not up for negotiation; schools check them every year.

## The cost pressure

Hosting costs $19,000 a month and is our largest cost after salaries. Our CFO wants it under $12,000. She has proposed moving to a cheaper provider's US region, and she would like to keep reading recordings indefinitely to train our own speech model, which she says would save licence fees later. Neither proposal has been agreed. The board has approved $60,000 for this review and any changes that follow.

## Team

We are nine people, three of them engineers. Our backend is Python on a single cloud provider; we have never run a second region.

## Priorities

Our head of product makes the call on trade-offs. Her order: first, collect even less about children than the contracts require, wherever we can; second, lower hosting costs; third, keep the app working through the morning reading peak.

## What we don't know

Whether parents' consent, given through the schools, would cover using recordings to train a speech model at all. If the app is down during a lesson, teachers lose the session, but we have never agreed a recovery target with schools.
