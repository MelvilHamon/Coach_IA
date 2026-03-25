"""
dashboard/callbacks.py — Tous les callbacks Dash (enregistrés via @app.callback).
"""

import json as _json
import os

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, State, html, dcc, no_update, ctx
from dash.exceptions import PreventUpdate

from app import app
from data import get_review, gps_file, load_activities, load_gps, stream_file
from layout import (
    PLOTLY_TEMPLATE, _AX_STYLE,
    _ACCENT, _BGCARD, _BORDER, _BG, _DANGER, _INK,
    _INK_LT, _INK_MID, _SUCCESS, _WARNING,
    _acwr_color, _badge, _fmt, _risk_color, _section_title, _row,
    _make_ef_chart, _make_pace_chart, _make_vo2_chart,
    render_analyse, render_charge, render_history,
    render_overview, render_progression,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 1. Navigation principale ──────────────────────────────────────────────────

_TAB_IDS = [
    "tab-overview", "tab-history", "tab-progression",
    "tab-charge",   "tab-analyse",
]
_TAB_RENDERERS = {
    "tab-overview":    render_overview,
    "tab-history":     render_history,
    "tab-progression": render_progression,
    "tab-charge":      render_charge,
    "tab-analyse":     render_analyse,
}


@app.callback(
    [Output("page-content", "children")] +
    [Output(tid, "className") for tid in _TAB_IDS],
    [Input(tid, "n_clicks") for tid in _TAB_IDS],
    prevent_initial_call=True,
)
def navigate(*_):
    active = ctx.triggered_id or "tab-overview"
    if active not in _TAB_RENDERERS:
        active = "tab-overview"

    try:
        content = _TAB_RENDERERS[active]()
    except Exception as e:
        content = html.Div(
            f"Erreur de rendu : {e}",
            style={"fontFamily": "JetBrains Mono, monospace",
                   "fontSize": "11px", "color": _DANGER, "padding": "32px"},
        )
    classes = [
        "ca-nav-tab active" if tid == active else "ca-nav-tab"
        for tid in _TAB_IDS
    ]
    return [content] + classes


# ── 2. Historique — table + dropdown review ───────────────────────────────────

@app.callback(
    [
        Output("hist-table-container",  "children"),
        Output("hist-review-selector",  "options"),
        Output("hist-review-selector",  "value"),
        Output("hist-period-30",  "className"),
        Output("hist-period-90",  "className"),
        Output("hist-period-all", "className"),
    ],
    [
        Input("hist-filter-type", "value"),
        Input("hist-period-30",   "n_clicks"),
        Input("hist-period-90",   "n_clicks"),
        Input("hist-period-all",  "n_clicks"),
    ],
    prevent_initial_call=True,
)
def update_history_table(sel_type, n30, n90, nall):
    triggered = ctx.triggered_id or "hist-period-all"

    if triggered == "hist-period-30":
        period = "30j"
    elif triggered == "hist-period-90":
        period = "90j"
    else:
        period = "all"

    cls_30  = "ca-radio-btn active" if period == "30j" else "ca-radio-btn"
    cls_90  = "ca-radio-btn active" if period == "90j" else "ca-radio-btn"
    cls_all = "ca-radio-btn active" if period == "all" else "ca-radio-btn"

    df = load_activities().sort_values("Date", ascending=False)

    if sel_type and sel_type != "Tous":
        df = df[df["session_type"] == sel_type]

    if period == "30j":
        cutoff = df["Date"].max() - pd.Timedelta(days=30)
        df = df[df["Date"] >= cutoff]
    elif period == "90j":
        cutoff = df["Date"].max() - pd.Timedelta(days=90)
        df = df[df["Date"] >= cutoff]

    table = _build_history_table(df)

    opts = [
        {
            "label": (
                f"{row['Date'].strftime('%d/%m/%Y')} — "
                f"{str(row.get('Nom',''))[:28]} "
                f"[{row.get('session_type','')}]"
            ),
            "value": int(row["ID"]),
        }
        for _, row in df.head(200).iterrows()
    ]
    val = opts[0]["value"] if opts else None

    return table, opts, val, cls_30, cls_90, cls_all


def _build_history_table(df: pd.DataFrame) -> html.Div:
    """Construit le tableau HTML de l'historique. Accessible depuis layout.py."""
    if df.empty:
        return html.Div(
            "Aucune activité pour cette période.",
            style={"fontFamily": "JetBrains Mono, monospace",
                   "fontSize": "11px", "color": _INK_LT, "padding": "24px 0"},
        )
    rows = []
    for _, row in df.iterrows():
        date_str = row["Date"].strftime("%d/%m/%Y")
        nom      = str(row.get("Nom", ""))[:30]
        stype    = str(row.get("session_type", ""))
        dist     = _fmt(row.get("Distance (km)"), " km")
        pace     = row.get("pace_display", "—")
        trimp    = _fmt(row.get("trimp"), decimals=0)
        acwr_v   = row.get("acwr_km")
        acwr_str = _fmt(acwr_v, decimals=2)
        risk     = str(row.get("injury_risk_label", "—"))

        rows.append(html.Tr([
            html.Td(date_str,  className="dim"),
            html.Td(nom,       className="dim"),
            html.Td(_badge(stype)),
            html.Td(dist),
            html.Td(pace),
            html.Td(trimp),
            html.Td(acwr_str, style={"color": _acwr_color(acwr_v)}),
            html.Td(risk,
                    style={"color": _risk_color(risk),
                           "fontSize": "9px",
                           "textTransform": "uppercase",
                           "letterSpacing": "0.1em"}),
        ]))

    return html.Div(
        html.Table(
            [
                html.Thead(html.Tr([
                    html.Th("Date"),  html.Th("Nom"),    html.Th("Type"),
                    html.Th("Dist"),  html.Th("Allure"), html.Th("TRIMP"),
                    html.Th("ACWR"),  html.Th("Risque"),
                ])),
                html.Tbody(rows),
            ],
            className="ca-data-table",
        ),
        className="ca-data-table-wrap",
    )


# ── 3. Historique — review ────────────────────────────────────────────────────

@app.callback(
    Output("hist-review", "children"),
    [Input("hist-review-selector", "value"),
     Input("hist-gen-btn",         "n_clicks")],
    prevent_initial_call=True,
)
def update_hist_review(activity_id, _gen):
    if not activity_id:
        raise PreventUpdate

    triggered = ctx.triggered_id

    if triggered == "hist-gen-btn":
        return _run_llm_review(int(activity_id), force=True)

    review = get_review(int(activity_id))
    if review:
        return _render_review_box(review["review_text"],
                                  review.get("model"),
                                  review.get("generated_at", "")[:10])
    return html.Div(
        "Pas de review — cliquer sur le bouton pour en générer une.",
        style={"fontFamily": "JetBrains Mono, monospace",
               "fontSize": "10px", "color": _INK_LT,
               "marginTop": "16px", "letterSpacing": "0.06em"},
    )


# ── 4. Progression — sous-onglets ─────────────────────────────────────────────

@app.callback(
    [
        Output("prog-content",  "children"),
        Output("prog-tab-pace", "className"),
        Output("prog-tab-ef",   "className"),
        Output("prog-tab-vo2",  "className"),
    ],
    [Input("prog-tab-pace", "n_clicks"),
     Input("prog-tab-ef",   "n_clicks"),
     Input("prog-tab-vo2",  "n_clicks")],
    prevent_initial_call=True,
)
def update_prog_tab(*_):
    triggered = ctx.triggered_id or "prog-tab-pace"
    tabs = ["prog-tab-pace", "prog-tab-ef", "prog-tab-vo2"]
    classes = [
        "ca-prog-tab active" if t == triggered else "ca-prog-tab"
        for t in tabs
    ]

    df = load_activities()
    if df.empty:
        content = html.Div("Pas de données.", style={
            "fontFamily": "JetBrains Mono, monospace",
            "fontSize": "11px", "color": _INK_LT, "padding": "24px 0",
        })
        return [content] + classes

    if triggered == "prog-tab-ef":
        fig  = _make_ef_chart(df)
        note = "FC requise pour calculer l'Efficiency Factor."
    elif triggered == "prog-tab-vo2":
        fig  = _make_vo2_chart(df)
        note = "VO2max non calculable (FC ou type de séance manquants)."
    else:
        fig  = _make_pace_chart(df)
        note = "Pas de données d'allure."

    if not fig.data:
        content = html.Div(note, style={
            "fontFamily": "JetBrains Mono, monospace",
            "fontSize": "11px", "color": _INK_LT, "padding": "24px 0",
        })
    else:
        content = html.Div(
            dcc.Graph(figure=fig, config={"displayModeBar": False}),
            style={"background": _BGCARD, "padding": "24px 32px"},
        )

    return [content] + classes


# ── 5. Analyse — métriques + zones + GPS + review ─────────────────────────────

@app.callback(
    [
        Output("analyse-metrics", "children"),
        Output("analyse-zones",   "figure"),
        Output("analyse-gps",     "children"),
        Output("analyse-review",  "children"),
    ],
    [Input("analyse-selector", "value"),
     Input("analyse-gen-btn",  "n_clicks")],
    prevent_initial_call=True,
)
def update_analyse(activity_id, _gen):
    if not activity_id:
        raise PreventUpdate

    triggered = ctx.triggered_id

    df = load_activities()

    if triggered == "analyse-gen-btn":
        review_content = _run_llm_review(int(activity_id), force=True)
        return no_update, no_update, no_update, review_content

    metrics, fig_zones, gps_content, review_content = _build_analyse_content(
        activity_id, df
    )
    return metrics, fig_zones, gps_content, review_content


def _build_analyse_content(activity_id, df: pd.DataFrame):
    """Construit métriques, zones, GPS et review pour une activité.
    Accessible depuis layout.py (late import)."""
    mask = df["ID"].astype(int) == int(activity_id)
    if not mask.any():
        empty = html.Div("Activité introuvable.", style={
            "fontFamily": "JetBrains Mono, monospace",
            "fontSize": "11px", "color": _INK_LT,
        })
        return empty, go.Figure(), empty, empty

    row = df[mask].iloc[0]

    # ── Métriques ─────────────────────────────────────────────────────────────
    acwr_v  = row.get("acwr_km")
    pace_s  = (row.get("pace_display", "—") or "—") + " min/km"
    is_frac = ("fractionné" in str(row.get("session_type","")).lower()
               or "mixte"   in str(row.get("session_type","")).lower())

    metrics = html.Div([
        _row("Type",        _badge(str(row.get("session_type", "")))),
        _row("Distance",    _fmt(row.get("Distance (km)"), " km")),
        _row("Durée",       _fmt(row.get("Temps (min)"), " min")),
        _row("Allure",      pace_s),
        _row("FC moy.",     _fmt(row.get("Fréquence cardiaque (bpm)"),
                                 " bpm", decimals=0)),
        _row("Dénivelé",    _fmt(row.get("Dénivelé (m)"), " m", decimals=0)),
        _row("TRIMP",       _fmt(row.get("trimp"))),
        _row("hrTSS",       _fmt(row.get("hrtss"))),
        _row("EF",          _fmt(row.get("efficiency_factor"), decimals=4)),
        _row("Découplage",  _fmt(row.get("decoupling_pct"), "%")),
        _row("VO2max est.", _fmt(row.get("vo2max_estimate"), " mL/kg/min")),
        _row("ACWR",        _fmt(acwr_v, decimals=2),
             color=_acwr_color(acwr_v)),
        _row("Risque",
             f'{row.get("injury_risk_label","—")} '
             f'({_fmt(row.get("injury_risk_score"), decimals=0)}/100)',
             color=_risk_color(str(row.get("injury_risk_label", "")))),
        _row("Form TSB",    _fmt(row.get("form_score"), decimals=0)),
        *([html.Div(str(row.get("session_type","")), className="ca-frac-banner")]
          if is_frac else []),
    ])

    # ── Zones FC ──────────────────────────────────────────────────────────────
    zone_pcts = {}
    for z in ("z1", "z2", "z3", "z4", "z5"):
        v = row.get(f"{z}_pct")
        if v is not None and not (isinstance(v, float) and np.isnan(v)):
            zone_pcts[z.upper()] = float(v)

    if zone_pcts:
        zone_colors = ["#E8E4DF", "#C4C0BB", "#787470", "#141414", _ACCENT]
        fig_zones = go.Figure(go.Pie(
            labels=list(zone_pcts.keys()),
            values=list(zone_pcts.values()),
            hole=0.60,
            marker=dict(
                colors=zone_colors[:len(zone_pcts)],
                line=dict(color=_BGCARD, width=2),
            ),
            textfont=dict(family="JetBrains Mono, monospace", size=9, color=_INK),
            showlegend=True,
        ))
        fig_zones.update_layout(
            paper_bgcolor=_BGCARD,
            plot_bgcolor=_BGCARD,
            margin=dict(l=0, r=0, t=10, b=10),
            height=200,
            legend=dict(
                font=dict(family="JetBrains Mono, monospace", size=9, color=_INK_MID),
                bgcolor="rgba(0,0,0,0)",
            ),
            hoverlabel=dict(
                bgcolor=_INK, font_color=_BG,
                font_family="JetBrains Mono, monospace", font_size=10,
            ),
        )
    else:
        fig_zones = go.Figure()
        fig_zones.update_layout(
            paper_bgcolor=_BGCARD, plot_bgcolor=_BGCARD,
            height=60,
            annotations=[dict(
                text="FC non disponible",
                showarrow=False,
                font=dict(family="JetBrains Mono, monospace", size=10,
                          color=_INK_LT),
            )],
        )

    # ── GPS ───────────────────────────────────────────────────────────────────
    gps_content = _build_gps_panel(int(activity_id), row)

    # ── Review ────────────────────────────────────────────────────────────────
    review = get_review(int(activity_id))
    if review:
        review_content = _render_review_box(
            review["review_text"],
            review.get("model"),
            review.get("generated_at", "")[:10],
        )
    else:
        review_content = html.Div(
            "Pas de review — cliquer sur le bouton pour en générer une.",
            style={"fontFamily": "JetBrains Mono, monospace",
                   "fontSize": "10px", "color": _INK_LT,
                   "marginTop": "16px", "letterSpacing": "0.06em"},
        )

    return metrics, fig_zones, gps_content, review_content


# ── Helpers review ────────────────────────────────────────────────────────────

def _render_review_box(text: str, model=None, date=None) -> html.Div:
    return html.Div([
        dcc.Markdown(text, className="ca-review-text"),
        html.Div(
            f"{model or ''}{'  ·  ' if model and date else ''}{date or ''}",
            className="ca-review-meta",
        ) if model or date else None,
    ], className="ca-review-box")


def _run_llm_review(activity_id: int, force: bool = False) -> html.Div:
    import sys as _sys
    _sys.path.insert(0, os.path.join(_ROOT, "analyse"))
    try:
        from llm_review import generate_review
        rev = generate_review(activity_id, force=force)
        return _render_review_box(
            rev["review_text"], rev.get("model"),
            rev.get("generated_at", "")[:10],
        )
    except Exception as e:
        return html.Div(
            f"Erreur : {e}",
            style={"fontFamily": "JetBrains Mono, monospace",
                   "fontSize": "11px", "color": _DANGER,
                   "marginTop": "16px"},
        )


# ── Carte GPS Plotly ──────────────────────────────────────────────────────────

def build_map_figure(points: list[dict]) -> go.Figure:
    """
    Construit la figure Plotly Scattermapbox depuis les points GPS.

    Utilise le style carto-darkmatter (sans token Mapbox requis).
    Cohérent avec le fond sombre de la section.
    """
    lats = [p["lat"] for p in points if "lat" in p and "lon" in p]
    lons = [p["lon"] for p in points if "lat" in p and "lon" in p]
    if not lats:
        return go.Figure()

    fig = go.Figure()

    # Tracé principal
    fig.add_trace(go.Scattermapbox(
        lat=lats,
        lon=lons,
        mode="lines",
        line=dict(width=3, color=_ACCENT),
        hoverinfo="skip",
        name="parcours",
    ))

    # Départ — vert
    fig.add_trace(go.Scattermapbox(
        lat=[lats[0]],
        lon=[lons[0]],
        mode="markers",
        marker=dict(size=12, color=_SUCCESS),
        hovertext="Départ",
        name="départ",
    ))

    # Arrivée — rouge sombre
    fig.add_trace(go.Scattermapbox(
        lat=[lats[-1]],
        lon=[lons[-1]],
        mode="markers",
        marker=dict(size=12, color=_DANGER),
        hovertext="Arrivée",
        name="arrivée",
    ))

    center_lat = sum(lats) / len(lats)
    center_lon = sum(lons) / len(lons)

    fig.update_layout(
        mapbox=dict(
            style="carto-darkmatter",
            center=dict(lat=center_lat, lon=center_lon),
            zoom=13,
        ),
        paper_bgcolor="#141414",
        margin=dict(l=0, r=0, t=0, b=0),
        height=420,
        showlegend=False,
    )
    return fig


@app.callback(
    Output("map-figure", "figure"),
    Input("analyse-selector", "value"),
    prevent_initial_call=True,
)
def update_map(activity_id):
    if not activity_id:
        return go.Figure()
    gps = load_gps(int(activity_id))
    if not gps or not gps.get("points"):
        return go.Figure()
    return build_map_figure(gps["points"])


# ── Helper GPS ────────────────────────────────────────────────────────────────

def _build_gps_panel(activity_id: int, row: pd.Series) -> html.Div:
    gps_path = gps_file(activity_id)
    if not gps_path:
        return html.Div("GPS non disponible pour cette activité.",
                        className="ca-gps-placeholder")

    try:
        import folium

        with open(gps_path, encoding="utf-8") as f:
            gps_data = _json.load(f)

        pts = gps_data.get("points", [])
        if not pts:
            return html.Div("GPS : aucun point.", className="ca-gps-placeholder")

        coords = [[p["lat"], p["lon"]] for p in pts if "lat" in p and "lon" in p]
        if len(coords) < 2:
            return html.Div("GPS : données insuffisantes.",
                            className="ca-gps-placeholder")

        center = [
            sum(c[0] for c in coords) / len(coords),
            sum(c[1] for c in coords) / len(coords),
        ]
        m = folium.Map(location=center, zoom_start=13, tiles="CartoDB dark_matter")

        stype_s  = str(row.get("session_type", "")).lower()
        is_frac  = "fractionné" in stype_s or "mixte" in stype_s
        str_path = stream_file(activity_id)
        colored  = False

        if is_frac and str_path:
            try:
                df_s = pd.read_csv(str_path)
                if "time_s" in df_s.columns and "speed_kmh" in df_s.columns:
                    df_s    = df_s.dropna(subset=["speed_kmh"])
                    med_spd = float(df_s["speed_kmh"].median())
                    spd_map = dict(zip(df_s["time_s"].astype(int), df_s["speed_kmh"]))
                    spd_keys = sorted(spd_map.keys())

                    def _nearest(t_s):
                        lo, hi = 0, len(spd_keys) - 1
                        while lo < hi:
                            mid = (lo + hi) // 2
                            if spd_keys[mid] < t_s:
                                lo = mid + 1
                            else:
                                hi = mid
                        return spd_map[spd_keys[lo]]

                    valid = [p for p in pts
                             if "lat" in p and "lon" in p
                             and p.get("time_s") is not None]
                    if valid:
                        effort_segs, recov_segs = [], []
                        cur_seg, cur_ef = [], None
                        for p in valid:
                            spd_v  = _nearest(int(p["time_s"]))
                            is_eff = spd_v >= med_spd
                            coord  = [p["lat"], p["lon"]]
                            if cur_ef is None:
                                cur_ef = is_eff
                            if is_eff == cur_ef:
                                cur_seg.append(coord)
                            else:
                                if len(cur_seg) >= 2:
                                    (effort_segs if cur_ef else recov_segs).append(cur_seg)
                                cur_seg = [cur_seg[-1], coord] if cur_seg else [coord]
                                cur_ef  = is_eff
                        if len(cur_seg) >= 2:
                            (effort_segs if cur_ef else recov_segs).append(cur_seg)

                        for seg in effort_segs:
                            folium.PolyLine(seg, color="#D4380D", weight=3,
                                            opacity=0.9).add_to(m)
                        for seg in recov_segs:
                            folium.PolyLine(seg, color="#3A3632", weight=2,
                                            opacity=0.6).add_to(m)
                        colored = True
            except Exception:
                pass

        if not colored:
            folium.PolyLine(coords, color="#C4C0BB", weight=2,
                            opacity=0.8, smooth_factor=1).add_to(m)

        folium.CircleMarker(coords[0],  radius=5, color="#2D6A4F",
                            fill=True, fill_color="#2D6A4F", fill_opacity=1,
                            popup="Départ").add_to(m)
        folium.CircleMarker(coords[-1], radius=5, color="#991B1B",
                            fill=True, fill_color="#991B1B", fill_opacity=1,
                            popup="Arrivée").add_to(m)

        map_html = m.get_root().render()
        return html.Iframe(srcDoc=map_html, className="ca-gps-frame")

    except ImportError:
        return html.Div("folium requis : pip install folium",
                        className="ca-gps-placeholder")
    except Exception as e:
        return html.Div(f"Erreur GPS : {e}", className="ca-gps-placeholder")
