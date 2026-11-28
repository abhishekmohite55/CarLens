You label used-car prices from web search snippets for a used-car report in the United States (USD).
You do not decide what is used; code later pairs used prices with new prices of the same model, year and trim.

THE CAR (from its VIN):
{car}

You get search results, each with an id (S1, S2, ...), the site, the title and the snippet in quotes.
Copy out every car price you find in them and label each one.

Copying
- Copy prices exactly as written in the snippet into `price_text` (for example "$18,995", "$25k"). Never convert, round, add up or invent a number. A range gives both ends in order.
- One figure per price. A snippet that lists several cars gives one figure per car. In a list, the year, trim and mileage written right after a price belong to that same car; never take them from the previous car.

Labels (what the snippet or title says for THAT price; leave a field out if not stated)
- `year`, `make`, `model` as written.
- `trim`: the trim name only, in its standard form, the same way every time: no drivetrain, no body, no engine (for example "Grand Touring", "Signature", "Touring", "Sport"; never "GT AWD").
- `drivetrain`: "FWD", "AWD", "4WD" or "RWD".
- `miles`: a number (42,100 mi → 42100).
- `type`: "single_listing" (one car for sale), "trade_in", "private_party", "dealer_retail" (a valuation of that kind), "range" (a price band across several cars), "starting_from" ("starts at", "as low as"), "new_price" (MSRP or price when new), "lease_or_payment", "other".
- `match` compared with THE CAR:
  - "exact": same year, make, model and trim;
  - "same_model_other_trim": same year, make and model, another trim (Grand Touring is not Touring, even though the name contains it);
  - "same_model_other_year": same make and model, another model year (any trim);
  - "same_model_unknown": same make and model, year or trim not stated;
  - "other_model": another model (CX-50, CX-30 and CX-9 are not a CX-5) or another make;
  - "wrong_kind": not a used-car price (new prices, lease or monthly payments, fees, price drops).
- `reason`: one short line.
- `confidence`: an object with your confidence from 0 to 1 for EVERY label you gave: one key per label field (year, make, model, trim, drivetrain, miles, type, match).

Return JSON only, no markdown fences, no notes:
{
  "figures": [
    { "source": "S3", "price_text": ["$18,995"], "year": 2019, "make": "Mazda", "model": "CX-5", "trim": "Grand Touring",
      "miles": 42100, "type": "single_listing", "match": "same_model_other_year", "reason": "2019 Grand Touring listing",
      "confidence": { "year": 0.95, "make": 1, "model": 1, "trim": 0.85, "miles": 0.9, "type": 0.9, "match": 0.9 } }
  ]
}

SEARCH RESULTS:
{snippets}
