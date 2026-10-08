# Profile Avatar UX Implementation

## Summary

Implemented the approved clickable avatar editor in the existing profile update form. The editor always shows the stored image or the existing full-name/email initial fallback, opens the existing file input when its semantic label is activated, and previews acceptable selected files locally before submit.

## Backend reused

No backend files or behavior changed. Existing `User.avatar`, `/account` multipart POST, JPG/JPEG/PNG/WEBP signature validation, 5 MiB limit, safe generated filename, authenticated image route and topbar source were reused. Invalid server-side validation continues to prevent both avatar replacement and profile-field updates.

## UI behavior

- Desktop layout uses a two-column profile grid with fields on the left and a centered circular avatar on the right. Narrow layouts stack avatar above fields and save action.
- Fallback initial follows existing topbar behavior: full name first, then email.
- A semantic label named “Chọn ảnh đại diện” is associated with the visually hidden `avatar` input. Hover/focus shows an edit/camera affordance.
- `URL.createObjectURL` provides a local preview; prior URLs are revoked when replaced and on page unload. No upload occurs before **Lưu thông tin**.
- The topbar continues to read the same persisted `user.avatar` and fallback values after redirect.

## Files changed

- `src/hotel_app/templates/account.html`
- `src/hotel_app/static/css/hotel.css`
- `tests/test_login.py`

## Verification

- Baseline: 173 passed.
- Focused: `python -m pytest tests/test_login.py --basetemp=.pytest_tmp -p no:cacheprovider` — 39 passed.
- Full suite: `python -m pytest --basetemp=.pytest_tmp -p no:cacheprovider` — 179 passed.
- `python -m compileall src tests`: passed.
- `git diff --check`: passed.
- Manual browser smoke: not performed in this environment; browser preview, picker, and save synchronization were not visually exercised.