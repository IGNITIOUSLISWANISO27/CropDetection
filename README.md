# FieldPriority: Python pipeline

Screening pipeline, Firebase layer and dashboard for maize fields in the Solwezi pilot (North-Western Province). It flags **possible drought-related
stress** for field verification under the team's 12 rules. It does not confirm drought.

```
GEE rasters + QGIS polygons -> Ingest -> Features -> Scoring -> Explain -> outputs/ -> Firebase -> Streamlit dashboard
                                                                       Kobo form -> validate ----^
```

## Current pilot: Solwezi (North-Western Province), from November 2026
The project now runs on the Solwezi Earth Engine exports. The earlier Chongwe pilot (5 fields, Jan-Mar 2025,
2024/2025 backtests) is retired: its outputs and original alert ledger are kept unchanged in `outputs/chongwe_archive/`,
and its rasters and field polygons in `data/chongwe_archive/raw/` (Sentinel-1 VV left out: too large to transfer).

| Step | How |
|---|---|
| Import Earth Engine exports | `import_gee.bat` (asks for the folder), or `python -m fieldpriority.import_gee --src <folder>` |
| Run the assessment | `run_pipeline.bat` (pipeline, then dashboard). Outputs: `outputs/solwezi/` |
| Add real monthly data | `fetch_solwezi_monthly.bat`: Sentinel-2 NDVI, CHIRPS rainfall + baseline, ERA5-Land temperature, Jan-Apr 2025 |
| Field visits | `validate_kobo.bat` (Alert IDs now `FP-SLZ-<Field_ID>-<date>`) |

What the importer reads: the field shapefile (`Agric_fields_GEE`), per-field CSV statistics (one year), and
`*_Monthly_Soil_Moisture_<year>.csv` (area mean, root zone + surface). It writes `data/solwezi/field_annual.csv`,
`soil_moisture_monthly.csv`, `field_info.csv` and `import_report.json` (which also lists empty rasters).

How the data is used:
* **Soil moisture 2021-2025** is the field's monthly soil moisture, compared with the same month of earlier years
  (rule 3). Root zone 10% or more below that baseline counts as water-deficit evidence
  (`rules.water_deficit.soil_moisture_anomaly_pct_max`, provisional). It replaces any soil moisture rasters.
* **Per-field yearly values** (NDVI mean 0.31, rainfall 1,129 mm, temperature, soil moisture for 2025) are shown as
  context only: a yearly value cannot show a decline within the season.
* **Monthly NDVI is still required** for rule 4. With only the imported files, F001 is "Insufficient data"
  (rule 7), listing what is missing. `fetch_solwezi_monthly.bat` supplies it.
* The legacy relative score needs at least two fields; with one field it is not computed.

Known data issues (Nov 2026 export): F001 is 0.02 ha (about 6 Sentinel-2 pixels including edges): check the polygon.
Six of the seven `.tif` exports are empty (one pixel clipped by a sub-pixel polygon): export rasters over the field
bounds plus a buffer (as `gee/export_season.js` does), or use the CSV statistics.

Real-data check: root-zone soil moisture was 13-17% below its 2021-2023 average in Feb-Apr 2024 (the 2024 drought)
and 12-16% above its 2021-2024 average in Feb-Apr 2025.

## Run
```bash
pip install -r requirements.txt
PYTHONPATH=src python -m fieldpriority.import_gee --src /path/to/gee_exports   # Solwezi exports -> data/solwezi
PYTHONPATH=src python -m fieldpriority.pipeline                 # uses paths.data_dir (data/solwezi)
PYTHONPATH=src python -m fieldpriority.pipeline --data-dir /path/to/exports --out-dir outputs/solwezi
PYTHONPATH=src python -m fieldpriority.pipeline --firebase --cred firebase-key.json   # optional
FIELDPRIORITY_DATA=/path/to/exports pytest -q                   # tests (integration needs data)
```

## Drought-stress rules (model/rules.py, config `rules:`)
The rules decide every field's result. The v1 weighted score is still computed, but only as a relative ranking for
comparison (shown as "legacy score"); it no longer sets the alert.

| Rule | How it is applied |
|---|---|
| 1 Drought-related maize stress only | `config/field_info.csv` crop must be maize; other crops are "Not assessed" |
| 2 Field ID, location, assessment date, usable data | Missing any of these, crop type, March rainfall + baseline, or usable NDVI (>= 50 % cloud-free) gives Insufficient data. Data ending more than 45 days before `--assessment-date` is not usable |
| 3 Seasonal baselines | Rainfall vs CHIRPS 2015-2024 mean for the same month. NDVI vs a multi-year same-month baseline when `ndvi_baseline_mXX` exists; until then vs this season's earlier peak (lowers data confidence) |
| 4 Deficit + decline together | Rainfall <= -25 % of baseline (assessment month or the month before) AND NDVI drop >= 0.05 and >= 8 % -> **Possible drought stress** |
| 5 Decline without deficit | **Crop stress—cause uncertain** (risk "Not attributed"); queued as a cause check, not a drought alert |
| 6 Growth stage | Stage from `planting_date` (days after planting) or a recorded `stage`. Decline at maturity/harvest = expected drying, not drought. Unknown stage caps risk at Moderate and asks for the stage |
| 7 Insufficient data, not Low | Separate risk level "Insufficient data"; never queued as a control |
| 8 Explanations | Each result lists what changed (value vs baseline), contributing indicators and what to check |
| 9 Separate labels | `risk_level`, `data_confidence` and `verification_status` are separate fields everywhere |
| 10 Kobo linking, original prediction kept | `outputs/alerts_issued.csv` is append-only. Visits link by Field ID + Alert ID and carry the issued prediction; a re-run never changes it. Alerts issued by the v1 score are kept as issued |
| 11 TEST excluded | `record_type = test`, or TEST in the alert, field or verifier ID |
| 12 Verification, not treatment | Next actions recommend field verification or extension officer assessment only (tested) |

Outcomes: Possible drought stress (High / Moderate), Crop stress—cause uncertain (Not attributed),
Water deficit—no vegetation decline yet (Watch), Drying consistent with crop maturity (Low), No drought-stress signal (Low),
Insufficient data, Not assessed. High needs a marked decline (>= 0.10) or a sensitive stage (tasselling/silking, grain filling).
Data confidence: High with no issues, Medium with one, Low with two or more (no multi-year NDVI baseline, unknown stage,
small field). **All thresholds are provisional and need agricultural review.**

To improve confidence: add `planting_date` per field to `config/field_info.csv`, and add multi-year NDVI baselines.

## Layers (match the system diagram)
| Layer | Module | Does |
|---|---|---|
| Ingest | `ingest/fields.py`, `ingest/rasters.py` | Validates polygons (Polygon only, EPSG:4326), finds rasters by filename, prefers `_1` re-exports, reports missing months |
| Features | `features/zonal.py`, `features/indicators.py` | Zonal mean/median per field, valid-pixel fractions, climate-cell IDs and which fields share a cell, monthly series, latest-month and month-to-month change, rainfall % anomaly |
| Scoring | `model/normalise.py`, `scoring.py`, `confidence.py` | 4-component weighted score, classes, driver breakdown, confidence |
| Explain | `explain/reasons.py` | Plain-language reasons with the agreed caveats |
| Storage | `storage/local.py`, `firebase_client.py` | CSV/JSON/GeoJSON, optional Firestore |

## Outputs (`outputs/`)
`indicators_monthly.csv` (long), `indicators_season.csv` (one row per field), `risk_assessments.csv/.json`
(priority, score, confidence, reasons), `fields_assessed.geojson` (for the map), `pipeline_report.json`
(rasters used, data-quality notes, replication check).

## Method and assumptions
- **Primary score replicates v1**: equal weights (0.25 x greenness, rainfall, soil moisture, temperature),
  each min-max scaled across the pilot fields. The test suite reproduces the v1 `Integrated_Stress` exactly.
- **It is a relative ranking.** With 5 fields one is always 1.0 and one 0.0 per component.
- **Greenness** is the Jan-Mar Sentinel-2 median-composite NDVI (existing `NDVI_Mean`), called relative
  vegetation greenness. It is never labelled an NDVI anomaly (needs a multi-year baseline).
- **Rainfall anomaly** is mm/month versus the CHIRPS 2015-2024 mean (season mean and latest month are both kept).
  Rainfall, soil moisture and temperature are coarse cell values shared by nearby fields.
- **Sentinel-1 VV** is context only and is not part of the score.
- **Experimental fixed-reference score** (`ref_method_*`) uses provisional ranges in `config/settings.yaml`
  for greenness and rainfall only. Soil moisture and temperature are excluded until a baseline exists.
- **Class thresholds** (0.25 / 0.50) are provisional; v1 had only High/Low.
- **Confidence** measures data support, not accuracy. It is capped at 0.85 until verified results exist.


## Kobo verification and validation metrics

```
pipeline  -> outputs/verification_queue.csv      (Alert ID + Field ID list for the verifiers; SOP section 3)
Kobo form -> export CSV (keep the original unchanged)
validate  -> outputs/verification_records.csv    (every record with its quality flags)
          -> outputs/validation_register.csv     (same columns as FieldPriority_Validation_Register_v1.xlsx)
          -> outputs/validation_metrics.json
```
```powershell
python -m fieldpriority.pipeline --alert-date 2026-10-21       # issues Alert IDs: FP-CHG-<Field_ID>-<YYYYMMDD>
python -m fieldpriority.pipeline --alert-date 2026-10-21 --assessment-date 2026-10-20   # current-season run
python -m fieldpriority.validate --kobo-csv "path\to\kobo_export.csv" --assessments outputs\risk_assessments.json
# or straight from Kobo:  set KOBO_SERVER / KOBO_TOKEN / KOBO_ASSET_UID, then  --kobo-api   (untested)
```

**Straight from Kobo.** The form is set in `config/settings.yaml` (`kobo: server: https://eu.kobotoolbox.org`,
`asset_uid: aEBzGzmTMDb2XB87ZfKKNM`). Copy `.env.example` to `.env` and put your API key in `KOBO_TOKEN`
(Kobo > Account settings > Security). `.env` is git-ignored; never commit or share the key. Then:
```powershell
$env:PYTHONPATH="src"; python -m fieldpriority.ingest.kobo     # checks token, form and required columns
.\validate_kobo.bat                                             # check + download + validate
```
Each download is kept unchanged in `outputs\kobo_raw\` (SOP: retain original exports).

**Quality checks** (SOP section 7, `validation/quality.py`): IDs present and matched to an issued alert, permission,
crop/stage, evidence, alternative causes considered, verdict and a reason of at least 15 characters, photos
(warning only), privacy (phone/email patterns), dates, and consistency rules (e.g. flowering concern at an early
stage, irrigation operating on a rain-fed field, soil vs waterlogging, verdict vs main cause).
Statuses use the register's values. The automatic result is only a *suggestion*; per the SOP the validation lead
assigns the final status in Kobo (`_validation_status`). With `require_human_status: true` only records the
lead has approved count towards metrics.

**Metrics** (`validation/metrics.py`, current model version only): correct alerts (Confirmed), false alerts (Rejected),
uncertain (reported separately), cause checks (reported separately), missed detections (Watch/Low control field Confirmed), verification rate, and verification lag
(visit date minus alert date). Lag is not warning lead time; that needs the date stress began, which the form
does not collect. Rates carry 95% Wilson intervals and are marked `descriptive_only` below 10 decided visits.
TEST records and simulated test data never count.

**Important:** the assessment is based on Jan-Mar 2025 imagery, so a visit in a later season cannot validate it.
Run the pipeline on current-season rasters and issue alerts from that run before verifying.

### Recommended changes to the Kobo form (v1.0)
1. Make `field_id` and `alert_id` `select_one` lists taken from `verification_queue.csv`, not free text.
2. Add a `constraint` so `verdict_reason` has a minimum length.
3. Show `flowering_concern` only when the stage is tasselling/silking or later.
4. Add a `geopoint` question once the SOP sets the GPS procedure.
5. Prefill or hide `system_risk` so it cannot differ from the stored alert.

## Backtest: checking accuracy before field visits exist
`python -m fieldpriority.backtest` (or `run_backtest.bat`) replays past seasons month by month with the same rules and
compares the result with what is known to have happened (`config/backtest_reference.csv`):
* **2024 (known drought):** dry spell from January 2024, national disaster declared 29 Feb 2024, Lusaka Province affected.
  The system should flag possible drought stress, ideally by the end of February.
* **2025 (known good season):** maize harvest 3.66 million t vs 1.5 million t the year before. It should stay quiet.
  Current result: no false drought alerts (0 of 5 fields, Feb and Mar 2025).

**Real 2024 data without Earth Engine:** `fetch_2024_data.bat` (or `python -m fieldpriority.fetch_data --year 2024`)
downloads real Jan-Mar 2024 data for the five fields from free public sources, no accounts: Sentinel-2 NDVI (AWS
Earth Search, clouds masked, monthly median), CHIRPS rainfall and its anomaly against 2014-2023, and ERA5-Land
temperature and soil moisture (Open-Meteo). It writes `data/backtest_2024/` plus `sources_2024.json` listing every
satellite scene used, then runs the backtest. Other years: `--year 2019 --months 1 2 3`. Expect 10-30 minutes and a
few hundred MB of downloads (cached in `_download_cache/`). Tested only against simulated servers so far.

Alternatively, to add 2024 with Earth Engine: in `gee/export_season.js` set `SEASON = ['2024-01', '2024-02', '2024-03']` and
`BASELINE_YEARS = [2014, 2023]` (so the drought year is not inside its own baseline), export, and put the files in
`data/backtest_2024/`. Note the printed rules fingerprint BEFORE running it: it proves the thresholds were not tuned
after seeing the answer. Results: `outputs/backtest/` and the Performance page. The real alert ledger is never touched.
This is area-level evidence, not field-level accuracy; field verification remains the real measure.

## Dashboard (Streamlit)

```powershell
pip install -r requirements.txt
python -m fieldpriority.pipeline --alert-date 2026-10-11      # once; writes outputs\
python -m fieldpriority.validate --kobo-csv "path\to\kobo_export.csv"   # optional, adds verification results
run_dashboard.bat                                             # or:  python -m streamlit run app\Home.py
```
The dashboard never recomputes scores; it only reads data through `storage/repository.py`.
With no Firebase key it reads the local `outputs\` folder; with a key it reads Firebase (sidebar: Data source).

| Page | Shows |
|---|---|
| Home | Ranked list of fields to visit first, why, verification status, honest status warnings |
| Risk map | Fields on satellite or street map, coloured by priority or any indicator score; zoom to a field |
| Field detail | Contribution of each indicator (field-level vs regional), reasons, monthly charts, method comparison, visits |
| Verify queue | Alert IDs for the Kobo form, submissions with data-quality problems, SOP checklist, downloads |
| Performance | Correct and false alerts, missed detections, verification rate with 95% ranges, quality of submissions |

The map needs an internet connection in the browser (Leaflet and Esri imagery tiles).

### Firebase setup
Firebase must be created in your own Google account (it cannot be created from code).
1. https://console.firebase.google.com > Add project (Google Analytics is not needed).
2. Build > Firestore Database > Create database > production mode. Pick the region nearest to Zambia that is offered; it cannot be changed later.
3. Project settings (gear icon) > Service accounts > Generate new private key. Save the downloaded file as `firebase-key.json` in this folder.
4. `python -m pip install firebase-admin`
5. `python -m fieldpriority.firebase_check`   (confirms the key, the database and read/write access, and explains any failure)
6. `.\sync_firebase.bat`   (checks, then pushes `outputs\` to Firebase). Then `.\run_dashboard.bat`: Data source "Automatic" now reads Firebase.

The key file gives full admin access to the project. Never commit it, email it or paste it into chat; `.gitignore` already excludes
`firebase-key.json` and `keys/`. Access rules: `firestore.rules` denies all browser and app access; the pipeline and dashboard use the
Admin SDK, which is not affected. Optional: deploy the rules with the Firebase CLI (`firebase deploy --only firestore:rules`).

Collections: `fields`, `indicators`, `season_features`, `risk_assessments`, `alerts`, `verifications`, `metrics`, `runs`, `meta`.
Verification records contain verifier IDs and observations, never names or phone numbers (the quality checks flag these).
The Firebase writer and reader are tested against an in-memory fake Firestore, not a live project, so the first real sync is the real test.
Check the current free-plan limits on the Firebase pricing page; this pilot stores a few hundred small documents.

### Dashboard warnings
Home warns when the imagery period ended long before the alert date. For a deliberate past-season pilot, set
`dashboard: stale_data_warning: false` in `config/settings.yaml`.
