"""PDF, Excel and GeoJSON exports for the Reports page. Built only from the data the dashboard shows."""
import datetime as dt
import io
import json

import pandas as pd

from _lib import RISK, RISK_ORDER, CFG, field_location, status_by_field, period_text, visits


def _logo_drawing(size=34):
    from reportlab.graphics.shapes import Drawing, Rect, Line, Polygon, Circle
    from reportlab.lib.colors import HexColor
    d = Drawing(size, size)
    k = size / 48
    d.add(Rect(0, 0, 48 * k, 48 * k, rx=12 * k, ry=12 * k, fillColor=HexColor("#1F4D3A"), strokeColor=None))
    for y in (10, 17):
        d.add(Line(8 * k, y * k, 40 * k, y * k, strokeColor=HexColor("#3E8E5A"), strokeWidth=2 * k))
    d.add(Polygon([24 * k, 17 * k, 30 * k, 33 * k, 37 * k, 39 * k, 36 * k, 30 * k], fillColor=HexColor("#D9A21B"), strokeColor=None))
    d.add(Circle(15 * k, 32 * k, 3.2 * k, fillColor=None, strokeColor=HexColor("#FAF8F2"), strokeWidth=2 * k))
    return d


def _map_png(data, A):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    g = data.fields[data.fields["Field_ID"].isin(A["field_id"])].to_crs(3857)
    lv = A.drop_duplicates("field_id", keep="last").set_index("field_id")["risk_level"]
    fig, ax = plt.subplots(figsize=(6.2, 3.6), dpi=160)
    for r in g.itertuples():
        col = RISK.get(lv[r.Field_ID], {}).get("color", "#7A8590")
        gs = [r.geometry] if r.geometry.geom_type == "Polygon" else list(getattr(r.geometry, "geoms", [r.geometry]))
        for p in gs:
            x, y = p.exterior.xy
            ax.fill(x, y, color=col, alpha=.75, ec="#1E2A24", lw=1)
        c = r.geometry.centroid
        ax.annotate(r.Field_ID, (c.x, c.y), xytext=(6, 6), textcoords="offset points", fontsize=8, weight="bold")
    minx, miny, maxx, maxy = g.total_bounds
    pad = max(maxx - minx, maxy - miny, 200) * .6
    ax.set_xlim(minx - pad, maxx + pad)
    ax.set_ylim(miny - pad, maxy + pad)
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    ax.set_facecolor("#F1ECE0")
    sb = 10 ** int(len(str(int(pad))) - 1)
    ax.plot([minx - pad * .85, minx - pad * .85 + sb], [miny - pad * .85] * 2, color="#1E2A24", lw=2)
    ax.text(minx - pad * .85, miny - pad * .78, f"{sb:,.0f} m", fontsize=7)
    ax.set_title("Field boundaries coloured by risk class (Web Mercator, no basemap)", fontsize=8, color="#5E6B63")
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf


def _bar_png(A):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    counts = A["risk_level"].value_counts()
    levels = [k for k in RISK_ORDER if k != "Not assessed" or counts.get(k)]
    fig, ax = plt.subplots(figsize=(6.2, 2.4), dpi=160)
    vals = [int(counts.get(k, 0)) for k in levels]
    ax.barh([RISK[k]["short"] for k in levels][::-1], vals[::-1], color=[RISK[k]["color"] for k in levels][::-1])
    for i, v in enumerate(vals[::-1]):
        ax.text(v + .05, i, str(v), va="center", fontsize=8)
    ax.set_xlabel("Number of fields", fontsize=8)
    ax.tick_params(labelsize=8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.xaxis.get_major_locator().set_params(integer=True)
    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf


def build_pdf(data, A, filters):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                            title="FieldPriority assessment report", author="FieldPriority")
    ss = getSampleStyleSheet()
    H = ParagraphStyle("H", parent=ss["Heading1"], textColor=colors.HexColor("#1F4D3A"), fontSize=18, spaceAfter=2)
    H2 = ParagraphStyle("H2", parent=ss["Heading2"], textColor=colors.HexColor("#1F4D3A"), fontSize=12.5, spaceBefore=10)
    B = ParagraphStyle("B", parent=ss["BodyText"], fontSize=9.2, leading=12.5)
    S = ParagraphStyle("S", parent=B, textColor=colors.HexColor("#5E6B63"), fontSize=8)
    status = status_by_field(data)
    now = dt.datetime.now().strftime("%d %b %Y %H:%M")
    head = Table([[_logo_drawing(), Paragraph("<b>FieldPriority</b><br/>Maize drought-risk assessment report", H)]],
                 colWidths=[14 * mm, 160 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    el = [head, Paragraph(f"{CFG['pilot_area']} · Assessment period {period_text(data)} · Generated {now}", S), Spacer(1, 6)]
    fl = "; ".join(f"{k}: {v}" for k, v in filters.items() if v) or "none"
    el.append(Paragraph(f"<b>Filters applied:</b> {fl}", S))

    n = len(A)
    counts = A["risk_level"].value_counts().to_dict()
    verified = sum(1 for f in A["field_id"] if status.get(f, "").startswith("Verified"))
    complete = int((A["missing_data"].map(len) == 0).sum()) if n else 0
    el.append(Paragraph("Summary", H2))
    flagged = counts.get("High", 0) + counts.get("Moderate", 0)
    el.append(Paragraph(
        f"{n} field{'s' if n != 1 else ''} assessed. {flagged} flagged for possible drought stress (High or Moderate), "
        f"{counts.get('Watch', 0)} on Watch, {counts.get('Low', 0)} Low, {counts.get('Insufficient data', 0)} with insufficient data. "
        f"{verified} verified in the field. {complete} of {n} had every input the rules need.", B))
    findings = []
    for r in A.to_dict("records"):
        findings.append(f"<b>{r['field_id']}</b> – {RISK.get(r['risk_level'], {}).get('short', r['risk_level'])}: "
                        f"{r['outcome']}. Data confidence {r['data_confidence']}. {status.get(r['field_id'])}.")
    if findings:
        el.append(Paragraph("Key findings", H2))
        for f in findings[:12]:
            el.append(Paragraph("• " + f, B))
    if n:
        el.append(Paragraph("Risk-class distribution", H2))
        el.append(Image(_bar_png(A), width=170 * mm, height=66 * mm))
        el.append(Paragraph("Field map", H2))
        el.append(Image(_map_png(data, A), width=170 * mm, height=99 * mm))
        el.append(Paragraph("Assessed fields", H2))
        rows = [["Field", "Risk class", "Result", "Confidence", "Verification", "Area (ha)", "Centre (lat, lon)"]]
        for r in A.to_dict("records"):
            loc = field_location(data, r["field_id"])
            area = float(data.fields.set_index("Field_ID").loc[r["field_id"], "area_ha"])
            rows.append([r["field_id"], RISK.get(r["risk_level"], {}).get("short", r["risk_level"]),
                         Paragraph(str(r["outcome"]), S), r["data_confidence"], Paragraph(status.get(r["field_id"], ""), S),
                         f"{area:.2f}", f"{loc['lat']:.5f}, {loc['lon']:.5f}"])
        t = Table(rows, colWidths=[16 * mm, 22 * mm, 44 * mm, 18 * mm, 30 * mm, 15 * mm, 30 * mm], repeatRows=1)
        st_ = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4D3A")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
               ("FONTSIZE", (0, 0), (-1, -1), 7.6), ("GRID", (0, 0), (-1, -1), .25, colors.HexColor("#CFC6B2")),
               ("VALIGN", (0, 0), (-1, -1), "TOP")]
        for i, r in enumerate(A.to_dict("records"), 1):
            st_.append(("BACKGROUND", (1, i), (1, i), colors.HexColor(RISK.get(r["risk_level"], {}).get("color", "#7A8590"))))
            st_.append(("TEXTCOLOR", (1, i), (1, i), colors.HexColor(RISK.get(r["risk_level"], {}).get("text", "#FFFFFF"))))
        t.setStyle(TableStyle(st_))
        el.append(t)
    el.append(Paragraph("Data sources and method", H2))
    src = CFG.get("sources", {})
    el.append(Paragraph(
        f"Crop greenness: {src.get('ndvi')}. Rainfall: {src.get('rainfall')} against {src.get('rainfall_baseline')}. "
        f"Soil moisture: {src.get('soil_moisture')}. Temperature: {src.get('temperature')}. Field visits: KoboToolbox. "
        "Risk classes come from the FieldPriority drought-stress rules (provisional thresholds, config/settings.yaml). "
        "They are screening results, not confirmed drought; field verification decides. Field boundaries are digitised "
        "estimates until checked on the ground.", B))
    el.append(Spacer(1, 6))
    el.append(Paragraph(f"FieldPriority {data.meta.get('model_version') or CFG.get('model_version')} · data source: {data.source_note}", S))
    doc.build(el)
    buf.seek(0)
    return buf.getvalue()


def build_excel(data, A):
    status = status_by_field(data)
    buf = io.BytesIO()
    rows = []
    for r in A.to_dict("records"):
        loc = field_location(data, r["field_id"])
        rows.append({"Field ID": r["field_id"], "Risk class": r["risk_level"], "Result": r["outcome"],
                     "Data confidence": r["data_confidence"], "Verification": status.get(r["field_id"]),
                     "Growth stage": r.get("growth_stage_label"), "Assessed for": r.get("assessment_date"),
                     "Data up to": r.get("data_end_date"), "Alert ID": r["alert_id"],
                     "Area (ha)": float(data.fields.set_index("Field_ID").loc[r["field_id"], "area_ha"]),
                     "Latitude": loc["lat"], "Longitude": loc["lon"], "Location": loc["district"],
                     "Missing data": "; ".join(r.get("missing_data") or []),
                     "Recommended follow-up": r.get("next_action")})
    ind = []
    for r in A.to_dict("records"):
        for i in (r.get("explanation") or {}).get("indicators") or []:
            ind.append({"Field ID": r["field_id"], **i})
    V = visits(data)
    vcols = ["field_id", "field_id_pipeline", "alert_id", "matched_alert_id", "visit_date", "district", "verifier_id",
             "maize_stage", "overall_condition", "soil_condition", "main_cause", "field_verdict", "verdict_reason",
             "validation_status_final", "analysis_eligible", "flag_codes"]
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame(rows).to_excel(xw, sheet_name="Assessments", index=False)
        pd.DataFrame(ind).to_excel(xw, sheet_name="Indicators", index=False)
        (V[[c for c in vcols if c in V]] if len(V) else pd.DataFrame(columns=vcols)).to_excel(xw, sheet_name="Field visits", index=False)
        L = data.ledger if data.ledger is not None else pd.DataFrame()
        L[L["field_id"].isin(A["field_id"])].to_excel(xw, sheet_name="History (issued)", index=False) if len(L) else \
            pd.DataFrame().to_excel(xw, sheet_name="History (issued)", index=False)
        pd.DataFrame([{"Item": "Pilot area", "Value": CFG["pilot_area"]}, {"Item": "Period", "Value": period_text(data)},
                      {"Item": "Generated", "Value": dt.datetime.now().isoformat(timespec="minutes")},
                      {"Item": "Data source", "Value": data.source_note}]
                     + [{"Item": f"Source: {k}", "Value": v} for k, v in CFG.get("sources", {}).items()]
                     ).to_excel(xw, sheet_name="About", index=False)
        for ws in xw.book.worksheets:
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = min(48, max(10, max(len(str(c.value or "")) for c in col) + 2))
    buf.seek(0)
    return buf.getvalue()


def build_geojson(data, A):
    status = status_by_field(data)
    g = data.fields[data.fields["Field_ID"].isin(A["field_id"])].merge(
        A[["field_id", "risk_level", "outcome", "data_confidence", "alert_id", "assessment_date"]],
        left_on="Field_ID", right_on="field_id").drop(columns="field_id")
    g["verification"] = g["Field_ID"].map(status)
    g["boundary_status"] = "digitised estimate, not field-verified"
    return g.to_crs(4326).to_json(drop_id=True).encode()
