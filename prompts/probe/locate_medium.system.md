Find timestamps in this used-car walkaround video.

Items: plate, model_badge (model text on the body), odometer (km reading), damage (each dent, scratch, crack or broken part), mirror, tyre, windshield.
For each item you can see, give the second where it is clearest. Skip anything not visible.

Reply with JSON only, in this shape:
{"items":[{"id":"L1","category":"damage","label":"dent on left front door","side":"left","t":75.0}],
 "coverage":{"front":true,"rear":true,"left":true,"right":false,"roof":false,"interior":true}}

side is one of: front, rear, left, right, roof, interior. label is at most 8 words.
