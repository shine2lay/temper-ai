# Quietnote: brief for the architecture review

Quietnote is a note-taking and scheduling app for therapists in private practice. A therapist books sessions, writes a progress note after each one, signs it, and later exports notes for insurance claims.

## Where we are

We launched a paid pilot six months ago. Today 60 therapists pay us $45 a month each, all in the United States, and together they write about 2,400 session notes a month. Most notes are written between 5pm and 8pm on weekdays, after the last session of the day.

We are three people: Priya, a licensed psychologist and our CEO; Tomás, who writes most of the code (TypeScript and Postgres); and Ana, a part-time developer who works two days a week. Nobody on the team has been through a security audit before, and nobody wants to carry a pager at night.

## The rules we live under

Session notes are protected health information. We must comply with HIPAA, and every vendor that stores or processes notes must sign a business associate agreement with us. This is not negotiable: a breach would end the company and could cost our therapists their licences. Therapists must use multi-factor authentication to sign in; our pilot contract already promises it. State rules require that signed notes are kept for at least seven years, and a signed note may never be edited, only amended.

A therapist must never lose a signed note. If the app is down for an hour during the day, that is unpleasant but therapists can wait; a full day would not be.

## Money

We raised $600,000 last spring and want it to last at least 18 months. Hosting and tools cost $1,100 a month today. One of our investors keeps pushing us to move to a cheaper hosting provider that will not sign a business associate agreement, to save about $400 a month. We are not doing that.

## What we want, in order

1. Protecting clients' notes comes first. We would like to go beyond the HIPAA minimum where it is cheap to do so, for example by encrypting each practice's notes with its own key.
2. Then keeping our burn low.
3. Then shipping insurance claim export before the end of March, because therapists keep asking for it.

## Not decided

Several therapists asked to record sessions as audio and get draft notes from the recording. We have not decided whether to offer it; it would mean storing recordings of therapy sessions.

Two group practices in California have approached us. We do not know whether taking them on brings extra state rules beyond HIPAA.
