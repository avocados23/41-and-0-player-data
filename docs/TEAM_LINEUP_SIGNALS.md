# Team Lineup Signals

Team lineup analysis is computed on demand by the Fastify service after a
roster contains five unique players assigned to PG, SG, SF, PF, and C. The
analysis is stateless: simulator evaluations are not written to PostgreSQL.

This repository owns the database schema and the offline player features that
the service consumes. Raw shot events remain here; Fastify reads the derived
shooting ability, zone, and contextual profiles instead of scanning events for
each lineup.

## Version and calibration

The active service model is `lineup-signals-v2`. It retains each underlying raw
metric and provisional score for auditability, then maps the result onto the
simulator-eligible lineup population. The bottom quartile is a weakness, the
middle half is neutral, and the top quartile is a strength. Critical functional
thresholds can still mark spacing, ball movement, or creator coverage as a
weakness when the population itself is weak in that area.

The read-only backend command below samples valid random lineups and prints
minimum, quartile, median, maximum, confidence, and warning-rate summaries. It
does not persist evaluations.

```bash
npm run signals:sample -- --lineups=10000
```

Run the command from the Fastify repository.

## Initial signal catalog

| Category | Signal | Principal inputs |
|---|---|---|
| Shooting | Shooting efficiency | Expected points and season-relative efficiency |
| Shooting | Floor spacing | Three-point threat, volume, and weakest spacers |
| Shooting | Three-level coverage | Rim, jumper, and three-point zone threats |
| Shooting | Shooting stability | Game-level execution volatility, separate from shooting quality |
| Offense | Self-created shooting | Unassisted made jumpers and threes |
| Offense | Ball-handling coverage | Primary and secondary handler production |
| Offense | Rim pressure | Rim attempts and free-throw pressure |
| Offense | Ball movement | Assists and turnovers per 40 |
| Offense | Offensive production | Total PORPAG |
| Offense | Free-throw pressure | Free-throw volume and adjusted accuracy |
| Fit | Off-ball scalability | Spacing, efficiency, assisted scoring, and versatility |
| Fit | Usage compatibility | Shape of the five-player usage hierarchy |
| Rebounding | Offensive rebounding | Offensive rebounds per 40 |
| Rebounding | Defensive rebounding | Defensive rebounds per 40 |
| Rebounding | Team rebounding | Total rebounds per 40 |
| Defense | Defensive impact | Total DPORPAG |
| Defense | Rim protection | Blocks per 40 |
| Defense | Defensive disruption | Steals plus blocks per 40 |

Listed positions validate roster construction but do not earn role-coverage
points. Ball-handling coverage is inferred independently from season-relative
assists per 40, assist-to-turnover ratio, and usage. Offensive production does
not imply handling or observed player synergy.

## Confidence and missing data

Every signal remains in the API response. Signals below the current confidence
floor carry a `LOW_CONFIDENCE` warning; signals missing one or more supporting
player profiles also carry `MISSING_DATA`. Missing event coverage therefore
does not prevent PORPAG, DPORPAG, box-score, or rebounding signals from being
computed.

The eventual frontend presentation will choose up to three qualifying
strengths, two middle-of-the-pack signals, and three qualifying weaknesses.
Until empirical bands are approved, the simulator displays the complete signal
set for calibration and does not force any classification.
