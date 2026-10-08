# Occupied Room UI Design

**Stage:** Requirements and UI design only  
**Baseline:** Current main branch, including Checkout Room and room-status filtering  
**Status:** Ready for implementation; this document changes no application code.

## 1. Current behavior and problem

The room_management.html template renders each room as a visible card with a class based on room.state and explicit room.status text. The action area currently renders the available-room rent action, or the occupied-room rental-edit and checkout actions, followed by shared normal edit and delete controls. An occupied room with an active rental can therefore show four actions: “Tùy chọn cho thuê”, “Trả phòng”, “Cập nhật”, and “Xóa phòng”. The rental edit and checkout controls currently span full rows, increasing card height.

The existing hotel.css already defines a two-column room-actions grid, with the delete form spanning both columns. Occupied cards have a pink/red background and red border, but their image is not desaturated. The room grid is four columns by default, two columns at 1180px, and one column at 520px. Both occupied controls currently span both action columns.

The template context already provides active_room_rentals keyed by room id. The checkout route is POST /rooms/<room_number>/checkout, uses the existing CSRF token, changes the room status/state to available/empty, clears check-in/check-out, commits, and redirects to /rooms. That redirect already re-renders the card using the available state. The rent route rejects occupied rooms and the delete route rejects occupied rooms. The normal room edit route currently accepts direct GET/POST requests for occupied rooms; hiding its card link is a UI restriction, not a server-side access guard.

## 2. Final action rules

For a room whose status/state pair is “Phòng trống”/empty, render exactly these three actions inside the card:

1. Cho thuê
2. Cập nhật
3. Xóa phòng

Keep the current grid layout: Cho thuê and Cập nhật on the first row; Xóa phòng spans the second row.

For a consistently occupied room with an active rental in active_room_rentals, render exactly these two actions:

1. Điều chỉnh thuê — existing rental-edit route and behavior.
2. Trả phòng — existing CSRF-protected POST form and checkout route.

Do not render Cho thuê, normal Cập nhật, or Xóa phòng for an occupied card. Rename only the visible rental-edit label from “Tùy chọn cho thuê” to “Điều chỉnh thuê”. Keep its route and behavior unchanged. Place both occupied actions side by side in the existing two-column action grid.

Use conditional Jinja rendering so unavailable actions are absent from the card HTML. Do not render fake disabled controls. Do not apply pointer-events: none to the whole card; both allowed rental actions must remain clickable.

For inconsistent status/state values, fail closed for ordinary room-management actions. Treat either occupied indicator as unavailable. Render the two rental actions only when the status/state pair is consistently occupied and there is a current rental record. If an occupied room has no current rental, keep the card and status visible but do not render a dead rental-edit link or an unrelated normal-management action. Do not fabricate a rental record.

## 3. Jinja strategy

Keep using the current active_room_rentals context in the room card:

- Available pair (status “Phòng trống” and state empty): render the current rent trigger, normal edit link, and delete form.
- Occupied pair with a current rental: render the rental-edit link and checkout form only.
- Occupied or inconsistent state without a current rental: do not fall through to available-only actions.

Keep the card, room image/details, explicit status text, and accessible room label visible. Reuse room-card--occupied for a consistent occupied room; derive the occupied visual treatment safely so inconsistent occupied indicators do not look available.

## 4. CSS and responsive behavior

Reuse the existing card and action grid. Keep the current occupied red/pink status treatment and add a restrained unavailable appearance, such as slight dimming and partial grayscale/desaturation on the room image. Preserve readable text and a clear occupied status; avoid fading the entire card enough to reduce contrast. No animation or JavaScript is needed.

Add an occupied modifier to the action area, for example room-actions--occupied. Override the current full-row spans so the rental-edit link and checkout form each occupy one grid column. Keep minmax(0, 1fr) sizing and controls within their columns. Allow the labels to wrap and center at narrow widths instead of using fixed widths. Check the existing medium two-column and narrow single-column card breakpoints for overflow and overlap.

Do not rely only on color or grayscale to indicate occupancy; retain the visible “Đang thuê” status text. Do not dim the status label so much that it becomes hard to read.

## 5. Checkout and rental behavior

Do not change checkout backend logic, the RoomRental schema, pricing, time calculations, or the rental-edit route. Preserve the checkout form method=post, csrf_token(), and existing confirmation behavior. On successful checkout, the existing redirect to /rooms re-renders the now available room and naturally restores Cho thuê, Cập nhật, and Xóa phòng.

The normal edit route currently permits direct requests for an occupied room. This design keeps the requested UI scope and does not propose an app.py change. If the teacher expects the no-edit business rule to resist manually constructed requests too, a server-side guard must be considered separately; hiding the card link alone is not authorization.

## 6. Expected implementation files

- src/hotel_app/templates/room_management.html — state-specific action rendering and label update.
- src/hotel_app/static/css/hotel.css — occupied appearance and side-by-side occupied actions with wrapping.
- tests/test_room_types.py — action markup, occupied class, status filtering and counts.
- tests/test_room_rentals.py — checkout POST/CSRF lifecycle, post-checkout actions, and rental edit regression.

No app.py, model/schema, room/rental business logic, OTP/Brevo, global navigation, or dependency change is expected.

## 7. Test design

For an available room card, assert exactly the Cho thuê, Cập nhật, and Xóa phòng action controls and no Trả phòng control. For an occupied room with a persisted current rental, assert the card remains visible, has the occupied/locked class, includes Điều chỉnh thuê and Trả phòng, and has no rent, normal edit, or delete control. Count controls inside the individual room article so the page-level dialogs do not affect assertions.

Also cover:

- occupied controls use two grid columns, do not inherit full-row spans, and have no fixed widths or pointer-events disabling the card;
- checkout remains POST with a CSRF token and rejects missing/invalid CSRF;
- successful checkout makes the room available/empty, clears its displayed stay times, redirects through /rooms, and restores all three available actions;
- rental adjustment still targets the current rental and its current GET/POST behavior and pricing remain unchanged;
- occupied state with no rental row does not render a dead edit link or available-only actions;
- room-status filtering/counts, available rent flow, available edit/delete, and existing room/rental tests remain unchanged.

## 8. Regression risks and design gate

- Checking only status or only state can expose incorrect actions when the stored values disagree; use explicit pair checks and fail closed for normal actions.
- Leaving existing full-row CSS spans in place will stack the occupied actions and preserve the tall card.
- Too much dimming can reduce status readability; keep the text and contrast clear.
- Checkout must remain POST + CSRF and use its existing redirect.
- An occupied room with no rental row is inconsistent; do not invent a rental edit target.
- Hiding the normal edit action is UI-only because the current direct edit route has no occupied-room guard.

No checkout, filtering, status-count, rental-data, authentication, OTP/Brevo, or unrelated behavior changes are part of this design.

**CURRENT_FEATURE_REGRESSION: NO** — no implementation files were changed.  
**OCCUPIED_ROOM_UI_DESIGN_STATUS: PASS**  
**IMPLEMENTATION_READY: YES**  
**NEXT_ACTION: Implement Occupied Room UI**
