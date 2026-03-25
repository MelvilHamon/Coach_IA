"""
dashboard/app.py — Init Dash + lancement.
Depuis la racine du projet : python dashboard/app.py
"""

import dash

app = dash.Dash(
    __name__,
    title="CoachAgent",
    suppress_callback_exceptions=True,
    meta_tags=[{"name": "viewport", "content": "width=device-width, initial-scale=1"}],
)
server = app.server

from layout import create_layout  # noqa: E402
app.layout = create_layout()

import callbacks  # noqa: E402, F401 — enregistre les callbacks

if __name__ == "__main__":
    app.run(debug=True, port=8050)
