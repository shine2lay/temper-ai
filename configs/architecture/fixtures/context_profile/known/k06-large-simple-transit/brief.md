# NextStop: notes for the architecture review

NextStop is a phone app that shows bus and tram departures for three cities: Riverton, Calder and Moorfield. You open it, it shows the stops near you and when the next vehicles leave, including live delays. That is almost all it does.

## Usage

We have run NextStop for six years. It has 1.1 million monthly users and about 180,000 daily users, and these numbers have been flat for two years. Almost everything is reading: departure times and delays come from the transit agencies' open data feeds, which our backend polls every 30 seconds and caches. Users do not sign in. Favourite stops are stored on the phone, not on our servers.

Traffic follows the commute. On weekdays between 7am and 9am, and again between 4pm and 7pm, requests run at about 5 times the daily average. On snow days we have seen 10 times the average for a whole morning.

Some people call us a large-scale platform because of the user count. We are not: the backend is two small services and a cache, and it is boring on purpose.

## Team and money

NextStop is run by the two of us, Ines and Rafael. Ines writes the Swift and Kotlin apps; Rafael writes the Go backend and looks after the servers. We also run a consulting business, so NextStop gets about one day a week from each of us. We are not on call; if something breaks at night, it waits until morning.

Ads bring in about $9,000 a month. Hosting costs $2,300 a month, mostly the cache and bandwidth, and we would like to bring that down. We can put $30,000 into this rework, and not more this year.

## Reliability

During rush hour the app has to work: an outage at 8am means thousands of one-star reviews and angry emails to the agencies. At 2am nobody notices. There is no user data to lose; everything we show can be fetched again from the feeds.

Our agreement with the Riverton transit agency requires us to show its service alerts within 2 minutes of publication. Calder and Moorfield have no such terms.

## Privacy

We collect no names, emails or accounts. The app uses the phone's location to find nearby stops, and the location never leaves the phone; we say so in our privacy policy and we intend to keep that promise. We keep anonymous usage counts for 90 days. Our ad network receives the device's advertising identifier.

## What we want

First, rush hour must hold up. Second, lower hosting costs. Third, less of our scarce time spent on maintenance.

## What we don't know

Ashford's transit agency has invited us to add their city next year, which they say would bring about 400,000 more monthly users. We have not seen their feed yet and do not know whether it allows polling every 30 seconds.
