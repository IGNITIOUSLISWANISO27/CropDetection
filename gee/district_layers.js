// FieldPriority: Zambia district layers from Google Earth Engine (for Person 1, GIS).  Version 3 (5 Nov 2026)
//
// Produces ONE table, gee_district_layers.csv, with the columns district_id, variable, year, month, value:
//   ndvi          MODIS MOD13Q1 NDVI (250 m), monthly mean over CROPLAND pixels of each district
//   sm_rootzone   SMAP L4 root-zone soil moisture (m3/m3, about 9 km), monthly mean over the district
//   cropland_pct  ESA WorldCover 2021: % of the district classified as cropland      (year 2021, month 0)
//   maize_pct     ESA WorldCereal 2021: % of the district classified as maize        (year 2021, month 0)
// Months or datasets with no images are skipped instead of stopping the script (the Console lists them).
//
// How to run
//   1. Assets > NEW > Shape files: upload the files in gee/zambia_districts_for_gee.zip. Name the asset
//      zambia_districts. Copy its Table ID into DISTRICTS below (keep the quotes).
//   2. Run. Then Tasks > RUN next to gee_district_layers (20-60 minutes).
//   3. Put gee_district_layers.csv from Google Drive in the shared FieldPriority folder.

var DISTRICTS = ee.FeatureCollection('projects/YOUR-PROJECT/assets/zambia_districts');   // <-- your Table ID
var SEASON_START = 2025;            // first year of the season shown (2025 = the 2025/26 season)
var MONTHS = [11, 12, 1, 2, 3, 4];  // season months, in order (Nov and Dec belong to SEASON_START)
var BASELINE_SEASONS = 10;

// ---------------------------------------------------------------- check that DISTRICTS is the right upload
var N_DISTRICTS = DISTRICTS.size().getInfo();
var HAS_ID = ee.List(DISTRICTS.first().propertyNames()).contains('dist_id').getInfo();
if (!HAS_ID || N_DISTRICTS !== 116) {
  throw new Error('DISTRICTS is not the FieldPriority district file: it has ' + N_DISTRICTS + ' districts' +
    (HAS_ID ? '' : ' and no dist_id column') + '. Upload the files inside gee/zambia_districts_for_gee.zip ' +
    '(116 districts) as a new asset and put ITS Table ID in DISTRICTS. Other district files (e.g. GADM ZMB_adm2, ' +
    '72 districts) cannot be matched to the dashboard.');
}
print('Districts OK: 116 with dist_id');

// ---------------------------------------------------------------- datasets (only the ones that exist)
function firstExisting(ids) {
  var cols = [];
  ids.forEach(function (id) {
    try { ee.data.getAsset(id); cols.push(id); } catch (e) { print('Not available (skipped): ' + id); }
  });
  return cols;
}
var SMAP_IDS = firstExisting(['NASA/SMAP/SPL4SMGP/008', 'NASA/SMAP/SPL4SMGP/007']);
var SMAP = SMAP_IDS.length ? ee.ImageCollection(SMAP_IDS[0]) : null;
for (var i = 1; i < SMAP_IDS.length; i++) SMAP = SMAP.merge(ee.ImageCollection(SMAP_IDS[i]));
print('Soil moisture dataset used', SMAP_IDS);

var MODIS = ee.ImageCollection('MODIS/061/MOD13Q1').select('NDVI');
var cropland = ee.ImageCollection('ESA/WorldCover/v200').first().select('Map').eq(40);
var EMPTY = ee.FeatureCollection([]);

// ---------------------------------------------------------------- helpers
function ymOf(seasonStart, m) { return {y: m >= 7 ? seasonStart : seasonStart + 1, m: m}; }

function monthlyStats(col, scale, variable, y, m, prep) {
  // mean image of the month -> mean per district; an empty month gives no rows instead of an error
  var start = ee.Date.fromYMD(y, m, 1);
  var c = col.filterDate(start, start.advance(1, 'month'));
  var rows = ee.FeatureCollection(ee.Algorithms.If(c.size().gt(0),
    prep(c.mean()).reduceRegions({collection: DISTRICTS, reducer: ee.Reducer.mean(), scale: scale, tileScale: 8})
      .filter(ee.Filter.notNull(['mean']))
      .map(function (f) {
        return ee.Feature(null, {district_id: f.get('dist_id'), variable: variable, year: y, month: m,
                                 value: f.get('mean')});
      }),
    EMPTY));
  return rows;
}
function ndviPrep(img) { return img.multiply(0.0001).updateMask(cropland); }
function smPrep(img) { return img.select('sm_rootzone'); }

// ---------------------------------------------------------------- monthly NDVI and soil moisture
var parts = [];
for (var k = 0; k <= BASELINE_SEASONS; k++) {
  var s = SEASON_START - k;
  MONTHS.forEach(function (m) {
    var d = ymOf(s, m);
    if (new Date(d.y, d.m, 1) > new Date()) return;          // month not complete yet
    parts.push(monthlyStats(MODIS, 250, 'ndvi', d.y, d.m, ndviPrep));
    if (SMAP && (d.y > 2015 || (d.y === 2015 && d.m >= 4))) {   // SMAP starts April 2015
      parts.push(monthlyStats(SMAP, 9000, 'sm_rootzone', d.y, d.m, smPrep));
    }
  });
}

// ---------------------------------------------------------------- cropland and maize share (2021 maps)
var area = ee.Image.pixelArea();
function share(mask, variable) {
  var stats = ee.Image.cat(area.updateMask(mask).rename('a'), area.rename('t'));
  return stats.reduceRegions({collection: DISTRICTS, reducer: ee.Reducer.sum(), scale: 100, tileScale: 8})
    .map(function (f) {
      return ee.Feature(null, {district_id: f.get('dist_id'), variable: variable, year: 2021, month: 0,
                               value: ee.Number(f.get('a')).divide(f.get('t')).multiply(100)});
    });
}
parts.push(share(cropland, 'cropland_pct'));
var wc = ee.ImageCollection('ESA/WorldCereal/2021/MODELS/v100').filter(ee.Filter.eq('product', 'maize'));
parts.push(ee.FeatureCollection(ee.Algorithms.If(wc.size().gt(0),
  share(wc.select('classification').mosaic().eq(100), 'maize_pct'), EMPTY)));

var table = ee.FeatureCollection(parts).flatten();
print('Images found: MODIS NDVI', MODIS.filterDate('2015-01-01', '2026-05-01').size(),
      'SMAP', SMAP ? SMAP.filterDate('2015-04-01', '2026-05-01').size() : 0,
      'WorldCereal maize tiles', wc.size());
Export.table.toDrive({collection: table, description: 'gee_district_layers', fileFormat: 'CSV',
                      selectors: ['district_id', 'variable', 'year', 'month', 'value']});
print('Ready: open the Tasks tab and click RUN next to gee_district_layers. ' +
      '(If the Console shows "computation timed out" above, ignore it: the export in Tasks has more time.)');

Map.addLayer(DISTRICTS.style({color: '1F4D3A', fillColor: '00000000'}), {}, 'Districts');
Map.centerObject(DISTRICTS, 6);
