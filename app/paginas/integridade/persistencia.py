"""As seções de risco do 1º turno continuam de risco no 2º? E o desempenho nelas?"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app.dados_integridade import aviso_cobertura, integridade

CRITS = {"abst": "Abstenção baixa", "17": "Voto após 17h", "man": "Liberação manual"}


def render(ctx):
    tab, resumo = integridade()
    st.subheader("🔁 O risco se repete no 2º turno?")
    st.markdown(
        "O painel original marca seções por três critérios nos logs do **1º turno**. Agora temos os logs do **2º** e "
        "dá para ver se as mesmas seções voltam a se destacar. Uma seção cuja urna, mesário ou eleitorado têm a "
        "característica de forma **estável** (digitais ruins, população idosa, escola com fila) volta a ser marcada; "
        "uma marca isolada num só turno é mais compatível com acaso ou evento do dia.")
    aviso_cobertura(resumo)
    p = pd.DataFrame(resumo["persistencia"])
    st.dataframe(p.rename(columns={"criterio": "critério", "secoes_t1": "marcadas no 1º", "t2_dado_t1": "% marcadas também no 2º",
                                   "t2_dado_nao_t1": "% das demais marcadas no 2º", "razao": "razão", "ambos": "nos dois turnos"}),
                 hide_index=True, width="stretch",
                 column_config={"% marcadas também no 2º": st.column_config.NumberColumn(format="percent"),
                                "% das demais marcadas no 2º": st.column_config.NumberColumn(format="percent"),
                                "razão": st.column_config.NumberColumn(format="%.1f")})
    st.caption("Razão alta = o critério mede algo estável da seção. O critério de voto após 17h quase não se repete: no 2º turno "
               "houve menos fila, então ele reflete mais o dia da eleição do que a seção.")

    st.markdown("#### Desempenho do Lula nas seções marcadas")
    base = tab.dropna(subset=["z_desvio_13"])
    linhas = []
    for k, rot in CRITS.items():
        for rotulo, m in ((f"{rot} — só 1º turno", base[f"f1_{k}"] & ~base[f"f2_{k}"]),
                          (f"{rot} — só 2º turno", ~base[f"f1_{k}"] & base[f"f2_{k}"]),
                          (f"{rot} — nos dois", base[f"f1_{k}"] & base[f"f2_{k}"])):
            g = base[m]
            z = g["z_desvio_13"].dropna()
            linhas.append({"grupo": rotulo, "seções": len(g), "z médio (Lula vs município)": z.mean() if len(z) else None,
                           "± IC 95%": 1.96 * z.std(ddof=1) / len(z) ** 0.5 if len(z) > 1 else None,
                           "variação do Lula (p.p.)": g["d_lula_pp"].mean() if len(g) else None})
    linhas.append({"grupo": "Todas as demais seções", "seções": len(base), "z médio (Lula vs município)": base["z_desvio_13"].mean(),
                   "± IC 95%": 1.96 * base["z_desvio_13"].std() / len(base) ** 0.5, "variação do Lula (p.p.)": base["d_lula_pp"].mean()})
    st.dataframe(pd.DataFrame(linhas), hide_index=True, width="stretch",
                 column_config={c: st.column_config.NumberColumn(format="%.2f") for c in ("z médio (Lula vs município)", "± IC 95%", "variação do Lula (p.p.)")})
    st.caption("z médio ≈ 0 significa que o grupo se comporta como o resto do município. Grupos pequenos têm intervalo largo.")

    st.markdown("#### Seções marcadas nos dois turnos")
    c1, c2 = st.columns(2)
    crit = c1.selectbox("Critério", list(CRITS), format_func=CRITS.get)
    uf = c2.selectbox("UF", ["Todas", *resumo["ufs"]])
    x = tab[tab[f"f1_{crit}"] & tab[f"f2_{crit}"]]
    if uf != "Todas":
        x = x[x["uf"] == uf]
    st.caption(f"{len(x):,} seções".replace(",", "."))
    cols = ["uf", "municipio", "zona", "secao", "bu_comparecimento", "lula_pct", "d_lula_pp", "z_desvio_13", "d_abst_pp", "d_bn_pp"]
    st.dataframe(x.sort_values("z_desvio_13", ascending=False)[cols].head(1000), hide_index=True, width="stretch",
                 column_config={"lula_pct": st.column_config.NumberColumn("% Lula 2º", format="percent"),
                                "d_lula_pp": st.column_config.NumberColumn("var. Lula (p.p.)", format="%.1f"),
                                "z_desvio_13": st.column_config.NumberColumn("z Lula", format="%.2f"),
                                "d_abst_pp": st.column_config.NumberColumn("var. abstenção (p.p.)", format="%.1f"),
                                "d_bn_pp": st.column_config.NumberColumn("var. B+N (p.p.)", format="%.1f")})
