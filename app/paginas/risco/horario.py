"""Página «Horário dos votos» do painel."""
from __future__ import annotations

import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app.comum import (COR_ALTA, COR_NORMAL, TODOS, com_log, histograma, perfil_horario, resumo_coluna)
from app.detalhe import detalhe_secao
from app.cabecalho import render as cabecalho


def render(ctx):
    cabecalho(ctx)
    SEM_LOGS = ctx.SEM_LOGS
    base = ctx.base
    df = ctx.df
    filho = ctx.filho
    nivel = ctx.nivel
    rotulo = ctx.rotulo
    uf = ctx.uf
    dh = com_log(df)
    if dh.empty:
        st.info(SEM_LOGS)
    else:
        perfil = perfil_horario(dh)
        perfil_br = perfil_horario(base)
        perfil, perfil_br = [p[(p.index >= 7) & (p.index <= 23)] for p in (perfil, perfil_br)]
        fig = go.Figure()
        fig.add_trace(go.Bar(x=perfil.index, y=perfil.values, name=nivel,
                             marker_color=["#33415c" if h < 17 else COR_ALTA for h in perfil.index]))
        if uf != TODOS:
            fig.add_trace(go.Scatter(x=perfil_br.index, y=perfil_br.values, name="Brasil (seções com log)",
                                     mode="lines+markers", line=dict(color=COR_NORMAL, dash="dot")))
        fig.add_vline(x=16.5, line_dash="dash", annotation_text="17h")
        fig.update_layout(title="Distribuição dos votos ao longo do dia (horário de Brasília)",
                          xaxis=dict(tickmode="array", tickvals=list(perfil.index),
                                     ticktext=[f"{h}h" for h in perfil.index]),
                          yaxis_tickformat=".0%", height=420, legend=dict(orientation="h"))
        st.plotly_chart(fig, width="stretch")

        # média ± desvio por subunidade
        th = resumo_coluna(dh, "hora_media", filho)
        tard = dh.groupby(filho, observed=True)[["votos_apos_17", "votos_log"]].sum()
        tard["pct_apos_17"] = tard["votos_apos_17"] / tard["votos_log"]
        th = th.merge(tard["pct_apos_17"], left_on=filho, right_index=True, how="left")
        th[rotulo] = th[rotulo].astype(str)
        if len(th) <= 40:
            t = th.sort_values("media")
            fig = go.Figure(go.Scatter(
                x=t["media"], y=t[rotulo], mode="markers",
                error_x=dict(type="data", array=t["desvio_padrao"].fillna(0), color="#b8c0cc"),
                marker=dict(size=9, color="#33415c"),
                customdata=np.stack([t["secoes"], t["pct_apos_17"]], axis=1),
                hovertemplate="%{y}<br>hora média %{x:.2f}h<br>seções %{customdata[0]}<br>"
                              "votos após 17h %{customdata[1]:.2%}<extra></extra>"))
            fig.add_vline(x=dh["hora_media"].mean(), line_dash="dash", annotation_text="média do nível acima")
            fig.update_layout(title="Hora média do voto: média ± 1 desvio padrão entre as seções",
                              xaxis_title="hora (decimal, Brasília)", height=max(350, 22 * len(t) + 80),
                              margin=dict(l=10, r=10, t=50, b=10))
        else:
            fig = px.scatter(th, x="media", y="pct_apos_17", size="secoes", hover_name=rotulo,
                             color="desvio_padrao", color_continuous_scale="OrRd", size_max=35,
                             labels={"media": "hora média (decimal)", "pct_apos_17": "% dos votos após 17h",
                                     "desvio_padrao": "desvio (h)"},
                             title="Cada ponto é uma unidade: hora média × % dos votos após 17h")
            fig.update_layout(yaxis_tickformat=".1%", height=560)
        st.plotly_chart(fig, width="stretch")

        a, b = st.columns(2)
        m, sd = dh["hora_media"].mean(), dh["hora_media"].std()
        fig = histograma(dh["hora_media"], 80, "#33415c")
        for k, estilo in [(0, "solid"), (2, "dot"), (3, "dash")]:
            fig.add_vline(x=m + k * sd, line_dash=estilo, line_color=COR_ALTA if k else "black",
                          annotation_text="média" if k == 0 else f"+{k} dp")
        fig.update_layout(title="Hora média do voto, por seção", xaxis_title="hora (decimal)",
                          yaxis_title="seções", height=380)
        a.plotly_chart(fig, width="stretch")
        fig = histograma(dh.loc[dh["votos_apos_17"] > 0, "pct_apos_17"], 60, COR_ALTA, log_y=True)
        fig.update_layout(title="Seções com votos após 17h: % dos votos depois das 17h (escala log)",
                          xaxis_tickformat=".0%", xaxis_title="% dos votos após 17h", yaxis_title="seções",
                          height=380)
        b.plotly_chart(fig, width="stretch")

        st.markdown("**Seções com mais votos após 17h**")
        cols = [c for c in ["uf", "municipio", "zona", "secao", "votos_apos_17", "pct_apos_17", "sinais",
                            "ultimo_voto", "hora_media", "z_horario", "dif_local_min", "pct_sem_bio_apos_17",
                            "ociosa_antes_17_min", "taxa_abstencao", "votos_log", "nome_local"] if c in dh]
        idx_top = dh[["pct_apos_17", "votos_apos_17"]].sort_values(
            ["pct_apos_17", "votos_apos_17"], ascending=False).head(500).index
        top = dh.loc[idx_top]
        ev_h = st.dataframe(
            top[cols], hide_index=True, width="stretch", height=380, on_select="rerun",
            selection_mode="single-row", key="tab_hora",
            column_config={**{c: st.column_config.NumberColumn(format="percent")
                              for c in ["pct_apos_17", "pct_sem_bio_apos_17", "taxa_abstencao"]},
                           **{c: st.column_config.NumberColumn(format="%.2f")
                              for c in ["hora_media", "ultimo_voto", "z_horario"]},
                           **{c: st.column_config.NumberColumn(format="%.0f")
                              for c in ["dif_local_min", "ociosa_antes_17_min"]}})
        st.caption("Votar depois das 17h é permitido: quem está na fila às 17h vota. Em 2022 foram cerca "
                   "de 4 milhões de votos após as 17h no 1º turno. Por isso, olhe junto os sinais: "
                   "fila de verdade costuma afetar a escola inteira e vem precedida de uma última hora cheia.")
        if ev_h and ev_h.selection and ev_h.selection.rows:
            st.divider()
            detalhe_secao(ctx, top.iloc[ev_h.selection.rows[0]])
