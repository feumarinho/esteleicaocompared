"""Página «Comparar» do painel."""
from __future__ import annotations

import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app.comum import (resumo)
from app.cabecalho import render as cabecalho


def render(ctx):
    cabecalho(ctx)
    df = ctx.df
    filho = ctx.filho
    r = ctx.r
    rotulo = ctx.rotulo
    tab = resumo(df, filho)
    alertas = df[df["alerta"] == "sinalizada"].groupby(filho, observed=True).size().rename("sinalizadas")
    tab = tab.merge(alertas, left_on=filho, right_index=True, how="left").fillna({"sinalizadas": 0})
    tab[rotulo] = tab[rotulo].astype(str)

    if len(tab) <= 40:
        t = tab.sort_values("media")
        fig = go.Figure(go.Scatter(
            x=t["media"], y=t[rotulo], mode="markers",
            error_x=dict(type="data", array=t["desvio_padrao"].fillna(0), color="#b8c0cc"),
            marker=dict(size=9, color="#33415c"),
            customdata=np.stack([t["secoes"], t["taxa_agregada"]], axis=1),
            hovertemplate="%{y}<br>média %{x:.1%}<br>seções %{customdata[0]}<br>"
                          "agregada %{customdata[1]:.1%}<extra></extra>"))
        fig.add_vline(x=r.media, line_dash="dash", annotation_text="média do nível acima")
        fig.update_layout(title="Média ± 1 desvio padrão da abstenção das seções",
                          xaxis_tickformat=".0%", height=max(350, 22 * len(t) + 80),
                          margin=dict(l=10, r=10, t=50, b=10))
    else:
        fig = px.scatter(tab, x="media", y="desvio_padrao", size="aptos", color="sinalizadas",
                         hover_name=rotulo, color_continuous_scale="OrRd", size_max=40,
                         hover_data={"secoes": True, "taxa_agregada": ":.1%", "aptos": ":,"},
                         title="Cada ponto é uma unidade: média × desvio padrão "
                               "(longe do grupo = comportamento diferente)")
        fig.update_layout(xaxis_tickformat=".0%", yaxis_tickformat=".0%", height=560)
    st.plotly_chart(fig, width="stretch")

    st.dataframe(tab.drop(columns=[c for c in ["cd_municipio"] if c in tab and rotulo != "cd_municipio"])
                 .sort_values("media", ascending=False), hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="percent")
                                for c in ["taxa_agregada", "media", "desvio_padrao", "mediana",
                                          "mad", "p05", "p95", "minimo", "maximo"]})
