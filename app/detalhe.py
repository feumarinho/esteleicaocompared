"""Detalhe de uma seção: indicadores, comparação com a escola e o município."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app.comum import (COR_ALTA, COR_BAIXA, COR_NORMAL, hora, linha_df, pct, perfil_horario, votos_por_hora)


def detalhe_secao(ctx, s):
    NOME_CRUZ = ctx.NOME_CRUZ
    base = ctx.base
    st.subheader(f"Seção {s['secao']} · Zona {s['zona']} · {s['municipio']}/{s['uf']}")
    if "nome_local" in s and pd.notna(s.get("nome_local")):
        st.caption(f"Local de votação: {s['nome_local']}"
                   + (f" — {s['endereco_local']}" if pd.notna(s.get('endereco_local')) else ""))
    k = st.columns(5)
    k[0].metric("Abstenção da seção", pct(s["taxa_abstencao"]),
                f"{(s['taxa_abstencao'] - s['taxa_esperada']) * 100:+.1f} p.p. vs esperado",
                delta_color="inverse")
    k[1].metric("Aptos / faltaram", f"{s['aptos']} / {s['abstencoes']}",
                f"esperado ≈ {s['abst_esperadas']:.0f}", delta_color="off")
    k[2].metric("z ajustado", f"{s['z_ajustado']:+.2f}")
    k[3].metric("Percentil no município", pct(s["pct_municipio"], 0))
    k[4].metric("Percentil no Brasil", pct(s["pct_brasil"], 0))

    zona_df = base[(base["cd_municipio"] == s["cd_municipio"]) & (base["zona"] == s["zona"])]
    mun_df = base[base["cd_municipio"] == s["cd_municipio"]]
    uf_tx = base.loc[base["uf"] == s["uf"], "taxa_abstencao"]
    comp = pd.DataFrame({
        "nível": ["Esta seção", f"Zona {s['zona']}", "Município", s["uf"], "Brasil"],
        "media": [s["taxa_abstencao"]] + [x.mean() for x in (zona_df["taxa_abstencao"], mun_df["taxa_abstencao"],
                                                             uf_tx, base["taxa_abstencao"])],
        "dp": [0] + [x.std() for x in (zona_df["taxa_abstencao"], mun_df["taxa_abstencao"],
                                       uf_tx, base["taxa_abstencao"])],
    })
    a, b = st.columns(2)
    fig = go.Figure(go.Bar(x=comp["nível"], y=comp["media"],
                           error_y=dict(type="data", array=comp["dp"], visible=True),
                           marker_color=[COR_ALTA if s["z_ajustado"] > 0 else COR_BAIXA] + [COR_NORMAL] * 4,
                           text=[pct(v) for v in comp["media"]], textposition="outside"))
    fig.update_layout(title="Comparação (barra = média, traço = ± 1 desvio padrão)",
                      yaxis_tickformat=".0%", height=360, margin=dict(t=50, b=10))
    a.plotly_chart(fig, width="stretch")

    fig = px.histogram(mun_df, x="taxa_abstencao", nbins=40, color_discrete_sequence=[COR_NORMAL],
                       title="Onde a seção cai entre as seções do município")
    fig.add_vline(x=s["taxa_abstencao"], line_color=COR_ALTA, line_width=3,
                  annotation_text="esta seção")
    fig.update_layout(xaxis_tickformat=".0%", height=360, margin=dict(t=50, b=10),
                      xaxis_title="taxa de abstenção", yaxis_title="seções")
    b.plotly_chart(fig, width="stretch")

    vizinhas = None
    if "local" in s and pd.notna(s.get("local")):
        vizinhas = mun_df[(mun_df["zona"] == s["zona"]) & (mun_df["local"] == s["local"])]

    if s.get("tem_log", False):
        st.markdown("#### ⏰ Horário dos votos (log da urna)")
        k = st.columns(6)
        k[0].metric("Hora média", hora(s["hora_media"]),
                    f"{(s['hora_media'] - mun_df['hora_media'].median()) * 60:+.0f} min vs município",
                    delta_color="inverse")
        k[1].metric("Votos após 17h", f"{int(s['votos_apos_17'])}  ({pct(s['pct_apos_17'])})")
        k[2].metric("Último voto", hora(s["ultimo_voto"]))
        k[3].metric("Sem biometria após 17h", pct(s["pct_sem_bio_apos_17"], 0),
                    f"{pct(s['pct_sem_bio'], 0)} no dia todo", delta_color="off")
        k[4].metric("z horário", f"{s['z_horario']:+.2f}" if pd.notna(s["z_horario"]) else "—")
        k[5].metric("Score cruzado", f"{s['score_cruzado']:+.2f}" if pd.notna(s.get("score_cruzado")) else "—",
                    help=f"Critérios: {NOME_CRUZ}")
        if s.get("sinais"):
            st.warning("**Sinais no log:** " + s["sinais"])

        perfis = {"Esta seção": perfil_horario(linha_df(s))}
        if vizinhas is not None:
            outras = vizinhas[vizinhas["secao"] != s["secao"]]
            if outras["tem_log"].any():
                perfis["Outras seções da escola"] = perfil_horario(outras)
        perfis["Município"] = perfil_horario(mun_df)
        fig = go.Figure()
        for (nome, p), cor in zip(perfis.items(), [COR_ALTA, "#33415c", COR_NORMAL]):
            p = p[(p.index >= 6) & (p.index <= 23)]
            fig.add_trace(go.Bar(x=[f"{h}h" for h in p.index], y=p.values, name=nome, marker_color=cor))
        fig.add_vline(x=10.5, line_dash="dash", line_color="black", annotation_text="17h encerramento")
        fig.update_layout(barmode="group", yaxis_tickformat=".0%", height=380, margin=dict(t=40, b=10),
                          title="% dos votos em cada hora (horário de Brasília)", legend=dict(orientation="h"))
        st.plotly_chart(fig, width="stretch")
        st.caption(f"Abertura da urna: {hora(s['abertura'])} · primeiro voto {hora(s['primeiro_voto'])} · "
                   f"maior intervalo sem votos entre 16h e 17h: {s['ociosa_antes_17_min']:.0f} min · "
                   f"votos no log: {int(s['votos_log'])} (comparecimento oficial: {int(s['comparecimento'])}) · "
                   f"urnas usadas: {int(s['n_urnas'])}")

    if s.get("tem_log", False) and pd.notna(s.get("votos_digital")):
        st.markdown("#### 🖐️ Identificação do eleitor")
        n = int(s["votos_log"])
        k = st.columns(5)
        k[0].metric("Sem digital", pct(s["pct_sem_digital"]),
                    f"{(s['pct_sem_digital'] - s['sem_digital_esperado']) * 100:+.1f} p.p. vs esperado",
                    delta_color="inverse")
        k[1].metric("Sem cadastro de digital", f"{int(s['votos_sem_cadastro'])} ({pct(s['pct_sem_cadastro'])})")
        k[2].metric("Liberação manual", f"{int(s['votos_manual'])} ({pct(s['pct_manual_cadastrados'])})",
                    f"esperado ≈ {pct(s['manual_esperado'])} de quem tem digital", delta_color="off")
        k[3].metric("Maior sequência manual", int(s["maior_seq_manual"]),
                    help="Maior número de eleitores seguidos liberados manualmente pelo mesário")
        k[4].metric("z sem digital / z manual", f"{s['z_sem_digital']:+.1f} / {s['z_manual']:+.1f}"
                    if pd.notna(s["z_sem_digital"]) else "—")
        um = linha_df(s)
        tot, sd, man = (votos_por_hora(um, p) for p in "hsm")
        faixa = [h for h in range(6, 24) if tot[h] > 0]
        if faixa:
            horas_ = list(range(min(faixa), max(faixa) + 1))
            fig = go.Figure()
            for nome, serie, cor in [("digital", tot - sd, "#9aa4b1"), ("sem cadastro", sd - man, "#e0a33a"),
                                     ("liberação manual", man, COR_ALTA)]:
                fig.add_trace(go.Bar(x=[f"{h}h" for h in horas_], y=[serie[h] for h in horas_], name=nome,
                                     marker_color=cor))
            fig.update_layout(barmode="stack", height=340, margin=dict(t=40, b=10), legend=dict(orientation="h"),
                              title=f"Como cada eleitor foi liberado, hora a hora ({n} votos)",
                              yaxis_title="votos")
            st.plotly_chart(fig, width="stretch")

    if vizinhas is not None:
        st.markdown("**Outras seções do mesmo local de votação** (mesma escola, mesmo público — "
                    "se só esta destoa, é um sinal mais forte)")
        cols_v = ["secao", "aptos", "abstencoes", "taxa_abstencao", "z_ajustado"]
        if vizinhas["tem_log"].any():
            cols_v += ["hora_media", "pct_apos_17", "ultimo_voto", "z_horario"]
            if "pct_sem_digital" in vizinhas:
                cols_v += ["pct_sem_digital", "pct_sem_cadastro", "pct_manual_cadastrados", "z_manual"]
        st.dataframe(vizinhas[cols_v].sort_values("secao"), hide_index=True, width="stretch",
                     column_config={**{c: st.column_config.NumberColumn(format="percent")
                                       for c in ["taxa_abstencao", "pct_apos_17", "pct_sem_bio_apos_17",
                                                 "pct_sem_digital", "pct_sem_cadastro", "pct_manual_cadastrados"]},
                                    **{c: st.column_config.NumberColumn(format="%.2f")
                                       for c in ["z_ajustado", "z_horario", "hora_media", "ultimo_voto",
                                                 "z_manual"]}})

