"""2018 × 2022 × 2026: o que é comum a todas as eleições e o que é novo em 2026."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ARQ = Path(__file__).resolve().parents[3] / "resultados" / "historico_2018_2026.json"
NOMES = {13: "Lula", 17: "Bolsonaro", 22: "Bolsonaro"}


@st.cache_data
def _ler():
    return json.loads(ARQ.read_text(encoding="utf-8"))


def render(ctx):
    st.subheader("📚 Referência histórica: 2018 × 2022 × 2026")
    if not ARQ.exists():
        st.info("Arquivo `resultados/historico_2018_2026.json` ausente.")
        return
    h = _ler()
    st.markdown(
        "Qualquer padrão do 2º turno de 2026 só faz sentido se for comparado com o que acontece nas outras eleições. "
        "Os mesmos cálculos foram feitos com os dados públicos do TSE de **2018** e **2022** (presidente, todas as seções).")
    r = pd.DataFrame(h["resumo"])
    r["segundo"] = [NOMES.get(int(v), v) for v in r["vice1"]]
    r["lider"] = [NOMES.get(int(v), v) for v in r["lider1"]]
    r["razão (2º lugar ÷ líder)"] = r["ganho_vice"] / r["ganho_lider"]
    t = r[["ano", "lider", "segundo", "abst1", "abst2", "bn1_pct", "bn2_pct", "ganho_lider", "ganho_vice", "razão (2º lugar ÷ líder)"]]
    st.dataframe(t.rename(columns={"abst1": "abstenção 1º", "abst2": "abstenção 2º", "bn1_pct": "branco+nulo 1º", "bn2_pct": "branco+nulo 2º",
                                   "ganho_lider": "votos ganhos pelo líder do 1º", "ganho_vice": "votos ganhos pelo 2º colocado do 1º"}),
                 hide_index=True, width="stretch",
                 column_config={**{c: st.column_config.NumberColumn(format="percent") for c in
                                   ("abstenção 1º", "abstenção 2º", "branco+nulo 1º", "branco+nulo 2º")},
                                "votos ganhos pelo líder do 1º": st.column_config.NumberColumn(format="localized"),
                                "votos ganhos pelo 2º colocado do 1º": st.column_config.NumberColumn(format="localized"),
                                "razão (2º lugar ÷ líder)": st.column_config.NumberColumn(format="%.1f")})
    st.markdown(
        "**Leitura:** em toda eleição de 2º turno o candidato que ficou em 2º no 1º turno ganha **mais** votos que o líder "
        "(os eleitores dos eliminados se dividem, e o líder já tinha parte dos seus). Em 2026 a razão é a mais alta das três, "
        "mas a direção é a mesma.")

    st.markdown("### Brancos e nulos caem onde não há 2º turno para governador")
    st.markdown(
        "A cédula do 2º turno muda conforme o estado tenha ou não 2º turno para governador. Nos estados **sem** governador no "
        "2º turno, o eleitor só vota para presidente e brancos/nulos costumam cair. Para cada ano, a razão "
        "(branco+nulo no 2º ÷ no 1º) separando os dois tipos de estado:")
    linhas = []
    for ano, d in h["bn_uf"].items():
        t_ = pd.DataFrame(d["tabela"])
        for rot, m in (("com governador no 2º turno", t_["gov2t"]), ("sem governador no 2º turno", ~t_["gov2t"])):
            s = t_[m]
            if len(s):
                p1, p2 = s.bn1.sum() / s.tot1.sum(), s.bn2.sum() / s.tot2.sum()
                linhas.append({"ano": int(ano), "estados": rot, "UFs": len(s), "B+N 1º turno": p1, "B+N 2º turno": p2, "razão": p2 / p1})
    d = pd.DataFrame(linhas)
    st.dataframe(d, hide_index=True, width="stretch",
                 column_config={"B+N 1º turno": st.column_config.NumberColumn(format="percent"),
                                "B+N 2º turno": st.column_config.NumberColumn(format="percent"),
                                "razão": st.column_config.NumberColumn(format="%.2f")})
    fig = go.Figure()
    for rot, cor in (("com governador no 2º turno", "#888"), ("sem governador no 2º turno", "#c0392b")):
        x = d[d["estados"] == rot]
        fig.add_bar(x=x["ano"].astype(str), y=x["razão"], name=rot, marker_color=cor)
    fig.add_hline(y=1, line_dash="dash", line_color="#444")
    fig.update_layout(height=320, barmode="group", margin=dict(l=10, r=10, t=10, b=10), yaxis_title="B+N 2º ÷ B+N 1º")
    st.plotly_chart(fig, width="stretch")
    st.markdown(
        "**Leitura:** a queda de brancos/nulos nos estados sem governador no 2º turno **também aconteceu em 2018 e 2022**: é "
        "esperada. Em 2026 a queda foi mais forte (razão menor); isso merece investigação, mas diferenças na mobilização, no número "
        "de estados sem 2º turno (21 em 2026) e na rejeição dos candidatos explicam parte dela.")

    st.markdown("### De onde vieram os votos adicionais do 2º colocado (estimativa)")
    f = h["fluxos"]
    linhas = []
    for ano, d in f.items():
        vice = NOMES.get(d["vice"], d["vice"])
        linhas.append({"ano": int(ano), "candidato": vice, "ganho total": d["ganho_vice"], "de brancos/nulos": d["bn"]["p_vice"],
                       "de eleitores dos eliminados": d["outros"]["p_vice"], "do líder do 1º": d["lider_para_vice"]})
    st.dataframe(pd.DataFrame(linhas), hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="localized") for c in
                                ("ganho total", "de brancos/nulos", "de eleitores dos eliminados", "do líder do 1º")})
    st.caption("Mesma regressão ecológica da aba Fluxo de votos, aplicada aos três anos. Ver a ressalva de que são estimativas "
               "por seção, não votos individuais.")
