# Deployment validation — 2026-10-10

- Validated on Home Assistant Core 2026.5.0.
- Original integration, dashboard, resources, configuration, and JPEG archive
  were backed up before deployment.
- Home Assistant Core configuration check passed before restart.
- One Core restart; one later Snapshot Archive entry reload succeeded.
- 12 isolated Python tests passed: date validation; descending order/filtering;
  empty dates; path/image symlink rejection; stable renamed camera identity and
  duplicate names; age/size retention with protected symlinks; one-time route
  registration and authentication flags; missing images; motion trigger and
  duplicate suppression; cancellation/unsubscription; scheduled cleanup draining;
  executor cancellation completion; disabled entity exclusion.
- Chromium exercised the actual installed Zen UI 1.3.0 bundle: wrapper heatmap
  screenshot exactly matched original pixels; date mapping; newest-first images;
  full-size viewing; keyboard/Escape; empty, authentication, and server errors;
  second-camera mapping; aborted requests and released object URLs.
- Live authenticated cameras/day/image endpoints passed; original JPEGs remained
  accessible; invalid date/filename 400, unknown camera/missing image 404, empty
  date successful empty list; unauthenticated camera/image requests returned 401.
- Real `snapshot_archive.capture` requests saved new JPEGs before and after entry
  reload. Latest API results sorted newest first. No sensor states were fabricated.
- Actual Home Assistant dashboard date click opened the gallery, downloaded
  authenticated JPEGs, and displayed a decoded 720×720 image at full resolution.
  Initial live browser loading timed out; a fresh browser run passed.
- Both HACS-managed Zen UI files matched predeployment SHA-256 checksums.
- Relevant post-restart logs contained no Snapshot Archive errors or blocking
  filesystem warnings. Two authentication warnings were expected denial tests.
  Existing unrelated sun2 and Chromecast errors were present.
- No unfinished `.tmp` image files were found after capture.

Not physically verified: a new motion event after deployment; additional camera
hardware (only one device was selected); actual 365-day aging/10 GiB pressure
on the production archive. Motion and retention paths were exercised by isolated
tests; manual real captures used the same capture pipeline. Future Zen UI versions
need a date adapter compatibility check because 1.3.0 has no public click event.

Local regression checks are `tests/test_archive.py` and `tests/browser_test.py`.
The one-off live deployment scripts and evidence were removed during repository
cleanup. API credentials stayed in memory during the recorded validation.


## Gallery deletion and compact trash icon — 0.2.2

- Added authenticated DELETE on the image route, with the same configured-camera,
  calendar-date, and filename restrictions. Deletes only a regular file using a
  pinned directory descriptor; rejects symlinks and directories.
- Gallery uses a small accessible trash-can button beside the timestamp. Success
  re-fetches the camera/date, updates the count/images, and releases old blobs.
  Errors preserve the image; an already-removed image triggers a refresh.
- 18 integration tests passed, including delete isolation, updated/empty listings,
  invalid paths, symlinks/nonfiles, missing camera/image, I/O failure, and frontend
  resource create/update/idempotence. Browser regression tests passed unchanged
  heatmap pixels plus delete success/failure/empty-date behavior.
- One Core restart loaded the DELETE handler; compact icon and resource fixes
  required no additional restart. Core configuration check passed.
- Fresh-browser testing reproduced an intermittent lost custom-element
  registration from early extra-module loading. Registered the gallery as a
  standard Lovelace resource through the supported WebSocket API; fixed the
  integration to register/update that resource automatically on future setup.
  Future automatic startup registration is covered by isolated tests and the
  Core config check; it has not required another live restart.
- Real dashboard trash-icon click deleted only disposable test filename
  23-59-59-987654.jpg, returned 204, and refreshed the gallery from 2 images to 1.
  Its image route then returned 404. The original JPEG present before the test
  retained its SHA-256 hash. The test copy was cleaned up after failed attempts.
- Unauthenticated DELETE returned 401 and left the test copy intact. Logs show
  only expected authentication-denial warnings for these tests; no Snapshot
  Archive errors. Both Zen UI bundles retain their original SHA-256 checksums.
- Existing archive contained one original image when live deletion testing began;
  the four images present before feature deployment are preserved in the backup
  below. The automated deletion test never selected an original filename.
