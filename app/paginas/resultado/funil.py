"""Página «Funil» do painel."""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go
import streamlit as st

from app.comum import (COR_BAIXA, COR_NORMAL, amostrar_fundo, limites_funil)
from app.cabecalho import render as cabecalho


def render(ctx):
    cabecalho(ctx)
    df = ctx.df
    r = ctx.r
    pontos = df[["aptos", "taxa_abstencao", "municipio", "zona", "secao"]].assign(
        _grupo=np.where(df["f_abst"], "abstenção baixa", "demais"))
    pontos = amostrar_fundo(pontos, pontos["_grupo"] != "demais")
    fig = go.Figure()
    for nome, cor in [("demais", COR_NORMAL), ("abstenção baixa", COR_BAIXA)]:
        d = pontos[pontos["_grupo"] == nome]
        fig.add_trace(go.Scattergl(
            x=d["aptos"], y=d["taxa_abstencao"], mode="markers", name=nome,
            marker=dict(size=4 if nome == "demais" else 7, color=cor,
                        opacity=0.35 if nome == "demais" else 0.9),
            text=d["municipio"].astype(str) + " · Z" + d["zona"].astype(str) + " · S" + d["secao"].astype(str),
            hovertemplate="%{text}<br>aptos %{x}<br>abstenção %{y:.1%}<extra></extra>"))
    tau2 = float(df["tau2"].median())
    for k, estilo in [(2, "dash"), (3, "solid")]:
        lim = limites_funil(r.taxa_agregada, tau2, int(df["aptos"].max()), k)
        for lado in ["inf", "sup"]:
            fig.add_trace(go.Scatter(x=lim["aptos"], y=lim[lado], mode="lines", showlegend=False,
                                     line=dict(color="black", dash=estilo, width=1), hoverinfo="skip"))
    fig.update_layout(title="Funil: seções pequenas variam mais por acaso — "
                            "linhas = ±2 e ±3 desvios esperados para cada tamanho",
                      xaxis_title="eleitores aptos na seção", yaxis_title="abstenção",
                      yaxis_tickformat=".0%", height=600)
    st.plotly_chart(fig, width="stretch")
    st.caption("O funil usa a abstenção agregada deste nível como centro. A cor (abstenção baixa) "
               "usa a comparação com o próprio município, por isso alguns pontos coloridos "
               "ficam dentro das linhas e vice-versa.")
