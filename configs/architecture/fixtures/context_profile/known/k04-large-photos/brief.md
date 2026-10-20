To: Architecture review
From: VP Platform, Glimmer
Re: Context for the media pipeline redesign

Glimmer is a photo and short-video sharing app. It is ten years old and is one of the larger consumer apps in its category: 31 million monthly active users, 9 million of them daily, across Europe, North America and Brazil. Users upload about 40 million photos and 6 million short videos a day, and the app serves roughly 1.5 billion media views a day. On New Year's Eve and during big football finals, uploads run at about 4 times the normal rate for several hours.

Engineering has 420 people in 38 teams. A central platform group of 60 runs the infrastructure across three cloud regions (Frankfurt, Virginia and São Paulo), with a 24/7 on-call rotation and a mature incident process. The media pipeline (upload, transcoding, storage, delivery) is owned by two of those teams.

Reliability: our public status page commits to 99.95% availability for viewing and 99.9% for uploading. A photo a user has uploaded and seen confirmed must never be lost. After a regional outage, viewing must be back within 15 minutes; uploads may take up to an hour.

Privacy and law: we hold users' photos, videos, profile data, contacts they choose to sync, and coarse location tags. Users must be 16 or older; we do not knowingly serve children, and we must delete an account's media within 30 days of a deletion request. EU users' data is processed under GDPR, and Brazilian users' data under LGPD; the Brazilian data protection authority has asked us to keep Brazilian users' media in Brazil, and our legal team has agreed to do so by the end of next year. We are also in scope of the EU Digital Services Act for content moderation.

Security: account takeovers are our most common serious incident, about 1,200 confirmed cases last year, mostly through reused passwords. We have a bug bounty and a yearly external penetration test.

Money: the media pipeline costs about $4.2M a month to run, mostly storage and delivery. Finance has asked for a 20% cut within the next year. There is no fixed limit on the redesign project itself, but it competes with other work for engineers.

Priorities from the leadership team: protect reliability and user trust first; then cut the pipeline's cost; then make it cheaper for teams to add new media formats. Speed of delivery matters less than doing this safely.

What we don't know: how much of the stored media is ever viewed again after its first year, which decides how much we can move to colder storage; and whether the Brazilian residency rule will extend to backups.
