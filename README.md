# MURAFLEX AUTOMATION  ·  v4.9.0

**Muraflex Field Measurement PDF → the estimation team's GLASS and DOOR sheets, in seconds.**

The app has two modules, chosen from the home screen:

| Module | What it reads | What it writes |
|---|---|---|
| **GLASS** | The red upper and lower benchmark at each glass panel edge, matched to the glass tags | The team's GLASS template, with TOTAL, Difference, JUDGEMENT and Fraction already calculated. Doors are left out. |
| **DOOR** | Every pivot and sliding door, measured at points A, B, C1 and C2. The hinge side and the door-swing readings are found on the drawing. | The team's DOOR sheet: pivot doors on the left, sliding doors on the right, with totals, Diff and FINAL |

Both modules export **one workbook per PDF, `<PDF name>.xlsx`, with two tabs: GLASS and DOOR**, like the team file.

The estimator's job becomes reviewing the values instead of typing them.

| | |
|---|---|
| Speed | **~8 ms per page** for a text PDF (2,994 pages in 25 s); scanned / picture pages use OCR (~5–10 s/page) |
| Verified | **177 automated tests**, including **3 real project PDFs** (14005, 14075, 14092; every elevation checked against the sheets) and fuzz tests on **5 sheet families**: 14002 style, 14005 style, 14092 style (lowers under the title, one upper, BY OTHERS), ADMIN style (hyphen fractions, stacked lites) and 13871 style (uppers equal to lowers, notes naming elevations, narrow sidelites). The families cover page text, Bluebeam mark-ups and rotated CAD plots. |
| Excel check | Every stored TOTAL / Difference / JUDGEMENT / Fraction is checked against a LibreOffice recalculation of the same formulas (0 mismatches) |
| Runs | On one office PC; everyone on the office network uses it from their browser (Team link). No cloud and no internet needed after install |

> **Accuracy note:** checked on the real 14005, 14075 and 14092 PDFs, plus generated sheets of every layout family seen so far. New layouts can still surprise it. Batch a folder of past projects (`batch_convert.bat`), spot-check the workbooks, and read the yellow notes in the app.

---

## 1. Quick start (Windows)

| Step | Do this |
|---|---|
| Install once | Install Python 3.9–3.13 from python.org and tick **Add Python to PATH** during setup. |
| Start the app | Double-click **`run_app.bat`**. The first run installs packages (2–3 min), then the browser opens at http://127.0.0.1:8080 on the MURAFLEX AUTOMATION home screen. Click **GLASS** or **DOOR** (or press G / D). |
| Convert without the UI | Drag FM PDFs or a whole folder onto **`batch_convert.bat`**. Each PDF gets one `.xlsx` (tabs GLASS + DOOR) saved next to it. |
| Check the install | Double-click **`self_test.bat`**. It runs an end-to-end test on generated FM sheets and prints PASS or FAIL. |
| No-Python build | Run **`build_exe.bat`**. It creates `dist\MuraflexAutomation\MuraflexAutomation.exe`. |

## Office network: use it from any PC

The app runs on **one PC** (the host). Everyone else in the office opens the **Team link** in Chrome or Edge, so nothing is installed on their PCs.

1. On the host PC, double-click **`run_app.bat`**. The window shows the links:
   ```
   This PC          : http://127.0.0.1:8080
   Other office PCs : http://192.168.8.87:8080      <- share this link
                      http://<COMPUTER-NAME>:8080
   ```
   The link is also in the app: the **🔗 Team link** button, the bottom of the home screen, and `glass_data/TEAM_LINK.txt`.
2. **Once only, on the host PC:** right-click **`allow_network_access.bat`** and choose **Run as administrator**. This opens ports 8080–8109 in Windows Firewall for office addresses only (10.x, 172.16–31.x, 192.168.x). If Windows asks whether to allow Python on the network on the first start, click **Allow**.
3. Other PCs open the link. Each person exports their own Excel files, which download to their own PC.

**Notes**
* **The address is found automatically at every start**, so it is never hard-coded. If the office DHCP gives the host a new IP, the new link is shown. To keep one fixed link, ask IT for a DHCP reservation, or use the `http://<COMPUTER-NAME>:8080` link.
* **Keep the host PC on**, with the app window open, while people use it.
* **Only this PC and private office addresses can connect.** Anyone else gets "only available on the office network". The setting is `GLASS_ALLOW`.
* **One PDF, two people:** a PDF opened by two people shares the same saved edits.
* **Server:** the app uses the `waitress` server (many users at once); `run_app.bat` installs it. `python app.py --local` runs it for this PC only.
* **Port:** if port 8080 is busy (some programs use 8080 too), the next free port is used and shown. Double-clicking `run_app.bat` again opens the app that is already running.

## Phones, tablets and any screen size (v4.9)

The same Team link works on **phones, tablets, laptops and big monitors** (Chrome, Edge, Safari, Samsung Internet). The phone or tablet must be on the **office Wi-Fi** (same network as the host PC). Nothing to install. Every function is the same: open PDFs, GLASS and DOOR, edit, fill from the drawing, undo / redo, next to check, AI reading, export to Excel.

| Screen | Layout |
|---|---|
| Laptop / desktop (≥ 1101 px) | Same as v4.8: pages · drawing · sheet. Monitors ≥ 2200 px get a wider sheet. |
| Small laptop, iPad landscape (900–1100 px) | Drawing and sheet side by side; the sheet shows compact cards. |
| Phone, iPad portrait (< 900 px) | Bottom bar: **Drawing · Split · Sheet · Check**. Split = drawing above the sheet (portrait) or beside it (landscape). **Drag the grey divider** to give more room to either side (double-tap resets). |

**On a phone or tablet**
* **Zoom the drawing:** pinch with two fingers (or the − / + / Fit buttons). The page toolbar scrolls sideways if it does not fit.
* **Fill a cell from the drawing:** tap the cell, then tap the value on the drawing (same as clicking on a PC). In the *Sheet* view a bar says **Pick on drawing**: tap it, tap the value(s), then **Done** brings you back to the sheet.
* **Next to check:** the **Check** button in the bottom bar (the same as the *To check* tile or the **N** key).
* **⋯ (More)** in the top bar: Undo, Redo, Open PDF, Export all, AI settings, Team link, Shortcuts, Home.
* **^** next to the sheet name hides / shows the totals and filters to give the list more room.
* **Export** downloads the `.xlsx` to the phone / tablet (Downloads / Files app).
* Your chosen view, divider position and mode are remembered on each device.

## Online version (Render) - a link anyone can open

The repo holds a Render Blueprint (`render.yaml`), the same way as Lumen Store. One-time setup:

1. Go to **https://dashboard.render.com** and sign in with GitHub.
2. **New** > **Blueprint** > choose the **muraflex-automation** repo > **Apply**. (If the repo is not listed: *Configure GitHub account* > give Render access to it.)
3. Wait for the first build (~5 min). The link is on the service page, e.g. `https://muraflex-automation-xxxx.onrender.com`. Share it with anyone, on any phone, tablet or PC.

Every push to `main` redeploys automatically.

**What is different online** (`GLASS_PUBLIC=1`)
* Anyone with the link can use it; there is no office-network check.
* **AI settings are locked**, so nobody on the internet can set or use an API key. To turn on AI reading for everyone, set `ANTHROPIC_API_KEY` under the service's *Environment* tab (every visitor's AI reads are then billed to that key).
* The **Team link** button shows the site address.
* Free plan: the site sleeps after 15 min idle (the first visit then takes ~1 min), and uploaded PDFs and saved edits are cleared when it restarts. Export your Excel files before you leave.
* Uploaded PDFs sit on Render's server while the service runs. Use the office version (`run_app.bat`) for confidential client drawings.

## 2. Using the app

0. **Start-up screen.** The home screen shows the AI status (AI ON when `key.txt` is found) and the Team link. **Pick a module**: **GLASS** or **DOOR**. You can also drop PDFs straight onto a card. The ⌂ button (or `H`) goes back home, and the GLASS / DOOR switch in the header changes module without reopening the PDFs.
1. **Open PDF(s).** Click Open PDF, drag the files onto the window, or press Ctrl+O. Several PDFs can be open at once, each in its own tab.
2. **Wait for the automatic read.** Every page is read straight away. A reading window shows the page being read, the progress, the time, live counts (elevations, values, doors, raster / AI pages) and one line per page (VECTOR / RASTER / AI). Text PDFs are so fast the window may not appear at all. **Continue in background** (or Esc) hides it; reading goes on. The page rail shows a thumbnail of every page with its number of elevations, or `none` for cover, key-plan and notes pages.
3. **Review.**
   * Hover a row and its values light up on the drawing: U = upper, L = lower, purple = tag.
   * **Click-to-fill:** click a cell, then click any value on the drawing. Orange dotted boxes mark values that were not used. The cursor then moves to the next cell.
   * **Next to check:** click the orange **To check** tile, or press **N**, to jump to the next elevation / door with an empty cell or a note (it cycles through all of them). The red jump-bar numbers and the *To check only* filter work too.
   * **+ Add panel** adds a panel, **×** removes one, and Ctrl+Z / Ctrl+Y undo and redo. Edits are saved automatically and offered back when the same PDF is opened again.
4. **Export.**
   * **Export to Excel** (Ctrl+E), from either module, writes `<PDF name>.xlsx` with **both tabs: GLASS and DOOR**. The DOOR tab is the empty team template when the PDF has no doors.
   * **Export all** writes one workbook per open PDF into a zip.

**Keyboard:**
* The **arrow keys** move between cells, like Excel.
  * ↑ / ↓ go to the same column above or below, across panels, elevations and doors.
  * ← / → go to the next cell once the caret is at the start or end of the value.
* A cell reached with the arrows has its value selected, so typing replaces it.
* **Enter** goes to the next cell. Press `?` in the app for all shortcuts.

### DOOR module
Each door gets a card laid out like its block on the DOOR sheet: columns **A, B, C1, C2**, rows **Upper / Lower / Total**, Diff under the uppers and FINAL beside the totals.

| Pivot door (FPD, GPD, GHD…) | Sliding door (GSD, FSD, GPSD, GSTD… code ends in SD / STD) |
|---|---|
| **A** = hinge (pivot) side edge: upper / lower from the elevation | **A** = edge at the closed end of the run |
| **B** = latch side edge: upper / lower from the elevation | **B** = inner edge (towards the panel the door slides over) |
| **C1** = swing-plan reading at **45°** open; upper = B's upper | **C1** = far edge of that panel (end of travel) |
| **C2** = swing-plan reading at **90°** open (tip of the open leaf); upper = A's upper | |

**How the swing plan is read.** The plan is a quarter arc drawn around the pivot.
* The end of the arc on the wall line is the **closed** door. Its reading repeats the latch lower and is not used for C1 / C2; it is only a check.
* The other end, where the open leaf stands, is **C2 (90°)**.
* The middle of the arc is **C1 (45°)**.

Each reading is matched to the nearest of these three points, so stray values next to the plan are ignored. When the plan is only written, with no arc, the readings are fitted to where the plan would be: the tip over the hinge, 45° toward the latch, then the closed position.

**Hinge side**, in order of trust:
1. The dashed **V** drawn on the door in elevation (its point is on the hinge side).
2. The **pivot of the swing plan**, which sits over the hinge edge.
3. The closed-door reading, which equals the latch lower.

The card shows *Hinge left / right*. A note appears when the hinge side is missing or unclear, when a swing reading is missing, or when the closed reading is more than 1/8" from the latch lower.

* **Diff** = TOTAL(A) − TOTAL(B). **FINAL** uses the same judgement rules as the GLASS sheet, applied to A and B.
* **Editing:**
  * The **Pivot / Sliding** switch changes the block the door goes to on the DOOR sheet.
  * **⇄ Swap A / B** fixes the hinge side or the sliding direction.
  * **+ Add door** adds a door the reader missed. Untick a door to leave it out.
* **Click-to-fill** works the same as in GLASS. The order is A upper, A lower, B upper, B lower, C1, C2. The C1 / C2 uppers follow B / A automatically.
* Hovering a column highlights that point on the drawing. The closed-door reading is shown as a grey **closed** box.

## 3. What is read

| From the FM PDF | Into the GLASS sheet |
|---|---|
| Circled number next to `ELEVATION / OFFICE 2 #63` | **B ELEV** (first row of the elevation) |
| Glass code + tag (`OLIGL-12` / `63-A`) | **C Tag** |
| Red value above the BM line at each panel edge | **E UPPER** |
| Red value below the BM line at each panel edge | **G LOWER** |
| — | **I TOTAL, K Difference, M JUDGEMENT, O Fraction**: live formulas with stored results |

* **Layout:** each panel gets 2 rows (left edge, then right edge). There is 1 blank row between panels and 2 between elevations. Data starts on row 5, and elevations are sorted by number across all pages.
* **Doors** (FPD, FSD, GPD, GHD…) are not in the GLASS sheet. They are in the DOOR module and the DOOR sheet.
* **Ignored:** width labels (`59"11/16`, `111"`), door-swing plan values and pages without measured elevations.
* **Notation:** `57"1/4`, `49"15/16`, `65' 13/16`, `66 1/16`, `66`, `48'`, `48FT`, `BM 48FT`, `BM 65' 1/4`, `52-5/16`, CAD stacked fractions (`36¹⁄₁₆"`, small raised/lowered digits), `½`, and real feet-inches `5'-6 1/2"`, repeated or prime inch marks (`59 11/16"""`, `59 11/16''`, `59 11/16‴`) are all understood. A fraction stored as a separate word is joined back to its whole number.
* **Mark-up colour:** any colour works. Green uppers with red lowers is fine, and so are values typed as Bluebeam mark-ups or pasted in as pictures (read by OCR).
* **Side views:** an elevation with one measured edge and one glass tag, such as an OFFICE VIEW of a return panel, uses the same values for both edges. It is flagged for checking.
* **No-tag spans:** a span between measured edges that has no glass tag (wall or existing condition) is listed as NO TAG and not exported. Tick it to export it.
* **BY OTHERS glass** (`GL-12 / BY OTHERS`) is listed but not exported, like doors. Tick it to export it.
* **Lowers written under the title** (14092 style) are matched to the nearest frame edge, found from the drawn mullion lines. An edge left blank **between two written edges** gets their **average**, rounded down to 1/16" like the judgement average. Example: 360-C lower = (L2 + L4) / 2 = (60 11/16 + 60 13/16) / 2 = 60 3/4. A blank edge at the **end** of the elevation takes the nearest written one. Both cases are flagged, and the note shows the calculation.
* **Uppers written at only some edges** (14065: 44" at the two end edges only):
  * When the given uppers are all the same value, that value is used at every edge.
  * When they differ, a blank edge between two given ones gets their average (rounded down to 1/16"), and a blank end edge gets the nearest given value.
  * Flagged, with the calculation in the note.
* **One upper for the whole elevation** is used at every edge. An elevation with no upper (for example one marked "Deleted") takes the upper of its neighbour on the same BM line. Both cases are flagged.
* **Stacked lites** (D1 / D2 / D3 in one column) get one row each, with the same edge values. A second lite tag (`1917-DD1`, `720-AA`) is joined to the first: `1917-D1 / 1917-DD1`.
* **Widths and other numbers** outside the BM range (`133 1/4"`, `106 3/8`) are shown as orange values you can click to fill a cell. The GLASS sheet has no width column, so they are never used automatically.

### Judgement rules (same as the team tool)
| Difference between edge totals | JUDGEMENT |
|---|---|
| < 1/4" (SOP: < 3/16") | smaller total |
| 1/4" – < 3/4" | average, rounded **down** to 1/16" |
| 3/4" – 1" | LEVEL FLOOR or CEILING |
| > 1" – 5" | CHECK VALUE ENTERED |
| > 5" | DEFINITELY A TYPO |

## 4. How it works

```
 PDF ──► pdfdoc ─────────► extract ─────────────────────────────────► excel ──► <PDF name>.xlsx
        tokens: text,      1 join split readings ("65'" + "13/16")       GLASS template
        box, colour,       2 values: inch/fraction/FT, bare numbers in    formulas + cached results
        size, direction      mark-up colour; drop word labels ('42" HOLD TO')
        + mark-up glyphs   3 titles (upper-case ELEVATION, not note sentences) + circle number
        + OCR tiles        4 column/row ownership, split refined by glass codes
        + OCR for graphics 5 BM line = the line/label that splits values into two bands
          (hybrid pages)      (dashed segments merged; 'BM 48FT' is a value, not the line)
        + rotation-aware   6 window: edge-label row (DW/FAL/CL) → title; extras far from the band dropped
                           7 optimal alignment of uppers and lowers (tolerates a missing value)
                           8 recover a missing value from the nearest unused reading (flagged)
                           9 tags (also rotated) to spans; side views; no-tag spans; doors separated
                          10 circle number drawn as a picture → OCR of the ring
```

| Module | Role |
|---|---|
| `glassx/units.py` | Inch / fraction parser. Returns the chosen value **and** the alternative readings (never a silent guess) |
| `glassx/pdfdoc.py` | PyMuPDF tokenizer: splits text that has no spaces at visible gaps (`FAL59"7/16111"` becomes 3 tokens); reads mark-up annotations; finds dashed BM lines; tiled OCR for scans |
| `glassx/extract.py` | Elevation and panel extraction (pipeline above) |
| `glassx/judgement.py` | Judgement rules, shared by the Excel formula, the cached values and the UI |
| `glassx/doors.py` | DOOR module: pivot / sliding type, hinge side from the swing plan, A / B / C1 / C2 |
| `glassx/excel.py` | Writes the team GLASS and DOOR templates; puts the computed results into the formula cells so values show even in Protected View |
| `glassx/pipeline.py` | Document store and per-page result cache (bumped automatically when the rules change) |
| `glassx/server.py`, `web/index.html` | Local Flask API and single-page UI |
| `glassx/cli.py` | `--batch`, `--selftest` |
| `glassx/synth.py` | Generator for realistic FM sheets with known answers (tests, fuzzing, self-test) |

## 5. Development

```
pip install -r requirements-dev.txt
python -m pytest                 # 149 tests: parser, judgement, extraction, 4 sheet families, fuzz, rotation, OCR, doors, Excel vs LibreOffice, API
                                 # copy real FM PDFs into tests/real_pdfs/ to also run the real-project regression
python app.py --selftest
python app.py --batch samples    # CLI on the sample PDFs
```
CI (`.github/workflows/tests.yml`) runs the tests and the self-test on Windows and Linux with Python 3.11 and 3.13.

## 6. Settings

| Variable | Default | |
|---|---|---|
| `GLASS_PORT` | 8080 | Port of the app (Team link `http://<IP>:8080`) |
| `GLASS_HOST` | 0.0.0.0 | `0.0.0.0` = office network; `127.0.0.1` = this PC only (same as `--local`) |
| `GLASS_ALLOW` | private ranges | Networks that may connect, comma-separated (for example `192.168.8.0/24`); `*` = everyone |
| `GLASS_PUBLIC` | – | Fixed address or name to show first as the Team link |
| `GLASS_DATA_DIR` | `./glass_data` | PDFs, page cache, saved edits, exports, logs |

Logs are written to `glass_data/logs/glassx.log`.

## 6b. Elevations pasted as pictures

Some FM sheets place the elevation drawing on the template as a **picture**: a scan, a screenshot, or CAD text exported as outlines. 14101 Sherritt is an example. Such a page has no text for the titles or the values.

* **When the reader steps in:** a page whose text layer gives no elevation, but which holds a large picture (or is almost all vector outlines).
* **What it does:** reads that area with OCR, about 10 s per page. Every value on the page is flagged *check every value*.
* **One-glyph fractions** (`54¼`, `49⅝"`, `50⅛"`): OCR reads these wrongly, as `54%4`, `544` or `49%"`. The reader cuts out the glyph after the whole number and compares it with ½ ¼ ¾ ⅛ ⅜ ⅝ ⅞, so `54%4` becomes **54 1/4**.
* **Long titles:** a title longer than one OCR tile is joined back from its two halves.

## 6c. AI reading with Claude (raster / scanned PDFs)

OCR cannot be 100% on raster sheets: hand-written mark-ups, one-glyph fractions and small rotated tags all cause errors. With an Anthropic API key, **Claude reads the drawing the way an estimator does.**

**Set up – easiest way (key file)**
1. Make a text file named **`key.txt`** in the app folder, next to `run_app.bat`.
2. Put the API key in it on one line: `sk-ant-...` (or `ANTHROPIC_API_KEY=sk-ant-...`). Lines starting with `#` are ignored.
3. Start (or restart) the app. The home screen and the header show **AI ON**: AI is switched on by itself with Sonnet 5.5, for picture and scanned pages.
   * Also accepted: `key.text`, `api_key.txt`, `anthropic_key.txt`.
   * The key file wins over a key saved in the AI window, which wins over the `ANTHROPIC_API_KEY` variable.
   * If the AI window says **AI package not installed**: close the app window, double-click **`install_ai.bat`**, wait for *AI package OK*, then start `run_app.bat` again. If it fails, the office proxy is blocking pypi.org: ask IT to allow `pypi.org` and `files.pythonhosted.org`.
   * To switch AI off, delete or rename `key.txt` (or set *When to use AI* to **Off**).
   * **Never share the folder with `key.txt` in it.** The release zip never contains one.

**Set up – in the app (no key file)**
1. Start the app and click the **AI** pill in the header.
2. Paste the API key (`sk-ant-...`) and choose a model:
   * **Claude Sonnet 5.5** (recommended)
   * **Opus 5.5** (most accurate)
   * **Haiku 5.5** (cheapest)
3. Choose when to use AI:
   * **Picture & scanned pages automatically** (default)
   * **Only when I click AI read**
   * **Off**
4. Click **Save**, then **Test connection**.

**Use**
* With *automatically*:
  * **Raster / scanned / picture pages** are read by AI when the PDF is opened (OCR is kept as the fallback and the cross-check).
  * **Vector (text) pages** use their exact text layer, which is free and exact. Only when a vector page is missing values (outlined or pictured numbers) does AI fill **just the empty cells**; values read from the text are never replaced. The page note lists every value AI filled.
  * The reading window shows each page as **VECTOR**, **RASTER** or **AI**.
* **✨ AI read page** (above the drawing) reads the page shown with AI at any time. Ctrl+Z restores the previous read.
* A ✨ next to the count in the page list marks pages read by AI.
* Command line check: `python app.py --ai-check "path\to\file.pdf"` prints what AI read on every page.

**How it works**
1. The page is sent at the model's full high-resolution size (no resizing by the API, so the boxes land exactly on the drawing). Claude returns each elevation's title and area.
2. Each elevation is cropped and sent at full resolution. Claude returns, as a fixed JSON structure, every edge's upper and lower exactly as written, the tags and codes, BY OTHERS, door type, hinge side and the 45° / 90° / closed swing readings, each with its box.
3. **The app does all the maths with its own rules**, the same as for text PDFs: one upper for every edge, a blank edge gets the average of its neighbours, totals, judgement, and door A / B / C1 / C2.
4. **QC:**
   * Every AI value is compared with OCR of the same spot. A different reading is flagged **REQUIRES HUMAN REVIEW** with both values.
   * Anything Claude was unsure of is flagged too.
   * If AI fails (no internet, bad key, rate limit), the OCR read is kept and the page note says why.

**Security and cost**
* The key is stored only on the host PC (`key.txt`, `glass_data\ai_settings.json`, or the `ANTHROPIC_API_KEY` variable). The app never serves `key.txt`. It is never shown or sent to other PCs, and only the host PC can change AI settings.
* With AI on, page images are sent to the Anthropic API, so check that your company allows this for client drawings.
* About 2 + (number of elevations) requests per page. Tokens used this session are shown in the AI window.

## 7. Limits

* **Scanned pages / picture mark-ups:** OCR finds most values, but every OCR elevation is flagged *check every value*. When it cannot read a value, it leaves the cell blank rather than guessing. Use click-to-fill for those cells.
* **Unusual layouts:** values written far from their panel edge, or two elevations drawn in one, can need a correction. The elevation note says what looks wrong.
