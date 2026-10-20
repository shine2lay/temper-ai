# DockPulse: changing the arrival board

DockPulse shows warehouse dispatchers which trailers have reached a loading door. Twelve warehouses use it daily and pay for it. The number of paying warehouses has tripled in the last year, and another six are contracted to start next quarter. Demand is proven; keeping up with new sites is now stretching both our event processing and our small operations team.

## What exists

The current system is a Go worker with PostgreSQL on a single virtual machine. A browser board polls the worker. It receives gate events from the CourierMesh partner API and weight readings from vendor-owned DockSense scales. Those are outside our product: we cannot change their software. Dispatchers compare the arrival board with the driver's paperwork before assigning a door.

Normal traffic is 120 events per second. At shift change it peaks at 400 events per second for ten minutes. Our signed warehouse contracts require the board API's p95 response time to stay below 250 milliseconds, the displayed gate status to be at most 3 seconds behind receipt of an event, and sustained ingestion of 400 events per second during that burst. These are acceptance conditions, not aspirations. A supplier slide claims its service handles 20,000 events per second; that is not our traffic or a requirement for this change.

## Promises and people

The contracts require 99.9% monthly availability. An event we have acknowledged must never be lost. After a failure, service must recover within 30 minutes. We retain gate records for 30 days, then delete them. They contain driver badge identifiers and carrier references, not names or addresses. No records leave the dispatch operation.

Six engineers know Go and PostgreSQL. Two rotate on the overnight pager. We have $80,000 to change the system and a $2,200 monthly hosting cap. Operations must keep the existing scanner certificates valid through the migration; replacing every device credential is not acceptable.

## Trade-offs and open points

Our engineering director decides. First, make the board fast enough for dispatchers; second, use less compute per event; third, make adding a partner less work. Meeting the contractual floors does not settle which option is best above them.

We have not established whether CourierMesh retries can arrive out of order. That changes deduplication and buffering. Sales hopes to add a RailVista integration later, but no customer has agreed to it and it is outside this project.
