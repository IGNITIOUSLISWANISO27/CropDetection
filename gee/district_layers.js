// FieldPriority: Zambia district layers from Google Earth Engine (for Person 1, GIS).
//
// Produces ONE table, gee_district_layers.csv, with the columns district_id, variable, year, month, value:
//   ndvi          MODIS MOD13Q1 NDVI (250 m), monthly mean over CROPLAND pixels of each district
//   sm_rootzone   SMAP L4 root-zone soil moisture (m3/m3, about 9 km), monthly mean over the district
//   cropland_pct  ESA WorldCover 2021: % of the district classified as cropland      (year 2021, month 0)
//   maize_pct     ESA WorldCereal 2021: % of the district classified as maize        (year 2021, month 0)
//
// How to run
//   1. Assets > NEW > Shape files: upload gee/zambia_districts_for_gee.zip (all files in it). Name the asset
//      zambia_districts. Copy its asset ID into DISTRICTS below.
//   2. Set the season months below (same months as the dashboard's district layers; see national_report.json
//      "window"). Baseline: the 10 seasons before (NDVI) and every season since 2015 (SMAP).
//   3. Run, then Tasks > RUN the export. Download the CSV from Google Drive, save it as
//      data\national\gee_district_layers.csv in the fieldpriority folder, and run monthly_update.bat
//      (or: python -m fieldpriority.national.build).

var DISTRICTS = ee.FeatureCollection('projects/YOUR-PROJECT/assets/zambia_districts');   // <-- change
var SEASON_START = 2025;            // first year of the season shown (2025 = the 2025/26 season)
var MONTHS = [11, 12, 1, 2, 3, 4];  // season months, in order (Nov and Dec belong to SEASON_START)
var BASELINE_SEASONS = 10;

// ---------------------------------------------------------------- helpers
function ymOf(seasonStart, m) { return {y: m >= 7 ? seasonStart : seasonStart + 1, m: m}; }

var cropland = ee.ImageCollection('ESA/WorldCover/v200').first().select('Map').eq(40);

function monthlyStats(img, variable, y, m, scale) {
  return img.reduceRegions({collection: DISTRICTS, reducer: ee.Reducer.mean(), scale: scale, tileScale: 4})
    .map(function (f) {
      return ee.Feature(null, {district_id: f.get('dist_id'), variable: variable, year: y, month: m,
                               value: f.get('mean')});
    });
}

function ndviMonth(y, m) {
  var start = ee.Date.fromYMD(y, m, 1);
  var img = ee.ImageCollection('MODIS/061/MOD13Q1').filterDate(start, start.advance(1, 'month'))
    .select('NDVI').mean().multiply(0.0001).updateMask(cropland);
  return monthlyStats(img, 'ndvi', y, m, 250);
}

function smMonth(y, m) {
  var start = ee.Date.fromYMD(y, m, 1);
  var img = ee.ImageCollection('NASA/SMAP/SPL4SMGP/007').filterDate(start, start.advance(1, 'month'))
    .select('sm_rootzone').mean();
  return monthlyStats(img, 'sm_rootzone', y, m, 9000);
}

// ---------------------------------------------------------------- monthly NDVI and soil moisture
var parts = [];
for (var k = 0; k <= BASELINE_SEASONS; k++) {
  var s = SEASON_START - k;
  MONTHS.forEach(function (m) {
    var d = ymOf(s, m);
    var end = new Date(d.y, d.m, 1);                 // first day of the next month
    if (end > new Date()) return;                    // month not complete yet
    parts.push(ndviMonth(d.y, d.m));
    if (d.y > 2015 || (d.y === 2015 && d.m >= 4)) parts.push(smMonth(d.y, d.m));   // SMAP starts Apr 2015
  });
}

// ---------------------------------------------------------------- cropland and maize share (2021 maps)
var area = ee.Image.pixelArea();
function share(mask, variable) {
  var stats = ee.Image.cat(area.updateMask(mask).rename('a'), area.rename('t'));
  return stats.reduceRegions({collection: DISTRICTS, reducer: ee.Reducer.sum(), scale: 100, tileScale: 4})
    .map(function (f) {
      return ee.Feature(null, {district_id: f.get('dist_id'), variable: variable, year: 2021, month: 0,
                               value: ee.Number(f.get('a')).divide(f.get('t')).multiply(100)});
    });
}
var maize = ee.ImageCollection('ESA/WorldCereal/2021/MODELS/v100').filter(ee.Filter.eq('product', 'maize'))
  .select('classification').mosaic().eq(100);
parts.push(share(cropland, 'cropland_pct'));
parts.push(share(maize, 'maize_pct'));

var table = ee.FeatureCollection(parts).flatten();
print('Rows (first 5)', table.limit(5));
Export.table.toDrive({collection: table, description: 'gee_district_layers', fileFormat: 'CSV',
                      selectors: ['district_id', 'variable', 'year', 'month', 'value']});

Map.addLayer(DISTRICTS.style({color: '1F4D3A', fillColor: '00000000'}), {}, 'Districts');
Map.addLayer(maize.selfMask(), {palette: ['D9A21B']}, 'WorldCereal maize 2021', false);
Map.centerObject(DISTRICTS, 6);
