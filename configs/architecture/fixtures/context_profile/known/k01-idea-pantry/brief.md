# Pantry Pal: founder notes for the architecture chat

We are two founders, Maya Okafor and Luis Brandt, and Pantry Pal is still an idea. Nothing is built yet. We have a landing page and a waitlist with 340 email sign-ups, and we have run 18 interviews with home cooks who throw away too much food.

## What we want to build

A phone app that keeps track of what is in your kitchen and suggests meals that use up food before it spoils. You scan a grocery receipt, the app lists the items with rough expiry dates, and every evening it suggests two or three recipes. Later we might add a shared household list, but not for the first version.

## Where we are

- Maya is a product designer; Luis is a backend developer who has built two small Django apps. Neither of us has run anything in production with real users at night.
- We both work on this part-time, about 15 hours a week each, next to our day jobs.
- We are paying for everything from our savings: $12,000 in total for the first year, everything included.
- We would like hosting to stay under $150 a month until we know people want this.

## What we know about users

Nothing yet beyond the interviews. Our hope is 2,000 people in the beta and 10,000 users by the end of next year, but these are guesses. For comparison, the big player in this space, FridgeFriend, says it serves 2 million households; we are nowhere near that and do not expect to be.

## Data

Users sign in with email. We store the food they buy and the meals they cook. Some testers asked us to record food allergies so recipes can avoid them. We have not decided whether to store allergies, because we are not sure what that means legally. Receipt photos should be deleted once the items are read; we promised this on the landing page.

## What matters to us

Above all, we need to learn quickly whether people use it, so getting a beta out fast is the first thing. Keeping costs low comes right after that. We do not want to spend nights fixing servers, so anything we run should be simple to operate. We will need to change things often after the beta, so the design should be easy to change.

## Open points

We have not picked a country to launch in, though Luis lives in Germany and Maya in Canada. We do not know yet how many receipts a typical user would scan per week.
