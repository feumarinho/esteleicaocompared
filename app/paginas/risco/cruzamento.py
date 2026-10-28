"""Página «Cruzamento» do painel."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.comum import (COR_ALTA, COR_NORMAL, CRITERIOS, EIXO_Z, amostrar_fundo, filtrar, hora)
from app.detalhe import detalhe_secao
from app.cabecalho import render as cabecalho


def render(ctx):
    cabecalho(ctx)
    NOME_CRUZ = ctx.NOME_CRUZ
    SEM_LOGS = ctx.SEM_LOGS
    criterios = ctx.criterios
    df = ctx.df
    limite_cruz = ctx.limite_cruz
    tem_logs = ctx.tem_logs
    mask_c = (df["tem_log"] & df["score_cruzado"].notna()) if tem_logs else pd.Series(False, index=df.index)
    dc = filtrar(df, mask_c, ["municipio", "zona", "secao", "score_cruzado", "taxa_abstencao", "hora_media",
                              "pct_apos_17", "pct_sem_digital", "sinais"]
                 + [c for crit in CRITERIOS.values() for c in crit[:2]])
    if dc.empty:
        st.info(SEM_LOGS)
    else:
        st.markdown(f"**Critérios (barra lateral):** {NOME_CRUZ} — todos ≥ {limite_cruz} desvios.")
        cx = criterios[0]
        cy = criterios[1] if len(criterios) > 1 else ("Votação tardia" if cx != "Votação tardia" else "Abstenção baixa")
        eixos = st.radio("Eixos", ["Padronizados (z, comparando com o próprio município)", "Valores brutos"],
                         horizontal=True)
        padr = eixos.startswith("Padr")
        xcol = CRITERIOS[cx][0] if padr else CRITERIOS[cx][1]
        ycol = CRITERIOS[cy][0] if padr else CRITERIOS[cy][1]
        if xcol not in dc or ycol not in dc:
            st.warning("Indicador indisponível nestes dados. Rode `python baixar_logs.py --refazer`.")
            st.stop()
        destaque = dc["score_cruzado"] >= limite_cruz
        pontos = dc
        pontos = amostrar_fundo(dc, destaque)
        hover = (pontos["municipio"].astype(str) + " · Z" + pontos["zona"].astype(str) + " · S"
                 + pontos["secao"].astype(str) + "<br>abstenção " + (pontos["taxa_abstencao"] * 100).round(1).astype(str)
                 + "% · hora média " + pontos["hora_media"].map(hora) + " · após 17h "
                 + (pontos["pct_apos_17"] * 100).round(1).astype(str) + "%")
        if "pct_sem_digital" in pontos:
            hover = hover + " · sem digital " + (pontos["pct_sem_digital"] * 100).round(1).astype(str) + "%"
        hover = hover + "<br>" + pontos["sinais"].fillna("")
        fig = go.Figure()
        for nome, mask, cor, tam, op in [("demais seções", pontos["score_cruzado"] < limite_cruz, COR_NORMAL, 4, .35),
                                         (NOME_CRUZ, pontos["score_cruzado"] >= limite_cruz, COR_ALTA, 9, .95)]:
            d = pontos[mask]
            fig.add_trace(go.Scattergl(
                x=d[xcol].clip(-12, 15) if padr else d[xcol], y=d[ycol].clip(-12, 15) if padr else d[ycol],
                mode="markers", name=nome, marker=dict(size=tam, color=cor, opacity=op),
                text=hover[mask], hovertemplate="%{text}<extra></extra>"))
        if padr:
            fig.add_shape(type="rect", x0=limite_cruz, x1=15, y0=limite_cruz, y1=15,
                          fillcolor=COR_ALTA, opacity=0.07, line_width=0)
            for v in (-limite_cruz, limite_cruz):
                fig.add_vline(x=v, line_dash="dot", line_color="#888")
                fig.add_hline(y=v, line_dash="dot", line_color="#888")
            fig.update_layout(xaxis_title=EIXO_Z[cx], yaxis_title=EIXO_Z[cy])
        else:
            fig.update_layout(xaxis_title=CRITERIOS[cx][2], yaxis_title=CRITERIOS[cy][2],
                              xaxis_tickformat=".0%", yaxis_tickformat=".0%")
        extra = f" (os demais critérios — {', '.join(criterios[2:]).lower()} — entram no destaque)" \
            if len(criterios) > 2 else ""
        fig.update_layout(title=f"Cada ponto é uma seção: {cx.lower()} × {cy.lower()}{extra}", height=620,
                          legend=dict(orientation="h"))
        st.plotly_chart(fig, width="stretch")

        sel = df[mask_c & (df["score_cruzado"] >= limite_cruz)].sort_values(["score_cruzado", "n_sinais"],
                                                                               ascending=False)
        st.write(f"**{len(sel):,}** seções com {NOME_CRUZ} (todos ≥ {limite_cruz}), de {len(dc):,} com log. "
                 "Ordenadas pelo score; a coluna *sinais* resume o que o log mostra.")
        cols = [c for c in ["uf", "municipio", "zona", "secao", "score_cruzado", "n_sinais", "sinais",
                            "taxa_abstencao", "z_ajustado", "hora_media", "z_horario", "pct_apos_17",
                            "pct_sem_digital", "z_sem_digital", "pct_manual_cadastrados", "z_manual",
                            "maior_seq_manual", "ociosa_antes_17_min", "dif_local_min", "aptos", "nome_local"]
                if c in sel]
        ev_c = st.dataframe(
            sel[cols], hide_index=True, width="stretch", height=420, on_select="rerun",
            selection_mode="single-row", key="tab_cruz",
            column_config={**{c: st.column_config.NumberColumn(format="percent")
                              for c in ["taxa_abstencao", "pct_apos_17", "pct_sem_digital", "pct_manual_cadastrados"]},
                           **{c: st.column_config.NumberColumn(format="%.2f")
                              for c in ["z_ajustado", "hora_media", "z_horario", "score_cruzado", "z_sem_digital",
                                        "z_manual"]},
                           **{c: st.column_config.NumberColumn(format="%.0f")
                              for c in ["dif_local_min", "ociosa_antes_17_min"]}})
        st.download_button("⬇️ Baixar lista (CSV)", sel[cols].to_csv(index=False, sep=";", decimal=",")
                           .encode("utf-8-sig"), "cruzamento.csv", "text/csv", key="dl_cruz")
        st.caption("Indicadores andam juntos por motivos comuns: mais eleitores → mais fila → votação tardia; "
                   "região sem cadastro biométrico → mais eleitores sem digital. O que diferencia é o contexto: "
                   "compare com as outras seções da mesma escola (detalhe da seção) e veja os sinais do log.")
        if ev_c and ev_c.selection and ev_c.selection.rows:
            st.divider()
            detalhe_secao(ctx, sel.iloc[ev_c.selection.rows[0]])
