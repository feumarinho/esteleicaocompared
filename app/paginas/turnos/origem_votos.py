"""Página «De onde vêm os votos» do painel."""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.comum import (NOMES_CURTOS, _mi, _pt, arquivos_turnos, candidatos_turnos, carregar_fluxo, estimar_fluxos)


def _grupo_simples(k: str, cands: dict[int, str]) -> str:
    if k == "demais":
        return "Votaram em outros candidatos"
    if k == "brancos_nulos":
        return "Votaram em branco ou nulo"
    if k == "abstencao":
        return "Não votaram no 1º turno"
    n = int(k[1:])
    return "Votaram no " + NOMES_CURTOS.get(n, cands.get(n, k).title().split()[0]) + " no 1º turno"


def _qtd(x: float) -> str:
    """Quantidade de votos em linguagem comum: '10,87 milhões', '870 mil', '4 mil'."""
    return f"{_pt(x / 1e6, 2)} milhões" if abs(x) >= 1e6 else f"{_pt(round(x / 1e3))} mil"


def _frase(s: str) -> str:
    return s[0].lower() + s[1:]


def render(ctx):
    arquivo = ctx.arquivo
    incluir_zz = ctx.incluir_zz
    ano_o = arquivo.stem.split("_")[1]
    if arquivos_turnos(ano_o) is None:
        st.info("Para ver esta seção faltam arquivos em `dados/`. Rode `python baixar_dados.py --turno 1`, "
                "`python baixar_dados.py --turno 2` e `python baixar_votos.py`.")
    else:
        cands_o = candidatos_turnos(ano_o)
        prep_o = carregar_fluxo(ano_o, tuple((q.name, q.stat().st_mtime) for q in arquivos_turnos(ano_o).values()),
                                incluir_zz)
        c1_, c2_ = st.columns([2, 1])
        escolha = c1_.radio("Candidato", sorted(cands_o), horizontal=True, key="origem_cand",
                            format_func=lambda n: NOMES_CURTOS.get(n, cands_o[n].title().split()[0]))
        local = c2_.selectbox("Estado", ["Brasil"] + sorted(set(prep_o["uf"])), key="origem_uf")
        quem = NOMES_CURTOS.get(escolha, cands_o[escolha].title().split()[0])
        alvo_o = f"f{escolha}"
        res_o = estimar_fluxos(prep_o, None if local == "Brasil" else [local], n_boot=100)
        Fo, lo_o, hi_o = res_o["F"], res_o["lo"], res_o["hi"]
        col = Fo[alvo_o]
        total = float(col.sum())
        proprios = float(col[alvo_o])
        novos = total - proprios
        eleit_1t = float(Fo.sum(axis=1)[alvo_o])

        st.subheader(f"De onde vêm os votos do {quem} no 2º turno — {local}")
        st.markdown(
            f"No 2º turno, o {quem} teve **{_qtd(total)} de votos** "
            f"{'no Brasil' if local == 'Brasil' else 'em ' + local}. "
            f"Cerca de **{_pt(proprios / total * 100)}%** deles ({_qtd(proprios)}) já tinham votado nele "
            f"no 1º turno. Os outros **{_qtd(novos)}** são votos novos.")
        novos_ord = col.drop(index=alvo_o).sort_values(ascending=False)
        novos_ord = novos_ord[novos_ord >= 0.01 * max(novos, 1)]
        if len(novos_ord):
            partes = [f"{_frase(_grupo_simples(o, cands_o))} ({_pt(float(v) / novos * 100)}% dos novos, {_qtd(float(v))})"
                      for o, v in novos_ord.head(3).items()]
            frase = "a maior parte veio dos eleitores que " + partes[0]
            if len(partes) > 1:
                frase += ", seguidos dos que " + partes[1]
            if len(partes) > 2:
                frase += " e dos que " + partes[2]
            st.markdown("Dos votos novos, " + frase + ".")
        fiel = float(Fo.loc[alvo_o, alvo_o]) / eleit_1t if eleit_1t else float("nan")
        st.caption(f"Fidelidade: de cada 100 eleitores do {quem} no 1º turno, cerca de {_pt(fiel * 100)} votaram nele "
                   "de novo.")

        # --- uma barra só com a composição dos votos
        cor_g = {alvo_o: "#b3342d", "c70": "#33415c", "c14": "#5b7db1", "c55": "#8fa8cf", "demais": "#c3cfe3",
                 "brancos_nulos": "#9aa4b1", "abstencao": "#e0a43b"}
        ordem_g = [alvo_o] + [o for o in novos_ord.index] + [o for o in col.index
                                                             if o != alvo_o and o not in novos_ord.index
                                                             and col[o] > 0]
        fig = go.Figure()
        for o in ordem_g:
            v = float(col[o])
            fig.add_trace(go.Bar(
                y=[""], x=[v / total * 100], orientation="h", name=_grupo_simples(o, cands_o) if o != alvo_o
                else f"Já votaram no {quem} no 1º turno",
                marker_color=cor_g.get(o, "#2f6fb5"),
                text=f"{v / total * 100:.0f}%" if v / total >= 0.04 else "", textposition="inside",
                insidetextfont=dict(color="white", size=14),
                hovertemplate=f"%{{x:.1f}}% · {_qtd(v)}<extra>%{{fullData.name}}</extra>"))
        fig.update_layout(barmode="stack", height=210, xaxis=dict(range=[0, 100], ticksuffix="%",
                          title="% dos votos do 2º turno"), margin=dict(l=10, r=10, t=10, b=10),
                          legend=dict(orientation="h", y=-0.55, x=0))
        st.plotly_chart(fig, width="stretch")

        # --- votos novos, um a um
        st.markdown(f"**Os {_qtd(novos)} de votos novos do {quem}, por origem**")
        if len(novos_ord):
            n_ = novos_ord.sort_values()
            fig = go.Figure(go.Bar(
                y=[_grupo_simples(o, cands_o) for o in n_.index], x=n_.to_numpy() / 1e6, orientation="h",
                marker_color=[cor_g.get(o, "#2f6fb5") for o in n_.index],
                text=[_qtd(float(v)) for v in n_], textposition="outside",
                hovertemplate="%{y}: %{x:.2f} mi<extra></extra>"))
            fig.update_layout(height=60 + 46 * len(n_), margin=dict(l=10, r=40, t=10, b=10),
                              xaxis=dict(visible=False, range=[0, float(n_.max()) / 1e6 * 1.3]))
            st.plotly_chart(fig, width="stretch")

        # --- tabela simples
        st.markdown("**Por grupo de eleitores**")
        linhas = []
        for o in col.index:
            if o == alvo_o or col[o] <= 0:
                continue
            base_g = float(Fo.sum(axis=1)[o])
            linhas.append({"Quem eram no 1º turno": _grupo_simples(o, cands_o),
                           "Eleitores nesse grupo": base_g,
                           f"Votaram no {quem} (estimativa)": float(col[o]),
                           f"De cada 100, quantos votaram no {quem}": float(col[o]) / base_g * 100 if base_g else np.nan,
                           "Faixa provável (votos)": f"{_mi(float(lo_o.loc[o, alvo_o]))} a {_mi(float(hi_o.loc[o, alvo_o]))}"})
        st.dataframe(pd.DataFrame(linhas), hide_index=True, width="stretch",
                     column_config={"Eleitores nesse grupo": st.column_config.NumberColumn(format="%d"),
                                    f"Votaram no {quem} (estimativa)": st.column_config.NumberColumn(format="%d"),
                                    f"De cada 100, quantos votaram no {quem}": st.column_config.NumberColumn(format="%.0f")})

        with st.expander("ℹ️ Como esta estimativa é feita e o que ela não mostra"):
            st.markdown(
                "- O voto é secreto: **ninguém sabe como cada pessoa votou**. Esta é uma estimativa feita comparando, "
                "seção por seção, o resultado do 1º e do 2º turno.\n"
                "- Funciona assim: se numa seção havia muitos eleitores de um candidato eliminado e o {q} cresceu "
                "bastante nessa seção, isso sugere que parte desses eleitores foi para ele. Repetindo isso em milhares "
                "de seções, dá para estimar proporções.\n"
                "- Os números são **ordens de grandeza**, não contagens. A \"faixa provável\" mostra a margem de "
                "erro por acaso, mas não cobre erros do método.\n"
                "- Algumas origens são difíceis de separar (por exemplo, quem votou em branco ou nulo e quem não foi "
                "votar costumam estar nos mesmos lugares). Por isso essas duas estimativas são as menos firmes.\n"
                "- Se muitos eleitores trocaram de lado em sentidos opostos ao mesmo tempo, isso não aparece: só o "
                "saldo.".replace("{q}", quem))
