You read short web search snippets for a used-car report in India (INR). Copy out every price and label it.
Code decides later which prices to use: you only copy and label, honestly, with your confidence.

You get THE CAR, then groups of search results. Each group header says what it is for:
- [new price]: today's price of a new car of this model (on-road or ex-showroom)
- [listing]: used cars for sale or valuations of this car model
- [part <part> — <issue>, <severity>, <action>]: what repairing or replacing that part costs; the header is the planned job
- [tyre ...]: the price of a tyre for this car
Each result has an id (S1, S2, ...), the site, the title and the snippet in quotes.

Copying (every group)
- Copy prices exactly as written in the snippet into `price_text` (for example "₹4.50 lakh", "Rs. 1,995", "₹ 4,95,000"). Never convert, round, add up or invent a number. A range gives both ends in order.
- One figure per price. A snippet that lists several cars, variants or prices gives one figure per price. In a list of cars, the year, variant and km written right after a price belong to that same car (e.g. "₹ 4,95,000 2019 - 19,000 km" = one 2019 car with 19,000 km); never take them from the previous car.
- Leave out any label the snippet or title does not state for THAT price (no null fields). No notes.

Labels for [new price] and [listing] figures
- `year`, `make`, `model` as written.
- `trim`: the variant name only, in its standard form, the same way every time: no fuel, no transmission (for example "VXi", "ZXi Plus", "Asta", "Sportz"; never "VXi AMT CNG").
- `fuel`: "Petrol", "Diesel", "CNG", "Electric", "Hybrid". `transmission`: "Manual", "AMT", "Automatic", "CVT", "DCT".
- `km` (listings): a number (19,000 km → 19000).
- `type`:
  - [new price]: "on_road", "ex_showroom", "used_value" (a used car price or valuation), "emi_or_loan", "other";
  - [listing]: "single_listing" (one car for sale), "valuation" (a fair-value estimate for this car), "range" (a price band across several cars), "starting_from" ("starts at", "starting price"), "new_price" (on-road or ex-showroom price of a new car), "emi_or_loan", "other".
- `match`, compared with THE CAR:
  - "exact": same make, model and variant (and fuel / transmission when both are known); for [listing] also the same year;
  - "same_model_other_trim": same make and model, another variant (ZXi is not VXi; "VXi CNG" or "VXi AMT" is another variant when THE CAR is a petrol manual VXi);
  - "same_model_other_year" ([listing] only): same make and model, another year (any variant);
  - "same_model_unknown": same make and model, variant not stated ([new price]) or year not stated ([listing]);
  - "other_model": another model (Swift Dzire is not a Swift, Grand i10 Nios is not an i10) or another make;
  - "wrong_kind": not the kind of price the group is for ([new price]: used prices, EMI, discounts, loans; [listing]: new-car prices, EMI, discounts, loans, "price dropped" amounts).

Labels for [part ...] figures
- `part`: the part the price is for, in plain words ("bumper", "side mirror", "windshield", "headlight").
- `position`: "front", "rear", "left", "right", "front left", ... when stated.
- `work`: "buffing" (polish, rubbing, scratch removal by polishing, headlight restoration), "touch_up" (touch-up paint), "scratch_repair", "dent_repair" (denting, including denting and painting of one panel), "repaint" (painting of a panel), "chip_repair" (windshield chip or crack repair), "full_repair_job" (body shop repair of several panels), "new_part" (the price of a new part on its own, OEM or aftermarket), "used_part", "install" (fitting a part), "labour" (a labour charge), "other".
- `new_or_repair`: "new_part" (new_part, used_part), "repair" (buffing, touch_up, scratch_repair, dent_repair, repaint, chip_repair, full_repair_job), "labour" (install, labour).
- `car_specific`: "this_car" (price stated for this make / model), "other_car" (stated for another car), "generic" (no car stated).
- `match`, compared with the group's part and planned job:
  - "exact": same part and position (when both are known), and the work fits the planned job (a repair price for a repair job; a part, fitting or labour price for a replace job);
  - "other_position": same part, another position (front bumper for a rear bumper job);
  - "other_work": same part, but the work does not fit the planned job (a new-part price for a repair job, a repair price for a replace job);
  - "other_part": another part;
  - "not_a_price": not a cost of this kind (the price of the whole car on a spare-parts page, insurance, EMI, DIY kits, unrelated services).

Labels for [tyre ...] figures
- `type`: "tyre_price" (one tyre), "other". `tyre_size` when stated (e.g. "195/55 R16").
- `about`: "this_item" (a tyre for this car), "not_this_item" (another thing).

Every figure
- `reason`: one short line (what matches or what differs).
- `confidence`: an object with your confidence from 0 to 1 for EVERY label you gave: one key per label field.

Return JSON only, no markdown fences:
{
  "figures": [
    { "source": "S12", "price_text": ["₹7.85 lakh"], "make": "Maruti", "model": "Swift", "trim": "VXi", "fuel": "Petrol",
      "transmission": "Manual", "type": "on_road", "match": "exact", "reason": "same model, variant, fuel and transmission",
      "confidence": { "make": 1, "model": 1, "trim": 0.9, "fuel": 0.9, "transmission": 0.85, "type": 0.9, "match": 0.9 } },
    { "source": "S3", "price_text": ["₹ 4,95,000"], "year": 2019, "make": "Maruti", "model": "Swift", "trim": "ZXi",
      "km": 19000, "type": "single_listing", "match": "same_model_other_year", "reason": "2019 ZXi listing",
      "confidence": { "year": 0.95, "make": 1, "model": 1, "trim": 0.85, "km": 0.9, "type": 0.9, "match": 0.9 } },
    { "source": "S25", "price_text": ["₹1,500", "₹2,500"], "part": "bumper", "position": "rear", "work": "buffing",
      "new_or_repair": "repair", "car_specific": "generic", "match": "exact", "reason": "rear bumper scratch rubbing and polish",
      "confidence": { "part": 0.95, "position": 0.8, "work": 0.9, "new_or_repair": 0.95, "car_specific": 0.9, "match": 0.9 } },
    { "source": "S40", "price_text": ["₹4,250"], "type": "tyre_price", "tyre_size": "185/65 R15", "about": "this_item",
      "reason": "one tyre of the car's size", "confidence": { "type": 0.9, "tyre_size": 0.9, "about": 0.9 } }
  ]
}
