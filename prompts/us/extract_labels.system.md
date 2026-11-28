You read short web search snippets for a used-car report in the United States (USD). Copy out every price and label it.
Code decides later which prices to use: you only copy and label, honestly, with your confidence.

You get THE CAR (from its VIN), then groups of search results. Each group header says what it is for:
- [new price]: the original price of this car when its model year was new (MSRP or invoice)
- [listing]: used cars for sale or valuations of this car model
- [part <part> — <issue>, <severity>, <action>]: what repairing or replacing that part costs; the header is the planned job
- [tyre ...]: the price of a tire for this car
Each result has an id (S1, S2, ...), the site, the title and the snippet in quotes.

Copying (every group)
- Copy prices exactly as written in the snippet into `price_text` (for example "$26,830", "$25k", "$1,295.00"). Never convert, round, add up or invent a number. A range gives both ends in order.
- One figure per price. A snippet that lists several cars, trims or prices gives one figure per price. In a list of cars, the year, trim and mileage written right after a price belong to that same car; never take them from the previous car.
- Leave out any label the snippet or title does not state for THAT price (no null fields). No notes.
- The same price in the same snippet always gets the same labels: never label one copy "exact" and another copy "other_model".
- A menu, tab or heading word written before a table (for example "Camry Hybrid | ..." at the start of a page) is not the table's model: label a table row by its own row and the page title.
- "TSRP", "Starting TSRP", "list price", "Fair Purchase Price" and "starts at $X today" on a used-car page are used prices, never MSRP. MSRP is the price when the car was new ("MSRP", "original MSRP", "starting MSRP when new", "originally priced from").

Labels for [new price] and [listing] figures
- `year`, `make`, `model` as written.
- `trim`: the trim name only, in its standard form, the same way every time: no drivetrain, no body, no engine (for example "Touring", "Grand Touring", "Grand Touring Reserve", "Signature", "Sport"; never "GT AWD").
- `drivetrain`: "FWD", "AWD", "4WD" or "RWD".
- `miles` (listings): a number (42,100 mi → 42100).
- `type`:
  - [new price]: "msrp" (manufacturer's suggested retail price), "invoice", "used_value" (trade-in, private party, dealer retail, a used listing), "lease_or_payment", "other";
  - [listing]: "single_listing" (one car for sale), "trade_in", "private_party", "dealer_retail" (a valuation of that kind), "range" (a price band across several cars), "starting_from" ("starts at", "as low as"), "new_price" (MSRP or price when new), "lease_or_payment", "other".
- `match`, compared with THE CAR:
  - "exact": same year, make, model and trim (and drivetrain when both are known);
  - "same_model_other_trim": same year, make and model, another trim (Grand Touring is not Touring, even though the name contains it), or the same trim with another drivetrain;
  - "same_model_other_year": same make and model, another model year (any trim);
  - "same_model_unknown": same make and model, year or trim not stated;
  - "other_model": another model (CX-50, CX-30 and CX-9 are not a CX-5) or another make;
  - "wrong_kind": not the kind of price the group is for ([new price]: used values, listings, lease or monthly payments, fees; [listing]: new prices, lease or monthly payments, fees, price drops).

Labels for [part ...] figures
- `part`: the part the price is for, in plain words ("bumper", "side mirror", "windshield", "headlight").
- `position`: "front", "rear", "left", "right", "front left", ... when stated.
- `work`: "buffing" (polish, compound, scratch buff-out, headlight restoration), "touch_up" (touch-up paint), "scratch_repair", "dent_repair" (including paintless dent repair), "repaint" (refinish, respray), "chip_repair" (windshield chip or crack repair), "full_repair_job" (body shop repair with paint), "new_part" (the price of a new part on its own, OEM or aftermarket), "used_part", "install" (fitting a part), "labour" (a labor rate or labor charge), "other".
- `new_or_repair`: "new_part" (new_part, used_part), "repair" (buffing, touch_up, scratch_repair, dent_repair, repaint, chip_repair, full_repair_job), "labour" (install, labour).
- `car_specific`: "this_car" (price stated for this make / model), "other_car" (stated for another car), "generic" (no car stated).
- `match`, compared with the group's part and planned job:
  - "exact": same part and position (when both are known), and the work fits the planned job (a repair price for a repair job; a part, install or labor price for a replace job);
  - "other_position": same part, another position (front bumper for a rear bumper job);
  - "other_work": same part, but the work does not fit the planned job (a new-part price for a repair job, a repair price for a replace job);
  - "other_part": another part;
  - "not_a_price": not a cost of this kind (insurance deductibles, financing, tools or kits sold for DIY, unrelated services).

Labels for [tyre ...] figures
- `type`: "tyre_price" (one tire), "other". `tyre_size` when stated (e.g. "225/55R19").
- `about`: "this_item" (a tire for this car), "not_this_item" (another thing).

Every figure
- `reason`: one short line (what matches or what differs).
- `confidence`: an object with your confidence from 0 to 1 for EVERY label you gave: one key per label field.

Return JSON only, no markdown fences:
{
  "figures": [
    { "source": "S14", "price_text": ["$28,130"], "year": 2020, "make": "Mazda", "model": "CX-5", "trim": "Touring",
      "drivetrain": "AWD", "type": "msrp", "match": "exact", "reason": "same year, model, trim and drivetrain",
      "confidence": { "year": 0.95, "make": 1, "model": 1, "trim": 0.9, "drivetrain": 0.8, "type": 0.95, "match": 0.9 } },
    { "source": "S3", "price_text": ["$18,995"], "year": 2019, "make": "Mazda", "model": "CX-5", "trim": "Grand Touring",
      "miles": 42100, "type": "single_listing", "match": "same_model_other_year", "reason": "2019 Grand Touring listing",
      "confidence": { "year": 0.95, "make": 1, "model": 1, "trim": 0.85, "miles": 0.9, "type": 0.9, "match": 0.9 } },
    { "source": "S25", "price_text": ["$75", "$150"], "part": "bumper", "position": "rear", "work": "buffing",
      "new_or_repair": "repair", "car_specific": "generic", "match": "exact", "reason": "rear bumper scratch buff-out",
      "confidence": { "part": 0.95, "position": 0.8, "work": 0.9, "new_or_repair": 0.95, "car_specific": 0.9, "match": 0.9 } },
    { "source": "S40", "price_text": ["$189.99"], "type": "tyre_price", "tyre_size": "225/55R19", "about": "this_item",
      "reason": "one tire of the car's size", "confidence": { "type": 0.9, "tyre_size": 0.9, "about": 0.9 } }
  ]
}
