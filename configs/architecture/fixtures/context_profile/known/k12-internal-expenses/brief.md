# Expenses replacement: brief for the architecture team

Kestrel Engineering has 600 employees across four offices. Staff claim travel and other expenses through ClaimPro, a hosted tool we have used for nine years. ClaimPro's vendor is retiring the product: our licence ends on 31 March and the vendor has refused to extend it. If there is no replacement by then, nobody can be reimbursed, and finance would be back to paper forms and spreadsheets.

We want to build a replacement in-house: employees submit a claim with receipt photos, their manager approves it, finance checks it and the payment goes out with the next payroll.

## Volume

Staff submit about 2,400 claims a month. Around 40% of them arrive in the last three days of the month, because people batch them before the cut-off.

## Systems we must keep

- Approved claims must post to our SAP finance ledger. Finance will not change SAP for this project.
- IT policy requires every internal tool to sign people in through Okta; no separate passwords.

## Data and rules

A claim holds the employee's name, staff number, cost centre, the receipts, and the bank account details we pay into. Tax rules require us to keep receipts and claim records for 7 years. Only the employee, their manager and the finance team may see a claim.

## Team and money

Two developers from internal IT will build it; both work in C# and .NET, and neither has built anything that posts to SAP. A product owner from finance gives it two days a week. The budget is $120,000 to build it. After launch it has to run on our existing Azure subscription, and IT supports it during office hours only.

## What we want

First, finance wants to change approval rules themselves, without asking developers. Second, keep the monthly running cost low. Third, IT should not need to look after it outside office hours.

Later we might add travel booking to the same tool, but that is not part of this project.

## What we don't know

We do not know yet which interface SAP offers for posting claims: whether there is an API we may call, or only a file import that finance runs by hand.
