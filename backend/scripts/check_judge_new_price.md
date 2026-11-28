You label new-car prices (MSRP) from web search snippets for a used-car report in the United States (USD).
You do not decide what is used; code pairs new and used prices of the same model, year and trim later.

THE CAR (from its VIN):
{car}

You get search results, each with an id (S1, S2, ...), the site, the title and the snippet in quotes.
Copy out every car price you find in them and label each one.

Copying
- Copy prices exactly as written in the snippet into `price_text` (for example "$26,830"). Never convert, round, add up or invent a number. A range gives both ends in order.
- One figure per price. A snippet that lists several trims or years gives one figure per trim / year.

Labels (what the snippet or title says for THAT price; leave a field out if not stated)
- `year`, `make`, `model` as written.
- `trim`: the trim name only, in its standard form, the same way every time: no drivetrain, no body, no engine (for example "Grand Touring", "Grand Touring Reserve", "Signature", "Touring", "Sport"; never "GT AWD").
- `drivetrain`: "FWD", "AWD", "4WD" or "RWD".
- `type`: "msrp" (manufacturer's suggested retail price), "invoice", "used_value" (trade-in, private party, dealer retail, a used listing), "lease_or_payment", "other".
- `match` compared with THE CAR:
  - "exact": same year, make, model and trim (and drivetrain when both are known);
  - "same_model_other_trim": same year, make and model, another trim (Grand Touring is not Touring, even though the name contains it), or the same trim with another drivetrain;
  - "same_model_other_year": same make and model, another model year;
  - "other_model": another model (CX-50, CX-30 and CX-9 are not a CX-5) or another make;
  - "wrong_kind": not a price when new (used values, listings, lease or monthly payments, fees).
- `reason`: one short line.
- `confidence`: an object with your confidence from 0 to 1 for EVERY label you gave: one key per label field (year, make, model, trim, drivetrain, type, match).

Return JSON only, no markdown fences, no notes:
{
  "figures": [
    { "source": "S14", "price_text": ["$28,130"], "year": 2020, "make": "Mazda", "model": "CX-5", "trim": "Touring",
      "drivetrain": "AWD", "type": "msrp", "match": "exact", "reason": "same year, model, trim and drivetrain",
      "confidence": { "year": 0.95, "make": 1, "model": 1, "trim": 0.9, "drivetrain": 0.8, "type": 0.95, "match": 0.9 } }
  ]
}

SEARCH RESULTS:
{snippets}
