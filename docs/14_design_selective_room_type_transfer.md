# Selective Room-Type Transfer Design

## Status and scope

**SELECTIVE_ROOM_TYPE_TRANSFER_DESIGN_STATUS: PASS**  
**IMPLEMENTATION_READY: YES**

This is a requirements and design document only. The current destructive all-room behavior is not changed in this stage. No application, test, schema, or other documentation file is modified.

## Current behavior and data model

The Room Type edit dialog combines source-name editing with an optional target selector. When a target is selected, `edit_room_type` currently moves every room returned by `rooms_using_room_type(source.name)` to the target. If the source name is also changed in that submission, all originally associated rooms are transferred to the target while only the `RoomType` catalog record is renamed. That leaves no source rooms to rename, but prevents choosing a subset.

The separate `POST /room-types/<id>/transfer` endpoint also transfers every matching source room. The current `room_types.html` has no form or action that calls this endpoint; the existing tests do call it directly. Both routes use CSRF protection and commit the room changes together. Existing rollback tests cover a failed commit.

`Room.type` is a text column, not a `RoomType` foreign key. `RoomType` has a unique name and catalog fields. `RoomRental` records room ID/number and rental time and price snapshots. `rooms_using_room_type(name)` currently matches `(room.type or "").strip().casefold()` against the similarly normalized source name. Preserve this matching rule. The current delete route rejects deletion while any normalized matching rooms remain.

## Requirements and operation semantics

Renaming the source catalog entry and transferring selected rooms are independent operations and may be submitted separately or together. Selection is based on current source rooms resolved by the normalized helper.

| Submitted operation | Selected rooms | Remaining source rooms | RoomType source record |
| --- | --- | --- | --- |
| Rename only | None | Every source room gets the new source name | Renamed |
| Transfer only | Selected rooms get target name | Unselected rooms keep their source type text | Unchanged |
| Rename and transfer | Selected rooms get target name | Unselected rooms get the new source name | Renamed |
| No rename, no selected room | None | Unchanged | Unchanged; show no-change feedback |

If zero rooms are selected, no transfer occurs and a target is not required. If the target field contains an old selection while the count is zero, treat it as irrelevant and do not transfer. This permits rename-only submissions. If one or more IDs are selected, the target is required, must resolve to an existing RoomType, and must differ from the source. Selecting every room is allowed but remains an explicit selection.

For the approved combined example, source `Phòng đơn` renamed to `Phòng Standard`, selected rooms `101` and `103` move to `Phòng đôi`; every unselected source room is relabeled `Phòng Standard`; the RoomType catalog row becomes `Phòng Standard`. Selected rooms always take the target name, regardless of the simultaneous source rename.

## UI and payload

Keep the current Update Room Type modal and its form/submit flow. Rename the transfer section heading to **Chuyển phòng sang thể loại khác**. On opening the modal, render the current source name and count, then a selectable row for each matching room, including occupied rooms. Each checkbox uses `name="selected_room_ids"` and the database `Room.id` as its value; room number is display-only. Show the stored status text beside each number. Sort rows consistently by room number (case-insensitive), then ID as a tie-breaker.

Add a nameless **Chọn tất cả** convenience checkbox. It checks or clears the source-room checkboxes, reflects manual changes, and becomes indeterminate when only part of the list is checked. A live accessible summary reads **Đã chọn X / Y phòng**. This summary and Select All are presentation state only; the backend calculates from submitted IDs and source rows.

Keep the target selector, but enable it only when at least one room is selected and there is at least one possible destination. Exclude the source from target options. With no source rooms, show **Không có phòng để chuyển.** and disable Select All and target selection; the name field and rename action remain available. With source rooms but zero currently selected, keep target optional/disabled until the user selects at least one.

If any selected room is occupied (existing definition: status `Đang thuê` or state `occupied`), show a textual warning: **Phòng đang thuê sẽ chỉ thay đổi thể loại; trạng thái và thông tin thuê được giữ nguyên.** Do not communicate the warning by color alone. Update the submit confirmation to name the selected count, source and target; use “toàn bộ” only when all source rooms are actually selected. Append the occupied-room preservation warning when applicable. If the same submission also renames the source, say that the remaining rooms and source type will take the new name. Rename-only submissions do not ask for a transfer confirmation.

The form continues to POST to the existing `edit_room_type` URL with CSRF, `name`, optional `target_room_type_id`, and zero or more repeated `selected_room_ids` fields. No room number is used as an authoritative identifier. Provide source room data in the page/modal context for rendering; it is not trusted as authorization.

## Server-side validation

For every POST, resolve the source RoomType and the server-side normalized set of current source rooms. Read `request.form.getlist("selected_room_ids")`. Parse every submitted value as a positive integer. Reject the whole operation if a value is malformed, refers to no Room, or is not in the resolved source-room set. Never partially apply valid IDs while ignoring an invalid or foreign-room ID. This also rejects stale selections if a room no longer belongs to the source.

Deduplicate repeated IDs before processing so an accidental repeated checkbox value cannot process a room twice. The authoritative selected-room list is derived by filtering the resolved source-room objects by the validated ID set, not by trusting posted counts, room numbers, or client-provided source lists.

Validate a target only when the deduplicated selection is nonempty. It must parse as an existing RoomType ID and differ from the source. Empty selection does not require a target. Preserve current source-name trimming, length checks and case-insensitive uniqueness behavior. Validation errors keep the modal open, preserve submitted name/selection/target for correction where safe, and do not mutate records.

## Deterministic atomic transaction

Use one shared selective-transfer validation/selection helper for the unified edit route and compatibility transfer route. Resolve, validate, and compute all sets before mutation. Then, in one SQLAlchemy transaction:

1. Resolve source RoomType and matching source rooms using `rooms_using_room_type`.
2. Parse, deduplicate, and validate every selected Room ID against that source-room set.
3. Validate the proposed source name and uniqueness independently.
4. If selected rooms exist, resolve and validate the target.
5. Assign only selected rooms to `target.name`.
6. If the source is renamed, assign the new source name to all remaining source rooms and update `source.name`.
7. Commit once after all assignments.

On `IntegrityError` or another `SQLAlchemyError`, roll back the entire transaction and return the existing safe error treatment (name conflict or generic 503 service error). No room type assignment, rename, or other database mutation may survive a failure. Do not commit between transfers, room relabeling, or catalog rename. Assignment changes only `Room.type`; preserve room status/state, check-in/check-out, price, and every RoomRental row and its historical values.

## Route strategy

**A — Keep and adapt `POST /room-types/<id>/transfer` to selective IDs.** The endpoint has no current template call site, but it is exercised directly by the existing test suite and may be used by external callers. Preserve the endpoint for compatibility, require the same selected ID list and target rules, and make it a transfer-only operation. It must share the same server-side selected-ID validation/transfer helper as `edit_room_type`; it must not rename the source catalog record. Update its tests to submit IDs. The edit modal continues to use the unified edit endpoint for rename-only, transfer-only, and combined operations. Do not remove the route in this feature.

## Delete behavior and regression risks

Keep the current delete-in-use rule unchanged. After a partial transfer the source still has rooms, so deleting its RoomType remains blocked. After all matching rooms are transferred, the existing delete rule can permit deletion.

Main risks are trusting client checkbox values, losing legacy normalized type matching, accidentally transferring unselected rooms during a rename, leaving remaining rooms under the old name after a catalog rename, breaking occupied rental state/history, and allowing separate commits to leave partial results. The server validation, explicit operation matrix, single transaction, and tests below address those risks. No schema migration or dependency is required.

## Expected implementation files

- `src/hotel_app/app.py`: provide source-room modal data; validate repeated IDs and targets; apply independent rename/transfer semantics atomically; share validation/transfer behavior with the retained endpoint.
- `src/hotel_app/templates/room_types.html`: selective room checklist, Select All, live count, occupied warning, zero-room state, new section heading and selective confirmation.
- `src/hotel_app/static/css/hotel.css`: modal checklist, status labels, summary and responsive scrolling/layout.
- `tests/test_room_types.py`: selective business logic, malformed/tampered IDs, occupied preservation, route compatibility, rollback and UI structure coverage.
Do not modify `src/hotel_app/models.py`, room/rental routes, database schema, Login/Auth/OTP, profile/avatar, or other room behaviors.

## Required test design

### Transfer and rename semantics
1. Select one room from five: only that room moves; four remain.
2. Select several rooms; verify selected and unselected groups.
3. Select all source IDs and transfer all.
4. Submit zero selected IDs with blank target: no transfer; unchanged name is a no-op.
5. Rename-only with blank target updates the catalog and every matching source room text, including normalized legacy variants.
6. Transfer-only preserves source name and leaves unselected rooms associated with it.
7. Rename plus selective transfer yields the documented split.
8. Verify selected IDs always take the target name and every remaining room takes the new source name on rename.
9. Empty source still supports rename.
10. Missing target with selected IDs, same source/target, nonexistent target, malformed target are rejected with no mutation.

### ID validation and transaction safety
11. Non-integer/nonpositive/nonexistent IDs are rejected.
12. An ID from another RoomType is rejected and that room is unchanged.
13. Duplicate submitted IDs process one room once.
14. A stale ID that used to belong but no longer matches the source is rejected.
15. Simulate commit/flush failure after multiple assignments in combined rename/transfer; source name, every room type and target remain unchanged after rollback.
16. CSRF remains required on both routes; unauthenticated behavior remains unchanged.

### Occupied rooms and related behavior
17. Occupied rooms appear as selectable choices and trigger a textual warning when selected.
18. Transferring an occupied room changes only `Room.type`; status, state, check-in/out, price and other room fields remain identical.
19. Existing RoomRental rows, IDs, pricing, duration, and dates remain unchanged.
20. Room Type counts reflect selected transfer and any renamed remaining rooms.
21. Partial transfer leaves source in use and deletion is still rejected; moving all source rooms preserves the existing delete rule.
22. Existing room creation/edit type options and other Room/RoomRental behavior remain healthy.

### UI structure
23. Render room checkbox inputs with `Room.id` values, room numbers and status labels.
24. Render Select All, selected-count summary, target selector, renamed heading, and no “Chuyển toàn bộ phòng” copy.
25. Empty source state displays **Không có phòng để chuyển.** while the rename field remains available.
26. Structural tests verify payload hooks and form CSRF; do not add browser automation solely for checkbox JavaScript.

## Backend/schema decision

**BACKEND_SCHEMA_CHANGE_REQUIRED: NO.** Reuse current models, normalized text matching, routes, session, CSRF and database transaction.

**Next action:** implement Selective Room-Type Transfer after this design stage is approved.