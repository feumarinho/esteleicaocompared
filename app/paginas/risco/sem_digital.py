"""Página «Sem digital» do painel."""
from __future__ import annotations

import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app.comum import (COR_ALTA, COR_NORMAL, amostrar_fundo, com_log, filtrar, resumo_coluna, votos_por_hora)
from app.detalhe import detalhe_secao
from app.cabecalho import render as cabecalho


def render(ctx):
    cabecalho(ctx)
    SEM_LOGS = ctx.SEM_LOGS
    df = ctx.df
    filho = ctx.filho
    limite = ctx.limite
    rotulo = ctx.rotulo
    tem_logs = ctx.tem_logs
    dd = com_log(df) if "pct_sem_digital" in df else df.iloc[0:0]
    if dd.empty:
        st.info(SEM_LOGS if not tem_logs else
                "Os logs foram processados por uma versão antiga. Rode `python baixar_logs.py --refazer`.")
    else:
        ind = st.radio("Indicador", ["Sem digital (total)", "Liberação manual (só quem tem digital)"],
                       horizontal=True,
                       help="Sem digital = eleitor sem digital cadastrada + eleitor liberado pelo mesário. "
                            "Liberação manual = eleitor TEM digital cadastrada, ela não foi reconhecida e o "
                            "mesário liberou com a digital dele.")
        total_ind = ind.startswith("Sem")
        col_p, col_z, col_esp = (("pct_sem_digital", "z_sem_digital", "sem_digital_esperado") if total_ind
                                 else ("pct_manual_cadastrados", "z_manual", "manual_esperado"))

        # perfil hora a hora
        tot, sd, man = (votos_por_hora(dd, p) for p in "hsm")
        horas_ = [h for h in range(6, 24) if tot[h] >= max(30, 0.001 * tot.sum())]
        fig = go.Figure()
        fig.add_trace(go.Bar(x=[f"{h}h" for h in horas_], y=[(sd[h] - man[h]) / tot[h] for h in horas_],
                             name="sem cadastro de digital", marker_color="#e0a33a",
                             customdata=[int(tot[h]) for h in horas_],
                             hovertemplate="%{x}: %{y:.1%} de %{customdata} votos<extra></extra>"))
        fig.add_trace(go.Bar(x=[f"{h}h" for h in horas_], y=[man[h] / tot[h] for h in horas_],
                             name="liberação manual pelo mesário", marker_color=COR_ALTA))
        fig.update_layout(barmode="stack", yaxis_tickformat=".0%", height=380, legend=dict(orientation="h"),
                          title="% dos eleitores de cada hora liberados SEM digital (horário de Brasília; "
                                "horas com menos de 30 votos omitidas)")
        st.plotly_chart(fig, width="stretch")

        # por subunidade
        agg = dd.groupby(filho, observed=True)[["votos_log", "votos_digital", "votos_sem_cadastro",
                                                "votos_manual"]].sum()
        agg["sem_digital_agregado"] = 1 - agg["votos_digital"] / agg["votos_log"]
        agg["manual_agregado"] = agg["votos_manual"] / (agg["votos_log"] - agg["votos_sem_cadastro"])
        td = resumo_coluna(dd, col_p, filho).merge(agg, left_on=filho, right_index=True, how="left")
        z3 = dd[dd[col_z] >= 3].groupby(filho, observed=True).size().rename("secoes_z3")
        td = td.merge(z3, left_on=filho, right_index=True, how="left").fillna({"secoes_z3": 0})
        td[rotulo] = td[rotulo].astype(str)
        if len(td) <= 40:
            t = td.sort_values("media")
            fig = go.Figure(go.Scatter(
                x=t["media"], y=t[rotulo], mode="markers",
                error_x=dict(type="data", array=t["desvio_padrao"].fillna(0), color="#b8c0cc"),
                marker=dict(size=9, color="#33415c"),
                customdata=np.stack([t["secoes"], t["secoes_z3"]], axis=1),
                hovertemplate="%{y}<br>média %{x:.1%}<br>seções %{customdata[0]}<br>"
                              "seções com z ≥ 3: %{customdata[1]}<extra></extra>"))
            fig.add_vline(x=dd[col_p].mean(), line_dash="dash", annotation_text="média do nível acima")
            fig.update_layout(title=f"{ind}: média ± 1 desvio padrão entre as seções",
                              xaxis_tickformat=".0%", height=max(350, 22 * len(t) + 80),
                              margin=dict(l=10, r=10, t=50, b=10))
        else:
            fig = px.scatter(td, x="sem_digital_agregado", y="manual_agregado", size="votos_log",
                             color="secoes_z3", hover_name=rotulo, color_continuous_scale="OrRd", size_max=35,
                             labels={"sem_digital_agregado": "% sem digital (total)",
                                     "manual_agregado": "% liberação manual (de quem tem digital)",
                                     "secoes_z3": "seções z≥3"},
                             title="Cada ponto é uma unidade: sem digital × liberação manual")
            fig.update_layout(xaxis_tickformat=".0%", yaxis_tickformat=".0%", height=560)
        st.plotly_chart(fig, width="stretch")

        # funil: proporção × número de votos
        pts = filtrar(dd, dd[col_z].notna(), ["municipio", "zona", "secao", col_p, col_z, col_esp,
                                              "votos_log", "votos_sem_cadastro"])
        den = pts["votos_log"] if total_ind else pts["votos_log"] - pts["votos_sem_cadastro"]
        flag = pts[col_z] >= limite
        keep = amostrar_fundo(pts[[]], flag).index
        pts, den, flag = pts.loc[keep], den.loc[keep], flag.loc[keep]
        fig = go.Figure()
        for nome, m, cor, tam, op in [("demais", ~flag, COR_NORMAL, 4, .35),
                                      (f"z ≥ {limite} (acima do esperado no município)", flag, COR_ALTA, 8, .95)]:
            d = pts[m]
            fig.add_trace(go.Scattergl(
                x=den[m], y=d[col_p], mode="markers", name=nome, marker=dict(size=tam, color=cor, opacity=op),
                text=(d["municipio"].astype(str) + " · Z" + d["zona"].astype(str) + " · S" + d["secao"].astype(str)
                      + "<br>esperado " + (d[col_esp] * 100).round(1).astype(str) + "% · z "
                      + d[col_z].round(1).astype(str)),
                hovertemplate="%{text}<br>%{y:.1%} de %{x} eleitores<extra></extra>"))
        fig.update_layout(title=f"{ind} × tamanho da seção (seções pequenas variam mais por acaso)",
                          xaxis_title="eleitores (votos no log)" if total_ind else "eleitores com digital cadastrada",
                          yaxis_title=ind, yaxis_tickformat=".0%", height=520, legend=dict(orientation="h"))
        st.plotly_chart(fig, width="stretch")

        sel = dd[dd[col_z] >= limite].sort_values(col_z, ascending=False)
        st.write(f"**{len(sel):,}** seções com {ind.lower()} {limite}+ desvios acima do esperado para o município. "
                 "Selecione uma linha para ver o detalhe.")
        cols = [c for c in ["uf", "municipio", "zona", "secao", col_z, col_p, col_esp, "pct_sem_cadastro",
                            "votos_manual", "maior_seq_manual", "dif_local_sem_digital_pp", "z_sem_digital",
                            "z_manual", "taxa_abstencao", "z_ajustado", "pct_apos_17", "sinais", "votos_log",
                            "nome_local"] if c in sel]
        cols = list(dict.fromkeys(cols))
        ev_d = st.dataframe(
            sel[cols], hide_index=True, width="stretch", height=400, on_select="rerun",
            selection_mode="single-row", key="tab_dig",
            column_config={**{c: st.column_config.NumberColumn(format="percent")
                              for c in ["pct_sem_digital", "pct_manual_cadastrados", "sem_digital_esperado",
                                        "manual_esperado", "pct_sem_cadastro", "taxa_abstencao", "pct_apos_17"]},
                           **{c: st.column_config.NumberColumn(format="%.2f")
                              for c in ["z_sem_digital", "z_manual", "z_ajustado"]},
                           "dif_local_sem_digital_pp": st.column_config.NumberColumn(format="%+.0f p.p.")})
        st.download_button("⬇️ Baixar lista (CSV)", sel[cols].to_csv(index=False, sep=";", decimal=",")
                           .encode("utf-8-sig"), "secoes_sem_digital.csv", "text/csv", key="dl_dig")
        st.caption("Liberar sem digital é previsto em lei e comum (~1 em cada 5 eleitores em 2022): "
                   "eleitor sem cadastro biométrico, idosos e trabalhadores braçais com digitais gastas, "
                   "leitor com defeito ou sujo. Por isso o z compara cada seção com o próprio município. "
                   "Sinais mais fortes: muitas LIBERAÇÕES MANUAIS (eleitor tinha digital), em SEQUÊNCIA, "
                   "numa seção que destoa das outras da mesma escola.")
        if ev_d and ev_d.selection and ev_d.selection.rows:
            st.divider()
            detalhe_secao(ctx, sel.iloc[ev_d.selection.rows[0]])
