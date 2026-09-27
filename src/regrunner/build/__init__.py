"""The Workbook Builder's live side (P08 onwards): a real browser window the Build tab drives.

* ``session.py``  - one build session per workbook: the headed browser, the injected overlay, picking, "run up to here" (the same
  ``TestRunner`` and actions as a real run), the side-effect pause.
* ``locators.py`` - from a picked element to the most stable unique locator, its backups and a plain-words description (pure logic).
* ``overlay.js``  - the floating pill, hover outline and pick card injected into every page, frame and window of the build browser.
"""
