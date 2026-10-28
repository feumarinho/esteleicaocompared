"""Boletim de urna × RDV × log × resultado oficial: as quatro fontes contam a mesma história?"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.dados_integridade import aviso_cobertura, integridade

TESTES = {
    "bu_diferente_rdv": ("Boletim ≠ RDV", "chk_bu_rdv"),
    "bu_diferente_comparecimento": ("Soma do boletim ≠ comparecimento", "chk_bu_comp"),
    "log_diferente_bu": ("Votos no log ≠ comparecimento do boletim", "chk_log_bu"),
    "habilitados_diferente_votos": ("Confirmações de voto ≠ votos computados (log)", "chk_conf_pres"),
    "bu_diferente_oficial": ("Boletim ≠ resultado oficial publicado", "chk_bu_oficial"),
}


def render(ctx):
    tab, resumo = integridade()
    st.subheader("⚖️ Boletim de urna × RDV × log × resultado oficial")
    st.markdown(
        "Cada urna deixa **três registros independentes** do 2º turno: o **boletim de urna (BU)** com a contagem, o "
        "**registro digital do voto (RDV)** com cada voto embaralhado e o **log** com tudo o que a urna fez. O TSE ainda "
        "publica o **resultado por seção**. Se tudo estiver certo, os quatro batem. Aqui está a conferência, seção por seção.")
    aviso_cobertura(resumo)
    c = pd.DataFrame(resumo["conciliacao"])
    tot = c.drop(columns="uf").sum()
    k = st.columns(5)
    for col, (campo, (rot, _)) in zip(k, TESTES.items()):
        col.metric(rot, f"{tot[campo]:,}".replace(",", "."), f"{tot[campo] / tot['secoes']:.2%} das seções", delta_color="off")
    st.caption("Diferença **não** é fraude: o log pode perder uma linha por falha de gravação, uma urna substituída "
               "durante o dia divide a votação em dois logs, e o contador de confirmações conta eventos, não eleitores. "
               "O que pesa é o **boletim ≠ RDV** e o **boletim ≠ oficial**, que deveriam ser sempre iguais.")
    por_uf = c.copy()
    for campo in TESTES:
        por_uf[campo + "_pct"] = por_uf[campo] / por_uf["secoes"]
    st.dataframe(por_uf[["uf", "secoes", *TESTES]].rename(columns={k: v[0] for k, v in TESTES.items()}),
                 hide_index=True, width="stretch")

    st.markdown("#### Lista de seções com diferença")
    f1, f2 = st.columns(2)
    teste = f1.selectbox("Tipo de diferença", list(TESTES), format_func=lambda k: TESTES[k][0])
    uf = f2.selectbox("UF", ["Todas", *resumo["ufs"]])
    col = TESTES[teste][1]
    x = tab[tab[col] == False]  # noqa: E712  (NaN fica de fora)
    if uf != "Todas":
        x = x[x["uf"] == uf]
    st.caption(f"{len(x):,} seções".replace(",", "."))
    cols = ["uf", "municipio", "zona", "secao", "bu_comparecimento", "log_votos", "bu_p_13", "bu_p_22", "bu_p_branco",
            "bu_p_nulo", "log_modelo", "log_n_erro"]
    st.dataframe(x[[c for c in cols if c in x]].head(2000), hide_index=True, width="stretch")
