"""VIN lookup (stage U1, docs/backend/07-us-market.md §4). Everything VIN-specific sits in this package: nothing
outside app/vin/ knows a provider's field names. A new VIN service = one file in providers/ + a config entry."""
