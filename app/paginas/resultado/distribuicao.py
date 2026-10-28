"""Página «Distribuição» do painel."""
from __future__ import annotations

import streamlit as st

from app.comum import (COR_ALTA, histograma)
from app.cabecalho import render as cabecalho


def render(ctx):
    cabecalho(ctx)
    df = ctx.df
    r = ctx.r
    fig = histograma(df["taxa_abstencao"], 80, "#33415c")
    for k, estilo in [(0, "solid"), (1, "dash"), (-1, "dash"), (2, "dot"), (-2, "dot")]:
        x = r.media + k * r.desvio_padrao
        fig.add_vline(x=x, line_dash=estilo, line_color=COR_ALTA if k else "black",
                      annotation_text="média" if k == 0 else f"{k:+d} dp")
    fig.update_layout(title="Distribuição da abstenção por seção", xaxis_tickformat=".0%",
                      xaxis_title="taxa de abstenção", yaxis_title="seções", height=480)
    st.plotly_chart(fig, width="stretch")
    st.caption("A distribuição real tem caudas mais largas que uma normal; por isso, contar "
               "seções além de ±2 dp num nível grande (Brasil, UF) sempre dá milhares de casos. "
               "O z ajustado, comparando cada seção com o próprio município, é mais útil para achar pontos.")
