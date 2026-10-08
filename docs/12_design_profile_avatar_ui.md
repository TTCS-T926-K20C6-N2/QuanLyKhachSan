# Profile Avatar UX Design

## Status and scope

**PROFILE_AVATAR_UI_DESIGN_STATUS: PASS**
**IMPLEMENTATION_READY: YES**

Requirements and design only. Preserve Login/Register/Logout, password recovery, Rooms and rentals. Reuse avatar storage and validation.

## Current backend findings

- `User.avatar` is nullable VARCHAR(255), storing an avatar filename.
- `POST /account` updates profile fields and an optional avatar together. It reads at most 5 MiB plus one byte, sanitizes the submitted filename with `secure_filename`, and validates JPG/JPEG, PNG and WEBP extension plus file signatures. WEBP receives an additional signature check.
- Files are stored under configured `ROOM_UPLOAD_FOLDER` with a generated random `profile-<token>.<ext>` basename. Client filenames are not used as storage paths.
- Validation errors prevent avatar writes and profile commits. Persistence errors roll back and remove a newly written image. On success, the old generated image is removed and the route redirects to `/account`.
- `GET /profile-images/<path:filename>` requires authentication and uses Flask `send_from_directory` rooted in the configured upload directory.
- Existing validation, storage and serving are sufficient. No model, route, schema or storage change is required.

## Current topbar behavior

The shared `base.html` topbar uses `user.avatar` through `profile_image`. Without an uploaded image it shows the uppercase initial of full name, then email. Authenticated renders use the current database User, so the topbar reflects a successful save on the redirect. The profile editor must use the same source and fallback order.

## Default avatar

Always show a circular avatar. Use the stored image; otherwise show the uppercase first character of full name, then email. A generic user icon is a defensive fallback if neither has a character. Never render a broken or empty-source image.

## Layout

- Desktop: two columns, personal information around 65–70%, avatar around 30–35%. Use a centered 160–180px avatar and short helper text.
- Mobile/tablet: stack avatar first, personal information second, existing save action last. Center the fixed-size avatar and keep inputs full width.
- Keep Hotel Management colors, typography and panel style.

## Click-to-select and accessibility

Keep one form-associated `avatar` file input with `accept="image/jpeg,image/png,image/webp"` and existing help/error references. Hide the raw native chooser from normal visual presentation and associate it with a semantic `label for="avatar"` styled as the circular target. Give it accessible name “Chọn ảnh đại diện”, visible “Nhấn để đổi ảnh” helper text, decorative camera/edit hint and visible keyboard focus. Native label semantics provide keyboard activation.

## Preview lifecycle

Use a small account-page script listening for the input change. For a plausible accepted type no larger than 5 MiB, create a temporary object URL and update the avatar image immediately. Revoke old URLs when replaced and on unload. The preview remains local until the existing form submit; navigation/reload discards it. Client checks are for usability only; server validation remains authoritative. No new browser framework.

## Validation and save

Preserve existing authoritative JPG/JPEG, PNG, WEBP, 5 MiB, extension/signature checks and safe generated filename. Validate before file writes or profile updates. Invalid uploads preserve existing avatar and persisted profile fields. Valid avatar and profile data save together using **Lưu thông tin**. Keep email immutable and do not add a separate avatar-save action.

## Expected implementation files

- `src/hotel_app/templates/account.html`: profile/avatar grid, image or fallback, semantic clickable label, hidden input, preview target and small script; preserve CSRF and save action.
- `src/hotel_app/static/css/hotel.css`: responsive profile grid, circular 160–180px avatar, cover crop, hover/edit affordance, focus ring and hidden-input styling.
- `tests/test_login.py`: focused avatar/profile tests.
Keep `app.py`, `models.py`, schema, routes, upload location, Login/Register/recovery and room features unchanged.

## Required tests

1. No-avatar fallback uses full-name initial; empty name falls back to email initial.
2. Existing avatar appears on profile.
3. Topbar uses same image source and fallback behavior.
4. Raw file chooser is not the normal visible control.
5. Clickable label associates with input, has accessible name and visible focus.
6. Valid JPG/JPEG, PNG and WEBP uploads succeed.
7. Unsupported extension/content and files over 5 MiB are rejected.
8. Invalid upload does not replace an existing avatar or save other fields.
9. Valid avatar persists through existing profile POST.
10. Personal-info update still works and login email does not change.
11. New avatar appears in topbar after save.
12. Existing Login/Register/Profile behavior remains passing.
13. Manual check: select a valid image and confirm immediate preview before submit; navigate away unsaved, return and confirm persisted avatar is unchanged.

## Backend decision

**BACKEND_CHANGE_REQUIRED: NO.** Existing field, upload flow, validation, storage and serving support this UX.