"""Testes forenses clássicos: dígitos finais e impressão digital participação × voto."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.dados_integridade import aviso_cobertura, integridade


def render(ctx):
    tab, resumo = integridade()
    st.subheader("🔬 Testes forenses")
    aviso_cobertura(resumo)
    f = resumo["forense"]

    st.markdown("### 1. Último dígito dos votos por seção")
    st.markdown(
        "Em totais de dezenas ou centenas de votos, o último dígito (0–9) é praticamente sorteado: cada um deve "
        "aparecer em ~10% das seções. Números inventados por quem fraudaria tendem a preferir certos dígitos. "
        "O teste compara com o esperado já descontando a inclinação natural da distribuição (há mais seções com 52 "
        "votos do que com 59).")
    dg = pd.DataFrame([{"UF": d["uf"], "Lula 2º t. (p)": (d["lula_t2"] or {}).get("p"), "Flávio 2º t. (p)": (d["flavio_t2"] or {}).get("p"),
                        "Lula 1º t. (p)": (d["lula_t1"] or {}).get("p"), "seções": (d["lula_t2"] or {}).get("n")} for d in f["digitos"]])
    ps = dg.drop(columns=["UF", "seções"]).iloc[1:].stack()
    n_t = int(ps.notna().sum())
    st.markdown(f"Valores-p: p pequeno = mais estranho. Ao olhar **{n_t} testes**, é esperado que ~{n_t * 0.05:.0f} fiquem abaixo de 0,05 "
                f"só por acaso; ficaram **{int((ps < 0.05).sum())}** (e **{int((ps < 0.001).sum())}** abaixo de 0,001).")
    st.dataframe(dg, hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="%.3f") for c in dg.columns if c.endswith("(p)")})
    uf = st.selectbox("Ver os dígitos de", [d["uf"] for d in f["digitos"]], key="dig_uf")
    d = next(x for x in f["digitos"] if x["uf"] == uf)
    fig = go.Figure()
    for nome, chave, cor in (("Lula", "lula_t2", "#c0392b"), ("Flávio", "flavio_t2", "#2a6fb0")):
        if d[chave] and d[chave].get("contagem") and sum(d[chave]["contagem"]):
            tot = sum(d[chave]["contagem"])
            fig.add_bar(x=list(range(10)), y=[c / tot for c in d[chave]["contagem"]], name=nome, marker_color=cor)
    fig.add_hline(y=0.1, line_dash="dash", line_color="#888")
    fig.update_layout(height=320, barmode="group", margin=dict(l=10, r=10, t=10, b=10), yaxis_tickformat=".0%",
                      xaxis_title="último dígito", yaxis_title="% das seções", xaxis=dict(dtick=1))
    st.plotly_chart(fig, width="stretch")

    st.markdown("### 2. Participação × voto (impressão digital)")
    st.markdown(
        "Quando votos são acrescentados numa seção para um só lado, a seção ganha participação **e** esse lado ganha "
        "percentual: aparece uma correlação positiva forte entre as duas coisas, e um 'braço' de seções com "
        "participação altíssima e quase todos os votos para um lado. Abaixo, a correlação **dentro do município** "
        "(positiva e alta = padrão de alerta) e a contagem de seções com ≥95% de participação e ≥90% para um lado.")
    im = pd.DataFrame(f["impressao"]).rename(columns={
        "uf": "UF", "corr_t2": "correlação 2º turno", "corr_t1": "correlação 1º turno",
        "part_95_lula_90": "≥95% particip. e ≥90% Lula", "part_95_flavio_90": "≥95% particip. e ≥90% Flávio"})
    st.dataframe(im, hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="%.3f") for c in ("correlação 2º turno", "correlação 1º turno")})
    uf2 = st.selectbox("Ver o gráfico de", resumo["ufs"], key="imp_uf")
    g = tab[tab["uf"] == uf2].dropna(subset=["part", "lula_pct"])
    g = g.sample(min(len(g), 8000), random_state=1)
    fig2 = go.Figure(go.Scattergl(x=g["part"], y=g["lula_pct"], mode="markers", marker=dict(size=3, opacity=0.35, color="#2a6fb0"),
                                  text=g["municipio"].astype(str) + " · zona " + g["zona"].astype(str) + " · seção " + g["secao"].astype(str)))
    fig2.update_layout(height=420, margin=dict(l=10, r=10, t=10, b=10), xaxis_title="participação (comparecimento ÷ aptos)",
                       yaxis_title="% do Lula nos votos válidos", xaxis_tickformat=".0%", yaxis_tickformat=".0%")
    st.plotly_chart(fig2, width="stretch")
    st.caption("Resultado esperado quando não há problema: uma nuvem redonda, sem inclinação nem 'braço' em direção ao canto "
               "de alta participação com um candidato próximo de 100%.")
