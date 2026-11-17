# Changelog

## 4.9.0 - Works on every screen: phones, tablets, laptops, large monitors
Reading rules, calculations, Excel output and the server are unchanged. Laptop / desktop (≥ 1101 px wide) keeps the v4.8 layout pixel for pixel.
- **Phones and portrait tablets (< 900 px):** one screen at a time with a bottom bar **Drawing · Split · Sheet · Check**.
  - *Split* puts the drawing above the sheet in portrait and beside it in landscape; a **draggable divider** sets the sizes (double-tap resets, arrow keys work too). The view and divider position are remembered per device.
  - The page rail becomes a strip of pages above the drawing (page numbers + counts on phones, thumbnails on tablets).
  - The top bar wraps to two rows: modules, AI, Open, Export and a **⋯ More** menu (Undo, Redo, Open, Export all, AI settings, Team link, Shortcuts, Home); open PDFs get their own row.
  - The page toolbar is one row that scrolls sideways; the sheet panel scrolls as a whole and its totals / filters can be folded away (**^**).
- **Compact sheet cards** whenever the sheet panel is narrow (phones, tablets, small laptops): each glass panel is a card with tag, L / R upper and lower, totals, Diff and Judgement; DOOR cards keep the A / B / C1 / C2 block with Diff and FINAL under it. Same inputs, same keyboard navigation (Enter, arrow keys), same click-to-fill.
- **Small laptops / iPad landscape (900–1100 px):** drawing and sheet stay side by side with a narrower rail and sheet. **Monitors ≥ 2200 px:** wider sheet panel.
- **Touch:** pinch to zoom the drawing (iOS and Android), bigger buttons and tap areas, larger hit area around values on the drawing while filling, 16 px inputs so iPhone does not zoom when you tap a cell, safe areas on notched phones.
- **Pick on drawing:** in the *Sheet* view, tapping a cell shows *Fill … · Pick on drawing*; the app switches to the drawing, you tap the value(s), *Done* returns to the sheet.
- **Check** button in the bottom bar steps through everything to check (same as the tile / **N**). Tapping an elevation in the Sheet view shows it on the drawing.
- Reading window, AI window, Team link and shortcuts windows fit small screens; the toast sits above the bottom bar. Home screen texts say *tap* on touch screens.
- **Online version:** `render.yaml` Blueprint for Render (free plan). `GLASS_PUBLIC=1` opens the app to everyone behind Render's HTTPS proxy, locks the AI key settings, and makes the Team link the site address. The office version is unchanged.
- **Tests:** 177 tests. New `tests/test_responsive.py` checks the page and, when Playwright + Chrome are installed, drives the real app at 375×667, 844×390, 768×1024, 1024×768, 1366×1024, 1280×720 and 1920×1080 (open PDF, edit, fill from the drawing, views, DOOR, export, no sideways scrolling).

## 4.8.1 - AI package install fix
- **"The anthropic package is missing":** `run_app.bat` used to install the AI package silently, so a failure (office proxy / firewall) was hidden. It now shows the install, retries with `--trusted-host pypi.org files.pythonhosted.org`, and says clearly if it still fails. The app keeps working without AI (OCR).
- **New `install_ai.bat`:** installs / repairs the AI package with the full output on screen and prints *AI package OK* when done.
- **`build_exe.bat`:** the exe now bundles the AI package (and waitress).
- **AI window:** the status text no longer breaks into one word per line; a missing package shows an orange box with what to do. The home screen says *AI key found · AI package missing - run install_ai.bat*.

## 4.8.0 - New look, reading window, AI key file
Workflow, reading rules, Excel output and keyboard navigation are unchanged.
- **New design:** dark "instrument" header with one accent colour per module (GLASS blue, DOOR teal), a sliding GLASS / DOOR switch, file chips, icon undo / redo and a clear Export button. Frosted viewer toolbar, KPI tiles, softer cards.
- **New start-up screen:** blueprint grid with a glass elevation that draws itself, a BM laser line sweep and benchmark chips appearing in turn. GLASS and DOOR cards (G / D, drop PDFs on a card), the AI status and the Team link at the bottom. Calm version when Windows "reduce animations" is on.
- **Reading window while a PDF is read:** live page preview with a scanning beam, page X of N, time, counts of elevations, values, doors and raster / AI pages, and one line per page marked VECTOR / RASTER / AI. *Continue in background* keeps you working; a summary shows when done and closes by itself. Fast text PDFs finish before it even appears.
- **Page thumbnails** in the page rail, with the elevation / door count under each.
- **Next to check:** click the To check tile or press **N** to step through every elevation / door that needs a look.
- **AI key file:** put **`key.txt`** (the Anthropic key on one line) next to `run_app.bat` and AI switches on by itself. The header shows **AI ON** and the AI window shows "Key read from key.txt". The file is never served to the browser and never packaged.
- **AI on vector pages with gaps:** a text page missing values (outlined / pictured numbers) gets **only its empty cells** filled by AI; text values are never replaced, and the note lists what AI filled.
- **AI failures are visible:** if AI cannot read a page (bad key, no internet), the reading window says so and OCR is used.
- **Fix:** Esc now closes the AI / Team link windows on the home screen.
- **Tests:** 167 tests (key file, AI gap filling) plus a browser run of home → read → GLASS → DOOR → export → AI window.

## 4.7.0 - AI reading with Claude for raster PDFs
- **New: ✨ AI reading** with your Anthropic API key, for raster or scanned FM sheets where OCR is not good enough.
  - **Models:** Claude Sonnet 5.5 (default), Opus 5.5 or Haiku 5.5.
  - **When:** picture and scanned pages automatically, only on the **✨ AI read page** button, or off.
  - **Two passes per page:** the page gives the elevation titles and areas; each elevation crop then gives the edges' upper and lower, tags and codes, BY OTHERS, door type, hinge and the 45° / 90° / closed swing readings.
  - **Fixed JSON output with boxes:** each answer has a fixed structure (forced tool call), and each value comes with its box. Images are sized to the high-resolution tier, so the boxes map 1:1 onto the drawing.
- **The app's own rules still do every calculation** on the AI values: one upper for every edge, blank edge = average of its neighbours (rounded down to 1/16"), and door A / B / C1 / C2.
- **QC:**
  - Every AI value is cross-checked with OCR of the same spot. A disagreement is flagged *REQUIRES HUMAN REVIEW* with both readings.
  - Values the AI was unsure of are flagged too.
  - When AI fails, the OCR read is kept and the note says why: wrong key, no network, rate limit or busy.
- **AI settings window:** API key (stored on the host PC only; only its last 4 characters are shown), model, mode, Test connection, and the tokens used this session. Only the host PC can change the settings.
- **Command line:** `--ai-check file.pdf` prints the AI read of every page.
- **Install:** `run_app.bat` installs the `anthropic` package.
- **Tests:** 165 tests. The AI tests use a fake API client and cover box mapping, the team rules, the OCR cross-check, doors, fallbacks, and that the settings are host-only and never return the key.

## 4.6.0 - 14101 Sherritt: elevations pasted as pictures, one-glyph fractions
- **Pages whose elevations are a picture are read.** The 14101 elevations are a picture placed on the FM template, so the text layer has no titles and no values. Every page showed "none".
  - When a page gives no elevation from its text but holds a large picture (or is almost all vector outlines), that area is now read with OCR, and every value is flagged *check every value*.
- **One-glyph fractions read by OCR:** `54¼`, `49⅝"`, `50⅛"`, `49¾"` used to come back from OCR as `54%4`, `544`, `5414` or `49%"`, and the fraction was lost.
  - The glyph after the whole number is now cut out of a sharp render and matched against ½ ¼ ¾ ⅛ ⅜ ⅝ ⅞.
  - OCR forms such as `541/4`, `5414` and `4958"` in mark-up colour are also read as 54 1/4 / 49 5/8.
- **Tiled OCR:**
  - The tile overlap was raised from 140 to 300 px, so short values are no longer cut in half.
  - A word cut at a tile edge is dropped when the next tile reads it whole.
  - Long lines (elevation titles) cut in both tiles are joined on their common text.
- **Rebuilt 14101 screenshot sheet:** all 16 values read exactly (54 1/4 ×8; 49 1/2, 49 5/8, 49 5/8, 50; 50, 49 3/4, 50 1/8, 50 1/4), with both elevations and both sliding doors.
- **Tests:** 158 tests, including a picture-only FM sheet with one-glyph fractions and a glyph-classifier test (½ ¼ ¾ ⅛ ⅜ ⅝ ⅞).

## 4.5.0 - 14065 UBS Boca Raton fixes
- **Uppers written at only some edges.** When the given values are the same (44" at the two end edges), that value now goes to every edge; before, the inner edges were left blank.
  - When the given uppers differ, a blank edge between two of them gets their average, rounded down to 1/16" (same rule as for lowers). A blank end edge gets the nearest given value.
  - The elevation note shows what was used.
- **Fractions with repeated inch marks are read in full.** `59 11/16"""`, `59 11/16''`, `59 11/16‴` and `59 11/16 "` used to lose the fraction and show as `59`. Bluebeam mark-ups and page text are both covered.
- **Tests:** 156 tests, including 14065-style sheets (uppers only at the ends, triple inch marks, with and without Bluebeam mark-ups).

## 4.4.0 - blank edges get the average of their neighbours; one Excel file with GLASS + DOOR tabs
- **Blank edge between two written edges = their average.** This applies to elevations whose lowers are written under the title (14090 CONFERENCE 360, 14092). Before, the blank edge copied the previous edge.
  - Example: 360-C lower = (L2 + L4) / 2 = (60 11/16 + 60 13/16) / 2 = **60 3/4**.
  - Example: the 360-E / 360-F edge = (L5 + L7) / 2 = (60 3/4 + 60 5/8) / 2 = **60 11/16**.
  - The average is rounded down to 1/16" (same rule as the judgement average). The elevation note shows each calculation.
  - A blank edge at the end of an elevation still takes the nearest written value.
  - Uppers follow the same rule.
- **One workbook per PDF:** `<PDF name>.xlsx` with two tabs, **GLASS** and **DOOR**, like the team file.
  - Export to Excel gives the same file from the GLASS and the DOOR module, and so do Export all (zip) and `batch_convert.bat`.
  - Each tab keeps its own stored results.
  - The DOOR tab is the empty template when a PDF has no doors.
- **14092 regression updated:** 4 edges changed from a copied value to the average (ELEV 5 and 6).
- **Tests:** 153 tests, including the CONFERENCE 360 case and blank edges in the 14092-style fuzz sheets.

## 4.3.1 - port 8080
- **The app now runs on port 8080.** The links are `http://127.0.0.1:8080` on this PC and `http://<IP>:8080` on other PCs (for example `http://192.168.8.87:8080`).
- **Port in use:** if another program already uses 8080, the next free port (8081, 8082, ...) is used and shown in the window and the Team link. `GLASS_PORT` or `--port` still choose a different port.
- **`allow_network_access.bat`** now opens ports 8080–8109. Run it again (as administrator) if you ran it for v4.3; it replaces the old 5050 rule.
- **Firewall check:** the start window warns when the firewall rule does not cover the port in use.

## 4.3.0 - use the app from any PC on the office network
- **The app is shared on the office network.** It runs on one PC, and colleagues open the **Team link** in their browser, for example `http://192.168.8.87:5050`. Nothing is installed on their PCs.
  - **The address is detected at every start** (IP addresses and computer name), so a new DHCP address is picked up automatically.
  - **Where the link appears:** in the start window, behind the new **🔗 Team link** button (with Copy), at the bottom of the home screen, and in `glass_data/TEAM_LINK.txt`.
- **Office network only:** this PC and private office addresses can connect (10.x / 172.16–31.x / 192.168.x). Everything else is refused. The setting is `GLASS_ALLOW`.
- **`allow_network_access.bat`:** run once as administrator. It adds a Windows Firewall rule for ports 5050–5079, office addresses only.
- **Multi-user server:** the app now runs on `waitress` (16 threads); it falls back to the Flask server if waitress is missing. `run_app.bat` installs waitress on existing installs too.
- **Start-up:**
  - If port 5050 is busy, the next free port is used.
  - Starting the app twice opens the running one instead of failing.
  - `--local` runs it for this PC only, and `--host` picks the address to listen on.
- **Safety:** an uploaded PDF is written atomically, so two people opening the same PDF at the same moment is safe.
- `.bat` files use Windows line endings.

## 4.2.0 - arrow keys move between cells
- **↑ / ↓** move to the same column in the row above or below. This works across panels, elevations and door cards, in both GLASS and DOOR.
- **← / →** move to the cell next to it once the caret is at the start or end of the value, or when the whole value is selected. While you are editing inside a value, the arrows still move the caret.
- A cell reached with the arrows has its value selected. Type to replace it, or press an arrow again to keep going. An edited value is saved when you move on, and Ctrl+Z undoes it.
- Click-to-fill follows the cell you move to. Mouse navigation and Enter work as before.
- Extraction is unchanged (reader 4.1), so saved page results stay valid.

## 4.1.0 - door swing readings read from the drawing; sidebar laid out like the DOOR sheet
- **C1 / C2 now follow the team's rule.** C1 is the swing-plan reading at **45°**, C2 the reading at **90°** (tip of the open leaf). The quarter arc of the swing plan is now found in the PDF (Bezier or polyline), and each reading is matched to its point on the arc. The reading at the closed end of the arc is recognised as the closed door: it is a check, not a C value. Stray values next to the plan (such as `59 7/16`) are no longer picked up.
- **Hinge side read from the drawing.** First the dashed V drawn on the door in elevation (its point is the hinge side), then the pivot of the swing plan, then the closed-door reading. **A is the hinge side and B the latch side**, as on the team sheet (C2 takes A's upper because the open leaf stands over the hinge). In v4.0, A was the edge whose lower repeats on the plan, which is the latch side, so some doors had A and B the wrong way round.
- **Plans written without an arc** are fitted to where the plan would be: the tip over the hinge, 45° toward the latch, then the closed position.
- **Door edges** snap to the drawn frame lines, not to where the readings are written.
- **New notes:** hinge side not found or unclear, which swing reading (45° / 90°) is missing, and closed reading differs from the latch lower.
- **DOOR sidebar card = the DOOR sheet block.** Columns A, B, C1, C2 (with hinge / latch / 45° / 90° under them), rows Upper / Lower / Total, Diff under the uppers, and FINAL in yellow beside the grey totals. The look is otherwise unchanged.
  - The card shows a *Hinge left / right* chip.
  - Hovering a column highlights that point on the drawing, and the closed-door reading shows as a grey *closed* box.
  - ⇄ Swap also flips the hinge.
- **Checked on:**
  - 14005: the team screenshot of ELEV 5 is exact (C1 65 15/16, C2 65 13/16), and all 5 doors get their hinge from the elevation V.
  - 14092: all 4 doors.
  - 14002 sample: door 63 = team DOOR sheet (107 5/16).
  - 14075: sliding doors unchanged.
- **Tests:** 149 tests, including a door fuzz test. It varies the hinge side, draws the plan as an arc or only writes it, adds or leaves out the V, and adds stray values (478 of 478 doors exact). The self-test now also runs 3 random door sheets.

## 4.0.0 - DOOR module
- **New home screen:** MURAFLEX AUTOMATION with two cards, **GLASS** and **DOOR**. Same starfield and glass look, and each card glows on hover. Press G / D, click, or drop PDFs on a card. The ⌂ button or `H` goes back home, and the header switch changes module without reopening the PDFs.
- **GLASS module** works exactly as before, except that doors are gone. They are not in the list, on the drawing or in the GLASS sheet. Each elevation shows how many doors went to the DOOR module.
- **DOOR module:** the same screen as GLASS, showing only doors.
  - **Pivot doors:** A = hinge side, the edge whose lower is repeated at the pivot of the swing plan. B = latch side. C1 / C2 = the other swing readings, with B's / A's upper.
  - **Sliding doors** (code ending in SD / STD): A = closed end, B = inner edge, C1 = end of travel.
  - Each point shows Upper / Lower / Total, plus Diff (A − B) and FINAL (GLASS judgement rules).
  - **Editing:** Pivot / Sliding switch, ⇄ Swap A / B, click-to-fill, + Add door, untick to skip, undo / redo, autosave, and A / B / C1 / C2 labels on the drawing.
- **DOOR sheet** `<PDF name> - DOOR.xlsx`, laid out like the team sheet: pivot doors in A / C–H, sliding doors in J / K–O, and 4 rows per door (uppers, lowers + Diff, grey totals + yellow FINAL). The formulas are live and their results are stored. Empty template blocks show 0.
- **Batch:** writes the DOOR workbook next to the GLASS one when a PDF has doors. The self-test now checks doors too.
- **Checked against the team's DOOR example:**
  - 14075 sliding doors are exact (102 and 102 3/8).
  - 14002 door 63 is exact.
  - All 5 doors of 14005 and all 4 doors of 14092 get their hinge side and both swing readings.
- **Fix:** a black note written next to a red reading is no longer taken as its label (14092 door 717 swing reading `60 1/16`).
- **Tests:** 139 tests, including the DOOR sheet against a LibreOffice recalculation.

## 3.5.0 - fractions whose bar is a drawn line (13869 Sanofi)
- **Numerator and denominator stored as one small word are read.** When the fraction bar is a drawn line, the small digits are stored together (`116`, `916`, `1516`, `18"`). They are now split into a real fraction: `36 1/16"`, `40 9/16"`, `40 15/16"`, `72 1/8"`. Before, `36` was joined to the `"`, so the value showed as `36`. A lone `1/8` was read as `18`, which is where the stray `18` lowers came from.
- **Raised and lowered digits in one text run are split before joining,** so `36` + raised `1` + lowered `16` is read as `36 1/16"`. Only digits are split this way, so symbols such as the `℄` drawn as C + L stay intact.
- **Unicode fraction pieces are joined however many pieces the PDF splits them into:** `49` `⁷` `⁄` `₈` `"` is read as `49 7/8"`.
- **`±` before a value** (`±72 1/8"`) is read.
- **Click-to-fill now puts in the full fraction.** It used to fill only the whole number, because the clickable value was the incomplete `36`.
- **Tests:** 125 tests. All fuzz families give 0 errors. The real PDFs are unchanged.

## 3.4.0 - stacked fractions
- **CAD stacked fractions are read in full.** These are a big whole number, a small raised numerator and a small lowered or stacked denominator, often with the inch mark as a separate word: `36` `1` `16` `"` is read as `36 1/16"`. Before, `36` was glued to the `"`, so the reading came out as `36` and the fraction was lost.
- **Unicode fractions are read too:** `36¹⁄₁₆"`, `40⁹⁄₁₆"` and `57¼"`, including when the PDF splits the glyphs into pieces.
- **Fractions are only joined when they are real fractions:** denominator 2, 4, 8, 16, 32 or 64 and numerator smaller than the denominator. Nearby unrelated small numbers stay separate.
- **Tests:** 119 tests. Full sheets written with CAD-stacked and unicode fractions read exactly. All fuzz families still give 0 errors.

## 3.3.0 - 13871 AstraZeneca fixes
- **No more "ELEV ?" duplicates.** Notes such as `NOTE TO ARCHITECT: ELEVATION 26 & 27 WILL RECEIVE…` were read as titles. A title now needs `ELEVATION /`, `ELEVATION:` or `ELEVATION` on its own. The fake elevations were taking the uppers of the real elevations, which is why those upper cells were empty.
- **Uppers the same size as lowers** (`48` / `48 3/8`) are kept. The 3.2 rule that dropped uppers looking like lowers, meant for door-swing plans, is now used only for readings above the edge labels.
- **Readings far from the rest of their row are dropped.** This covers a bulkhead height (`69 3/4`) over a door and a thickness (`15 1/4`) on a side view.
- **Code words inside a note** (`… RECEIVE A FPD DUE TO …`) are no longer glass or door codes.
- **Door plus narrow sidelite between the same two readings:** the span is split at the mullion line between them. The mullion takes the nearest edge's values and is flagged.
- **Saved edits now record the reader version.** Edits made on an older version show a "Keep new read" (recommended) banner, so old mistakes are not restored by accident.
- **Tests:** 111 tests, plus a 13871-style generator and fuzz test (upright and rotated): 499 of 499 lites exact, no fake elevations.

## 3.2.0 - real 14005 / 14075 / 14092 PDFs, ADMIN layout, new name
The app is renamed **MURAFLEX AUTOMATION**.

**New layouts**
- **Lowers under the title** (14092): read and matched to the nearest frame edge. Frame edges come from the mullion lines, including rectangles and quads drawn on rotated CAD plots. Before, these elevations were dropped, so ELEV 3 and ELEV 7 were missing.
- **One upper for the whole elevation** is used at every edge. An elevation with no upper takes it from its neighbour on the same BM line. Both are flagged.
- **Door-swing plan readings** are recognised because they repeat the lower values, so they are never taken as uppers.
- **ADMIN layout:** hyphen fractions (`42-1/16`, `60-5/8`) are read. Before, only bare numbers were read, so values were mixed up. Stacked lites (D1 / D2 / D3) share their column's edges. Second lite tags are joined to the first (`1917-D1 / 1917-DD1`).
- **BY OTHERS glass** is listed, not exported, and can be ticked.
- **Deleted / N.I.C.** written on an elevation is flagged.

**Fixes found on the real PDFs**
- Glass and door codes are matched generically, so `CLIGL-12`, `DGL-12`, `FPD-DGO`, `GSD-12` and others are recognised. Before, ELEV 3 of 14005 was dropped (`CLIGL`). Plain words such as ANGLE are never codes.
- Titles split into two text pieces (`ELEVATION /` + `INT. ATTORNEY S.O. 3110A`) are joined, so names and rooms are filled again.
- Readings beside a side view, nearer the next elevation, go to the side view when it has none of its own (14005 ELEV 6).
- Readings outside the frame that would only create an empty end span are dropped (14005 ELEV 9).
- A value next to a red `DW` label is no longer mistaken for a label (`45 3/4"  DW`).
- Invisible and white text is ignored.
- The OCR retry only reads the problem area, not the whole page: 14005 dropped from 8.9 s to 1.9 s.

**Tests**
- 102 tests, including real-PDF regression for 14005, 14075 and 14092, and generators and fuzz tests for the 14092 and ADMIN layouts (upright and rotated).
- The self-test now covers 4 sheet families.

## 3.1.0 - real 14005 Gibson Dunn layout
Fixes for the bugs on the 14005 screenshots: lowers were missing, values were marked as UPPER, elevations were lost, and one elevation showed as "ELEV ?".

**Values**
- Bare numbers in mark-up colour (`66`, `48`) are now values. Before, they were rejected, so lowers were lost and whole elevations were dropped.
- A fraction stored as a separate word is joined back to its whole number (`65'` + `13/16`). Before, only `65` was read.
- `48FT`, `BM 48FT`, `BM 65' 1/4` and `66'` are read as inches. Real feet-inches such as `5'-6 1/2"` still work.
- Any mark-up colour is accepted in one elevation, so green uppers with red lowers work.
- Numbers inside word labels (`42" HOLD TO`, the caption under `FAL - FAL`) are ignored.

**Benchmark line**
- The BM line is the line or label that splits the values into an upper and a lower band. A `BM` prefix on a value no longer becomes the BM line.
- Dashed lines drawn as many short segments are merged into one line.
- When one side has extra readings far from its band (a width label, for example), they are dropped.

**Titles and panels**
- Sentences in notes, such as the cloud note "Elevation 1 it is wood floor 5/8", are no longer elevation titles. This was the cause of "ELEV ?".
- `SEE ELEVATION 4` references are ignored. `ELEV. /` titles are supported.
- A circled number drawn as a picture is read by OCR of the ring.
- Rotated (vertical) tags are paired correctly, and tags are assigned to spans tag by tag.
- Side views with one measured edge use the same values for both edges and are flagged.
- A span with no glass tag (wall or existing condition) is listed as NO TAG and not exported.
- A missing value is recovered from the nearest unused reading in the right band and flagged.

**More PDF types**
- Rotated CAD plots (`/Rotate 90/270`): text direction is now taken as displayed.
- Bluebeam FreeText mark-ups are read glyph by glyph, keeping each word's real position and colour.
- On pages where elevations have tags but no readable values, OCR also reads the graphics (hybrid text + OCR).
- OCR fixes: a short fragment no longer hides the full reading, and RapidOCR settings no longer carry over from one call to the next.

**App**
- MURAFLEX AUTOMATION start-up screen: starfield, glass card and orbiting planet. The card glows and lifts on hover. Click, Enter or drop a PDF to begin.
- Untagged spans are shown as NO TAG rows, and the room number is no longer repeated in elevation names.

**Tests**
- 77 tests (26 new), including a Gibson-style generator and fuzz test, rotation, picture values and circle-number OCR.
- The self-test now includes Gibson-style sheets.
- Fuzz run: 900 PDFs / 9,141 panels, 0 errors.

## 3.0.0
**Engine**
- Rebuilt as a tested package (`glassx/`) with a single `app.py` launcher.
- Column boundaries are anchored on the glass codes. A value written just left of an elevation's first edge now stays with that elevation.
- Elevation numbers 10 and above are read even when the PDF merges the number into the title line (`10ELEVATION / ...`).
- Uppers and lowers are paired by optimal sequence alignment. One missing value no longer shifts every later point.
- The mark-up colour is detected automatically, so red, blue or any other mark-up ink works.
- The BM label is chosen per elevation column, with fallbacks to the dashed vector line and then to the largest vertical gap between values.
- Tags are only accepted from text, never from dimension values. Door tag `63` can no longer be read as `63"`.
- OCR reads scanned pages in overlapping tiles, so small labels survive. OCR lines split at large gaps, so titles that share a row stay separate. Every OCR elevation is flagged for checking.
- Page results are cached per engine version, so re-opening a PDF is instant.

**App**
- Several PDFs can be open at once in tabs; **Export all** produces one workbook per PDF in a zip.
- Click-to-fill: select a cell, then click any value on the drawing.
- Undo / redo (Ctrl+Z / Ctrl+Y) for every edit.
- **To check** counter and *Only to check* filter.
- Keyboard shortcuts (`?`), status line with read time, and logs.

**Tools**
- `--batch` command line and `batch_convert.bat` (drag a folder onto it).
- `--selftest` and `self_test.bat`.
- `build_exe.bat` (PyInstaller).
- 51 pytest tests, including a fuzz test and a check of Excel values against LibreOffice. GitHub Actions CI on Windows and Linux.

## 2.1.0
- Excel formula cells store their results, so values show in Protected View.
- The review list scrolls.
- Pages without measured elevations are ignored.
- Saved edits, + Add panel and × remove, jump bar.

## 2.0.0
- Rebuilt as an automatic whole-page reader with a light UI and export of the team's GLASS template.

## 1.0.0
- Drag-a-box OCR capture tool with full QC workbook.
