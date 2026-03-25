"""
dashboard/layout.py — Structure HTML, composants et helpers visuels.
"""

import numpy as np
import pandas as pd
from dash import dcc, html

from data import load_activities

# ── Palette de couleurs traces Plotly ────────────────────────────────────────

_ACCENT  = "#D4380D"
_SUCCESS = "#2D6A4F"
_WARNING = "#B45309"
_DANGER  = "#991B1B"
_INK     = "#141414"
_INK_MID = "#787470"
_INK_LT  = "#C4C0BB"
_BG      = "#F7F4F0"
_BGCARD  = "#FFFFFF"
_BORDER  = "#E8E4DF"

# ── Template Plotly ───────────────────────────────────────────────────────────

PLOTLY_TEMPLATE = dict(
    paper_bgcolor=_BGCARD,
    plot_bgcolor=_BGCARD,
    font=dict(family="JetBrains Mono, monospace", color=_INK_MID, size=10),
    margin=dict(l=48, r=24, t=24, b=40),
    showlegend=False,
    hovermode="x unified",
    hoverlabel=dict(
        bgcolor="#141414",
        font_color="#F7F4F0",
        font_family="JetBrains Mono, monospace",
        font_size=11,
        bordercolor="#2A2A2A",
    ),
)

_AX_STYLE = dict(
    gridcolor="#F0EDE8",
    gridwidth=1,
    showline=False,
    tickfont=dict(family="JetBrains Mono, monospace", size=10, color=_INK_LT),
    showgrid=True,
    zeroline=False,
)

# Palettes type de séance
_STYPE_PALETTE = [
    _INK, _ACCENT, _WARNING, _SUCCESS,
    "#5C4A3A", _INK_MID, _INK_LT,
]

# ── Helpers visuels ───────────────────────────────────────────────────────────

def _fmt(v, unit="", decimals=1, na="—"):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return na
    try:
        return f"{float(v):.{decimals}f}{unit}"
    except (TypeError, ValueError):
        return f"{v}{unit}"


def _badge_class(stype: str) -> str:
    s = str(stype).lower()
    if "fractionné" in s or "mixte" in s or "pyramide" in s:
        return "ca-badge ca-badge-frac"
    if "trail" in s:
        return "ca-badge ca-badge-trail"
    if "récupération" in s:
        return "ca-badge ca-badge-recov"
    if "longue" in s:
        return "ca-badge ca-badge-long"
    if "tempo" in s or "seuil" in s:
        return "ca-badge ca-badge-tempo"
    return "ca-badge ca-badge-endo"


def _badge(stype: str) -> html.Span:
    return html.Span(str(stype), className=_badge_class(stype))


def _acwr_color(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return _INK_LT
    if v > 1.5:
        return _DANGER
    if v > 1.3:
        return _WARNING
    if v > 0.8:
        return _SUCCESS
    return _INK_MID


def _risk_color(label: str) -> str:
    return {
        "faible":   _SUCCESS,
        "modéré":   _WARNING,
        "élevé":    _DANGER,
        "critique": _DANGER,
    }.get(str(label).lower(), _INK_LT)


def _acwr_status(v) -> str:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "neutral"
    if v > 1.5:
        return "alert"
    if v > 1.3:
        return "warn"
    return "ok"


def _risk_status(label: str) -> str:
    return {
        "faible":   "ok",
        "modéré":   "warn",
        "élevé":    "alert",
        "critique": "alert",
    }.get(str(label).lower(), "neutral")


def _section_title(text: str) -> html.Div:
    return html.Div(text, className="ca-section-title")


def metric_card(label: str, value: str, unit: str = "", status: str = "neutral") -> html.Div:
    _status_colors = {
        "ok":      _SUCCESS,
        "warn":    _WARNING,
        "alert":   _DANGER,
        "neutral": _BORDER,
    }
    border_color = _status_colors.get(status, _BORDER)
    return html.Div([
        html.Div(label, style={
            "fontFamily": "JetBrains Mono, monospace",
            "fontSize": "9px",
            "letterSpacing": "0.12em",
            "textTransform": "uppercase",
            "color": _INK_MID,
            "marginBottom": "8px",
        }),
        html.Div([
            html.Span(str(value), style={
                "fontFamily": "Cormorant Garamond, serif",
                "fontSize": "56px",
                "fontWeight": "300",
                "lineHeight": "1",
                "color": _INK,
            }),
            html.Span("\u00a0" + unit, style={
                "fontFamily": "JetBrains Mono, monospace",
                "fontSize": "11px",
                "color": _INK_MID,
                "marginLeft": "4px",
            }) if unit else None,
        ], style={"display": "flex", "alignItems": "baseline"}),
    ], style={
        "borderTop": f"3px solid {border_color}",
        "padding": "16px 0 24px",
        "flex": "1",
        "minWidth": "160px",
    })


def _row(label, value, color=None) -> html.Div:
    val_style = {"color": color} if color else {}
    return html.Div([
        html.Span(label, className="ca-row-label"),
        html.Span(value, className="ca-row-val", style=val_style),
    ], className="ca-row")


def _empty(msg="Pas de données disponibles.") -> html.Div:
    return html.Div([html.Strong("Données absentes"), msg], className="ca-empty")


# ── Graphiques statiques ──────────────────────────────────────────────────────

def _make_volume_chart(df: pd.DataFrame):
    import plotly.graph_objects as go

    df_asc = df.sort_values("Date")
    df_w   = df_asc[df_asc["weekly_km"].notna()].copy()
    df_w["week"] = (
        df_w["Date"].dt.tz_convert(None).dt.to_period("W")
        .apply(lambda p: p.start_time)
    )
    agg = (
        df_w.groupby("week")
        .agg(total_km=("Distance (km)", "sum"), acwr=("acwr_km", "last"))
        .reset_index()
        .tail(16)
    )
    if agg.empty:
        return go.Figure()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=agg["week"], y=agg["total_km"],
        name="km / semaine",
        marker=dict(color="#141414", opacity=0.12, line=dict(color="#141414", width=1)),
        yaxis="y1",
    ))
    fig.add_trace(go.Scatter(
        x=agg["week"], y=agg["acwr"],
        name="ACWR", mode="lines+markers",
        line=dict(color="#D4380D", width=2),
        marker=dict(size=4, color="#D4380D"),
        yaxis="y2",
    ))
    fig.add_hline(y=1.3, line_dash="dot", line_color=_WARNING, yref="y2", opacity=0.5)
    fig.add_hline(y=1.5, line_dash="dot", line_color=_DANGER,  yref="y2", opacity=0.5)
    fig.update_layout(**PLOTLY_TEMPLATE, height=280)
    fig.update_xaxes(**_AX_STYLE)
    fig.update_yaxes(**_AX_STYLE)
    fig.update_layout(
        showlegend=True,
        legend=dict(
            bgcolor="rgba(0,0,0,0)", borderwidth=0,
            font=dict(family="JetBrains Mono, monospace", size=9, color=_INK_LT),
            x=0, y=1.05, orientation="h",
        ),
        yaxis=dict(
            title=dict(text="km",
                       font=dict(family="JetBrains Mono, monospace", size=10, color=_INK_LT)),
        ),
        yaxis2=dict(
            **_AX_STYLE,
            title=dict(text="ACWR",
                       font=dict(family="JetBrains Mono, monospace", size=10, color=_INK_LT)),
            overlaying="y", side="right", range=[0, 2.5],
        ),
    )
    return fig


def _make_pace_chart(df: pd.DataFrame):
    import plotly.graph_objects as go

    run_types = [
        "endurance fondamentale", "fractionné court", "fractionné moyen",
        "fractionné long", "mixte", "tempo / seuil", "sortie longue",
    ]
    df_p = df[
        df["session_type"].isin(run_types) & df["Allure (min/km)"].notna()
    ].sort_values("Date")

    if df_p.empty:
        return go.Figure()

    fig = go.Figure()
    for i, stype in enumerate(run_types):
        sub = df_p[df_p["session_type"] == stype]
        if sub.empty:
            continue
        fig.add_trace(go.Scatter(
            x=sub["Date"], y=sub["Allure (min/km)"],
            mode="lines+markers", name=stype,
            line=dict(color=_STYPE_PALETTE[i % len(_STYPE_PALETTE)], width=1.5),
            marker=dict(size=4, color=_STYPE_PALETTE[i % len(_STYPE_PALETTE)]),
            opacity=0.85,
        ))
    fig.update_layout(**PLOTLY_TEMPLATE, height=340)
    fig.update_xaxes(**_AX_STYLE)
    fig.update_yaxes(**_AX_STYLE, autorange="reversed",
                     title=dict(text="min/km",
                                font=dict(family="JetBrains Mono, monospace",
                                          size=10, color=_INK_LT)))
    fig.update_layout(
        showlegend=True,
        legend=dict(
            bgcolor="rgba(0,0,0,0)", borderwidth=0,
            font=dict(family="JetBrains Mono, monospace", size=9, color=_INK_LT),
            x=0, y=-0.18, orientation="h",
        ),
    )
    return fig


def _make_ef_chart(df: pd.DataFrame):
    import plotly.graph_objects as go

    df_e = df[df["efficiency_factor"].notna()].sort_values("Date").copy()
    if df_e.empty:
        return go.Figure()

    df_e["ef_roll"] = df_e["efficiency_factor"].rolling(10, min_periods=3).mean()
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_e["Date"], y=df_e["efficiency_factor"],
        mode="markers", name="EF",
        marker=dict(size=3, color=_INK_LT), opacity=0.6,
    ))
    fig.add_trace(go.Scatter(
        x=df_e["Date"], y=df_e["ef_roll"],
        mode="lines", name="Moy. 10 séances",
        line=dict(color=_INK, width=2),
        fill="tozeroy", fillcolor="rgba(20,20,20,0.04)",
    ))
    fig.update_layout(**PLOTLY_TEMPLATE, height=320)
    fig.update_xaxes(**_AX_STYLE)
    fig.update_yaxes(**_AX_STYLE,
                     title=dict(text="EF (vitesse / FC)",
                                font=dict(family="JetBrains Mono, monospace",
                                          size=10, color=_INK_LT)))
    return fig


def _make_vo2_chart(df: pd.DataFrame):
    import plotly.graph_objects as go

    df_v = df[df["vo2max_estimate"].notna()].sort_values("Date").copy()
    if df_v.empty:
        return go.Figure()

    df_v["vo2_roll"] = df_v["vo2max_estimate"].rolling(8, min_periods=3).mean()
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_v["Date"], y=df_v["vo2max_estimate"],
        mode="markers", name="VO2max",
        marker=dict(size=4, color=_INK_LT), opacity=0.5,
    ))
    fig.add_trace(go.Scatter(
        x=df_v["Date"], y=df_v["vo2_roll"],
        mode="lines", name="Tendance",
        line=dict(color=_INK, width=2),
        fill="tozeroy", fillcolor="rgba(20,20,20,0.04)",
    ))
    fig.update_layout(**PLOTLY_TEMPLATE, height=320)
    fig.update_xaxes(**_AX_STYLE)
    fig.update_yaxes(**_AX_STYLE,
                     title=dict(text="mL/kg/min",
                                font=dict(family="JetBrains Mono, monospace",
                                          size=10, color=_INK_LT)))
    return fig


def _make_acwr_chart(df: pd.DataFrame):
    import plotly.graph_objects as go

    df_a = df[df["acwr_km"].notna()].sort_values("Date")
    df_90 = df_a[df_a["Date"] >= df_a["Date"].max() - pd.Timedelta(days=90)]
    if df_90.empty:
        return go.Figure()

    fig = go.Figure()
    fig.add_hrect(y0=0,   y1=0.8, fillcolor="#991B1B", opacity=0.04, line_width=0)
    fig.add_hrect(y0=0.8, y1=1.3, fillcolor="#2D6A4F", opacity=0.04, line_width=0)
    fig.add_hrect(y0=1.3, y1=1.5, fillcolor="#B45309", opacity=0.06, line_width=0)
    fig.add_hrect(y0=1.5, y1=3.0, fillcolor="#991B1B", opacity=0.06, line_width=0)
    fig.add_trace(go.Scatter(
        x=df_90["Date"], y=df_90["acwr_km"],
        mode="lines+markers",
        line=dict(color="#D4380D", width=2),
        marker=dict(size=4, color="#D4380D"),
        showlegend=False,
    ))
    fig.add_hline(
        y=1.3, line_dash="dot", line_color=_WARNING, opacity=0.6,
        annotation_text="1.3",
        annotation_font=dict(family="JetBrains Mono, monospace", size=9, color=_WARNING),
    )
    fig.add_hline(
        y=1.5, line_dash="dot", line_color=_DANGER, opacity=0.6,
        annotation_text="1.5",
        annotation_font=dict(family="JetBrains Mono, monospace", size=9, color=_DANGER),
    )
    y_max = max(2.0, float(df_90["acwr_km"].max()) + 0.2)
    fig.update_layout(**PLOTLY_TEMPLATE, height=260)
    fig.update_xaxes(**_AX_STYLE)
    fig.update_yaxes(**_AX_STYLE,
                     range=[0, y_max],
                     title=dict(text="ACWR",
                                font=dict(family="JetBrains Mono, monospace",
                                          size=10, color=_INK_LT)))
    return fig


# ── Sections ──────────────────────────────────────────────────────────────────

def render_no_data() -> html.Div:
    return html.Div([
        html.Strong("Données introuvables"),
        html.Span(
            "Lancer d'abord : python3 analyse/run_analysis.py",
            style={"display": "block", "marginTop": "8px", "color": _ACCENT},
        ),
    ], className="ca-empty")


def render_overview() -> html.Div:
    df = load_activities()
    if df.empty:
        return render_no_data()

    last = df.iloc[0]

    acwr_v     = last.get("acwr_km")
    risk_score = int(last.get("injury_risk_score") or 0)
    risk_label = str(last.get("injury_risk_label", "—"))
    form_v     = last.get("form_score")

    try:
        fv = float(form_v)
        form_status = "ok" if fv > 10 else "warn" if fv > -10 else "alert"
    except (TypeError, ValueError):
        form_status = "neutral"

    # Type distribution bars
    type_counts = df["session_type"].value_counts().reset_index()
    type_counts.columns = ["type", "count"]
    total_typed = len(df[df["session_type"].notna()])
    stype_colors = {
        "fractionné":   _ACCENT,
        "trail":        _SUCCESS,
        "tempo":        _WARNING,
        "endurance":    _INK_MID,
        "récupération": _INK_LT,
    }
    dist_rows = []
    for _, r in type_counts.iterrows():
        stype = str(r["type"])
        n     = int(r["count"])
        pct   = n / total_typed * 100 if total_typed else 0
        color = next(
            (v for k, v in stype_colors.items() if k in stype.lower()), _INK_LT
        )
        dist_rows.append(html.Div([
            html.Div([
                html.Span(stype,  className="ca-dist-bar-label"),
                html.Span(str(n), className="ca-dist-bar-count"),
            ], className="ca-dist-bar-header"),
            html.Div(
                html.Div(style={
                    "height": "2px", "width": f"{pct:.1f}%",
                    "background": color,
                }),
                className="ca-dist-bar-track",
            ),
        ], className="ca-dist-bar-row"))

    return html.Div([
        # KPI row
        html.Div([
            metric_card("Volume semaine", _fmt(last.get("weekly_km"), decimals=1), "km"),
            metric_card("ACWR",          _fmt(acwr_v, decimals=2),              "",    status=_acwr_status(acwr_v)),
            metric_card("Risque blessure", str(risk_score),                     "/100", status=_risk_status(risk_label)),
            metric_card("Form (TSB)",    _fmt(form_v, decimals=0),              "",    status=form_status),
        ], style={"display": "flex", "gap": "32px", "flexWrap": "wrap",
                  "padding": "0 0 8px"}),

        # Volume chart
        html.Div([
            _section_title("Volume hebdomadaire — 16 semaines"),
            html.Div(
                dcc.Graph(
                    figure=_make_volume_chart(df),
                    config={"displayModeBar": False},
                    style={"background": _BGCARD},
                ),
                className="ca-chart-card",
                style={"padding": "24px 32px"},
            ),
        ], className="ca-section"),

        # Type distribution
        html.Div([
            _section_title("Répartition des séances"),
            html.Div(dist_rows, style={"maxWidth": "520px"}),
        ], className="ca-section"),
    ])


def render_history() -> html.Div:
    df = load_activities()
    if df.empty:
        return render_no_data()

    all_types = ["Tous"] + sorted(df["session_type"].dropna().unique().tolist())
    type_opts = [{"label": t, "value": t} for t in all_types]

    # Pre-render initial table (all activities)
    from callbacks import _build_history_table  # noqa – late import to avoid circular
    initial_table = _build_history_table(df)

    # Review dropdown options
    review_opts = [
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
    review_default = review_opts[0]["value"] if review_opts else None

    return html.Div([
        html.Div([
            # Filters
            html.Div([
                html.Div([
                    html.Div("Type", className="ca-control-label"),
                    dcc.Dropdown(
                        id="hist-filter-type",
                        options=type_opts,
                        value="Tous",
                        clearable=False,
                        className="ca-dropdown",
                        style={"minWidth": "200px"},
                    ),
                ], className="ca-control-group"),
                html.Div([
                    html.Div("Période", className="ca-control-label"),
                    html.Div([
                        html.Button("30j",  id="hist-period-30",  n_clicks=0,
                                    className="ca-radio-btn"),
                        html.Button("90j",  id="hist-period-90",  n_clicks=0,
                                    className="ca-radio-btn"),
                        html.Button("Tout", id="hist-period-all", n_clicks=0,
                                    className="ca-radio-btn active"),
                    ], className="ca-radio"),
                ], className="ca-control-group"),
            ], className="ca-controls"),

            _section_title("Historique"),
            html.Div(initial_table, id="hist-table-container"),
        ], className="ca-section"),

        # Review section
        html.Div([
            _section_title("Review de séance"),
            html.Div([
                html.Div("Séance", className="ca-control-label"),
                dcc.Dropdown(
                    id="hist-review-selector",
                    options=review_opts,
                    value=review_default,
                    clearable=False,
                    placeholder="Sélectionner une séance…",
                    className="ca-dropdown",
                ),
            ], className="ca-control-group", style={"marginBottom": "16px"}),
            html.Button("Générer / Régénérer la review LLM",
                        id="hist-gen-btn", n_clicks=0, className="ca-btn accent"),
            dcc.Loading(
                html.Div(id="hist-review"),
                type="dot", color=_ACCENT,
            ),
        ], className="ca-section"),
    ])


def render_progression() -> html.Div:
    df = load_activities()
    if df.empty:
        return render_no_data()

    fig = _make_pace_chart(df)
    initial_chart = html.Div(
        dcc.Graph(figure=fig, config={"displayModeBar": False}),
        style={"background": _BGCARD, "padding": "24px 32px"},
    ) if fig.data else html.Div(
        "Pas de données d'allure.",
        style={"fontFamily": "JetBrains Mono, monospace",
               "fontSize": "11px", "color": _INK_LT, "padding": "24px 0"},
    )

    return html.Div([
        html.Div([
            html.Div([
                html.Button("Allure",            id="prog-tab-pace", n_clicks=0,
                            className="ca-prog-tab active"),
                html.Button("Efficiency Factor", id="prog-tab-ef",   n_clicks=0,
                            className="ca-prog-tab"),
                html.Button("VO2max estimé",     id="prog-tab-vo2",  n_clicks=0,
                            className="ca-prog-tab"),
            ], className="ca-prog-tabs"),
            html.Div(initial_chart, id="prog-content"),
        ], className="ca-section"),
    ])


def render_charge() -> html.Div:
    df = load_activities()
    if df.empty:
        return render_no_data()

    last       = df.iloc[0]
    risk_score = int(last.get("injury_risk_score") or 0)
    risk_label = str(last.get("injury_risk_label", "faible")).lower()
    rcolor     = _risk_color(risk_label)

    df_asc   = df.sort_values("Date")
    df_flags = df_asc[df_asc["Date"] >= df_asc["Date"].max() - pd.Timedelta(days=14)]
    flag_map = {
        "flag_acwr":        "ACWR élevé",
        "flag_monotony":    "Monotonie",
        "flag_load_spike":  "Pic de charge",
        "flag_consecutive": "Jours consécutifs",
    }
    flag_items = []
    any_flag   = False
    for fc, lbl in flag_map.items():
        if fc not in df_flags.columns:
            continue
        n = int(df_flags[df_flags[fc].isin([True, "True"])].shape[0])
        if n > 0:
            any_flag = True
            flag_items.append(html.Div([
                html.Div(className="ca-flag-dot"),
                html.Span(lbl,           className="ca-flag-lbl"),
                html.Span(f"{n} séance(s)", className="ca-flag-count"),
            ], className="ca-flag-row"))
    if not any_flag:
        flag_items.append(html.Div("Aucun flag actif", className="ca-no-flag"))

    stat_grid = html.Div([
        *[
            html.Div([
                html.Div(_fmt(last.get(k), decimals=0), className="ca-stat-val"),
                html.Div(lbl, className="ca-stat-lbl"),
            ], className="ca-stat-cell")
            for k, lbl in [
                ("fitness_score", "Fitness 42j"),
                ("fatigue_score", "Fatigue 7j"),
                ("form_score",    "Form TSB"),
                ("acwr_km",       "ACWR"),
            ]
        ]
    ], className="ca-stat-grid")

    return html.Div([
        html.Div([
            html.Div([
                _section_title("ACWR — 90 derniers jours"),
                html.Div(
                    dcc.Graph(
                        figure=_make_acwr_chart(df),
                        config={"displayModeBar": False},
                    ),
                    style={"background": _BGCARD, "padding": "24px 32px",
                           "marginBottom": "1px"},
                ),
                html.Div(style={"height": "32px"}),
                _section_title("Flags — 14 derniers jours"),
                *flag_items,
            ], className="ca-col-main"),

            html.Div([
                _section_title("Score de risque"),
                html.Div([
                    html.Div([
                        html.Span(str(risk_score),
                                  style={"fontFamily": "Cormorant Garamond, serif",
                                         "fontSize": "80px", "fontWeight": "600",
                                         "color": rcolor, "letterSpacing": "-0.02em",
                                         "lineHeight": "1"}),
                        html.Span("/100",
                                  style={"fontFamily": "JetBrains Mono, monospace",
                                         "fontSize": "12px", "color": _INK_LT,
                                         "marginLeft": "8px"}),
                    ]),
                    html.Div(risk_label,
                             style={"fontFamily": "JetBrains Mono, monospace",
                                    "fontSize": "9px", "color": _INK_LT,
                                    "textTransform": "uppercase",
                                    "letterSpacing": "0.2em", "marginTop": "8px"}),
                    html.Div(className="ca-risk-track",
                             children=[
                                 html.Div(className="ca-risk-fill",
                                          style={"width": f"{risk_score}%",
                                                 "background": rcolor}),
                             ]),
                ], style={"marginBottom": "8px"}),
                stat_grid,
            ], className="ca-col-aside"),
        ], className="ca-two-col"),
    ])


def render_analyse() -> html.Div:
    df = load_activities()
    if df.empty:
        return render_no_data()

    opts = [
        {
            "label": (
                f"{row['Date'].strftime('%d/%m/%Y')} — "
                f"{str(row.get('Nom',''))[:30]} "
                f"[{row.get('session_type','')}]"
            ),
            "value": int(row["ID"]),
        }
        for _, row in df.iterrows()
    ]
    default_id = opts[0]["value"] if opts else None

    import plotly.graph_objects as _go
    initial_metrics     = html.Div()
    initial_zones       = _go.Figure()
    initial_gps         = html.Div()
    initial_review      = html.Div()
    initial_map_content = dcc.Graph(
        id="map-figure",
        figure=_go.Figure(),
        config={"scrollZoom": True, "displayModeBar": False},
    )

    return html.Div([
        html.Div([
            html.Div([
                html.Div("Séance", className="ca-control-label"),
                dcc.Dropdown(
                    id="analyse-selector",
                    options=opts,
                    value=default_id,
                    clearable=False,
                    className="ca-dropdown",
                ),
            ], className="ca-control-group", style={"maxWidth": "640px"}),
        ], className="ca-section"),

        html.Div([
            html.Div([
                _section_title("Métriques"),
                html.Div(initial_metrics, id="analyse-metrics"),
            ], className="ca-col-main"),
            html.Div([
                _section_title("Zones FC"),
                dcc.Graph(
                    id="analyse-zones",
                    figure=initial_zones,
                    config={"displayModeBar": False},
                ),
                _section_title("Trace GPS"),
                dcc.Loading(
                    html.Div(initial_gps, id="analyse-gps"),
                    type="dot", color=_ACCENT,
                ),
            ], className="ca-col-aside"),
        ], className="ca-two-col"),

        html.Div([
            _section_title("Parcours"),
            initial_map_content,
        ], className="ca-section", style={"paddingTop": "0"}),

        html.Div([
            _section_title("Review coach"),
            html.Button(
                "Générer / Régénérer la review LLM",
                id="analyse-gen-btn", n_clicks=0, className="ca-btn accent",
            ),
            dcc.Loading(
                html.Div(initial_review, id="analyse-review"),
                type="dot", color=_ACCENT,
            ),
        ], className="ca-section"),
    ])


# ── Layout principal ──────────────────────────────────────────────────────────

def create_layout() -> html.Div:
    df = load_activities()
    if df.empty:
        n_acts    = 0
        last_date = "—"
    else:
        n_acts    = len(df)
        last_date = df.iloc[0]["Date"].strftime("%d %b %Y").upper()

    return html.Div([
        # Header
        html.Div([
            html.Div([
                "Coach",
                html.Em("Agent"),
            ], className="ca-header-title"),
            html.Div([
                html.Div(last_date),
                html.Div(f"{n_acts} activités"),
            ], className="ca-header-meta"),
        ], className="ca-header"),

        # Navigation
        html.Div([
            html.Button("Vue d'ensemble", id="tab-overview",    n_clicks=0,
                        className="ca-nav-tab active"),
            html.Button("Historique",     id="tab-history",     n_clicks=0,
                        className="ca-nav-tab"),
            html.Button("Progression",    id="tab-progression", n_clicks=0,
                        className="ca-nav-tab"),
            html.Button("Charge",         id="tab-charge",      n_clicks=0,
                        className="ca-nav-tab"),
            html.Button("Analyse",        id="tab-analyse",     n_clicks=0,
                        className="ca-nav-tab"),
        ], className="ca-nav"),

        # Page content — pre-rendered with overview
        html.Div(render_overview(), id="page-content"),
    ])
