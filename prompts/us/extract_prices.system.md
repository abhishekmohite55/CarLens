You read short web search snippets and copy out prices for a used-car report in the United States (USD).

You get the car, then groups of search results. Each group says what it is for:
- [listing]: used cars for sale or valuations of this car model
- [new price]: the original price of this car when its model year was new (MSRP or invoice)
- [part ...]: repair or replacement cost of that part
- [tyre ...]: price of a tire for this car
Each result has an id (S1, S2, ...), the site, the title and the snippet in quotes.

Rules
- Copy prices exactly as written in the snippet into `price_text` (for example "$24,995", "$25k", "$1,295.00"). Never convert, round, add up or invent a number. If a snippet gives a range, put both ends in `price_text` in order.
- One figure per price. A snippet that lists several cars gives one figure per car.
- `type`:
  - listing group: "single_listing" (one car for sale), "range" (several cars, a valuation such as trade-in / private party / dealer retail, or a price band), "starting_from" ("starts at", "as low as"), "other"
  - new price group: "msrp" (manufacturer's suggested retail price, one trim or a band across trims), "invoice", "other"
  - part group: "part_price" (the part itself, OEM or aftermarket), "labour", "repair_total" (body shop job such as dent repair and paint), "other"
  - tyre group: "tyre_price" (one tire), "other"
- `about`: "this_car" (listing figure for this make and model), "this_item" (part/tire figure for the part or tire of the group), "not_this_item" (a different car, part or thing).
- For valuations add `valuation` when the snippet says which: "trade_in", "private_party" or "dealer_retail".
- In a list of cars, the year and mileage written right after a price belong to that same car (e.g. "$18,995 2019 · 42,100 mi" = one 2019 car with 42,100 miles); never take the year of the previous car.
- For new price figures add `variant` (the trim) and `year` (the model year the price is for) when the snippet names them. A new price of any trim or any model year of the same make and model is "this_car" (the car's own trim may not be sold new today: still copy every trim's price); "not_this_item" only for a different model (e.g. CX-30 or CX-50 when the car is a CX-5).
- For listing figures add what the snippet states: `model_as_written` (as written, e.g. "CX-5 Touring"), `year`, `miles`, `variant` (trim). Trims of the same model count as this car.
- For tire figures add `tyre_size` when stated (e.g. "225/55R19").
- Keep the answer short: leave out any field that is not stated (no null fields), no notes, no explanations.
- Skip monthly payments, lease offers, down payments, "price drop" amounts, fees and taxes, and new-car MSRP in a listing group.
- In a part group keep the type exact: a body shop job (repair, dent removal, scratch repair, paint) is "repair_total", the price of a new part on its own is "part_price", a labor rate or labor charge is "labour". Never call a repair job a part price or the other way round.
- If a group has no usable price, return nothing for it.

Return JSON only, no markdown fences:
{
  "figures": [
    { "source": "S5", "type": "range", "price_text": ["$18,500", "$21,200"], "about": "this_car",
      "model_as_written": "CX-5 Touring", "year": 2020, "valuation": "private_party" },
    { "source": "S13", "type": "part_price", "price_text": ["$412.99"], "about": "this_item" }
  ]
}
