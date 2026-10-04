# Product-dependence survey (Sean Ellis question, as Superhuman ran it)

Template for the survey indicator of the fit and revenue kit (`pmf_kit.py`, data dictionary in
this folder). The kit never sends it: sending a survey means contacting people, which needs the
owner's approval, an opt-in channel and an honest description of who is asking and why.

Source: Rahul Vohra, "How Superhuman Built an Engine to Find Product/Market Fit", First Round
Review. Superhuman asked users who had recently experienced the core of the product ("at least
twice in the last two weeks", Sean Ellis's recommendation) and measured the share answering
"very disappointed"; Ellis found 40% to be the mark after benchmarking nearly a hundred
startups, results become directionally correct around 40 respondents, and nobody was surveyed
more than once.

## Who to ask

Only users who did the product's core value event (`value_event`) at least
`survey.min_value_events` times in the `survey.lookback_days` days before you send it: the same
rule the kit uses to decide who counts. Ask each person once. Do not ask people who have stopped
using the product; the kit would count them as not eligible anyway.

## The four questions

Replace `[product]` with the product's name.

1. **How would you feel if you could no longer use [product]?**
   - Very disappointed
   - Somewhat disappointed
   - Not disappointed
2. What type of people do you think would most benefit from [product]?
3. What is the main benefit you receive from [product]?
4. How can we improve [product] for you?

Question 1 is the measured one; offer exactly these three answers. Questions 2-4 are free text
for the team to read (who the product is really for, what to keep, what to fix). The kit does
not read them, and they must not be put in `survey.csv`.

## Exporting the answers to `survey.csv`

One row per answer to question 1, with a pseudonymous user id that matches `users.csv` (no
names or emails):

```
response_id,user_id,submitted_on,answer
r001,u01,2026-03-20,very_disappointed
r002,u02,2026-03-20,somewhat_disappointed
r003,u03,2026-03-21,not_disappointed
```

`submitted_on` is the answer day (`YYYY-MM-DD`). If someone answered twice, keep both rows: the
kit counts the first and reports the rest as repeats. Skipped or unclear answers are better left
out than guessed.

## Reading the result

The kit reports the share of eligible respondents answering "very disappointed", its 95%
interval and the denominators. 40% or more with enough eligible respondents meets the survey
indicator. It does not show product-market fit on its own: retention and payment at the target
price must be met as well.
