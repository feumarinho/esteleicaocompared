"""Página «Fluxo de votos» do painel."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app.comum import (NOMES_CURTOS, TODOS, _mi, arquivos_turnos, candidatos_turnos, carregar_fluxo, estimar_fluxos)


def _rotulo_origem(k: str, cands: dict[int, str]) -> str:
    fixos = {"demais": "Demais candidatos", "brancos_nulos": "Brancos e nulos", "abstencao": "Abstenção"}
    if k in fixos:
        return fixos[k]
    n = int(k[1:])
    return ("Eleitores de " if k[0] == "f" else "") + NOMES_CURTOS.get(n, cands.get(n, k).title().split()[0])


def render(ctx):
    arquivo = ctx.arquivo
    incluir_zz = ctx.incluir_zz
    mun = ctx.mun
    uf = ctx.uf
    ano_f = arquivo.stem.split("_")[1]
    if arquivos_turnos(ano_f) is None:
        st.info("Para estimar o fluxo de votos faltam arquivos em `dados/`. Rode `python baixar_dados.py --turno 1`, "
                "`python baixar_dados.py --turno 2` e `python baixar_votos.py`.")
    else:
        cands_f = candidatos_turnos(ano_f)
        prep = carregar_fluxo(ano_f, tuple((q.name, q.stat().st_mtime) for q in arquivos_turnos(ano_f).values()),
                              incluir_zz)
        nivel_f = "Brasil" if uf == TODOS else uf
        res = estimar_fluxos(prep, None if uf == TODOS else [uf], n_boot=100)
        F, lo, hi = res["F"], res["lo"], res["hi"]
        orig, dest = list(F.index), list(F.columns)
        nome_o = {k: _rotulo_origem(k, cands_f) for k in orig}
        nome_d = {k: (_rotulo_origem(k, cands_f).replace("Eleitores de ", "") if k.startswith("f")
                      else _rotulo_origem(k, cands_f)) for k in dest}
        fin = [k for k in dest if k.startswith("f")]
        st.subheader(f"Para onde foram os eleitores do 1º turno — {nivel_f}")
        if mun != TODOS:
            st.info("A estimativa precisa de muitas seções; com um município só ela fica instável. "
                    f"Mostrando {nivel_f}.")
        st.caption("Estimativa a partir dos boletins de urna de cada seção nos dois turnos. "
                   "**Não é contagem** (o voto é secreto): é o fluxo que melhor explica as diferenças entre seções.")

        # --- quanto cada finalista ganhou e de onde veio
        total1 = F.sum(axis=1)
        cols = st.columns(len(fin))
        for c, k in zip(cols, fin):
            v1_, v2_ = float(total1[k]), float(F[k].sum())
            novos = F[k].drop(index=k)
            c.metric(f"{nome_d[k]}: votos ganhos", ("+" if v2_ >= v1_ else "") + _mi(v2_ - v1_),
                     help=f"{_mi(v1_)} no 1º turno → {_mi(v2_)} no 2º (zona exterior fora)")
            c.caption("Vieram, na estimativa, de: " + " · ".join(
                f"{nome_o[o]} {_mi(float(x))}" for o, x in novos.sort_values(ascending=False).items() if x >= 5e4))

        # --- Sankey
        so_mov = st.checkbox("Mostrar só quem mudou de escolha (esconde quem repetiu o voto)", value=True,
                             key="fluxo_so_mov")
        pares = [(o, d_) for o in orig for d_ in dest if F.loc[o, d_] > 0.002 * F.to_numpy().sum()
                 and not (so_mov and o == d_)]
        cor_dest = {"f13": "214,69,61", "f22": "47,111,181", "brancos_nulos": "154,164,177", "abstencao": "120,120,120"}
        nos_o = [f"1º · {nome_o[o]}" for o in orig]
        nos_d = [f"2º · {nome_d[d_]}" for d_ in dest]
        fig = go.Figure(go.Sankey(
            arrangement="snap",
            node=dict(label=nos_o + nos_d, pad=14, thickness=16,
                      color=["#9aa4b1"] * len(orig) + ["#33415c"] * len(dest)),
            link=dict(source=[orig.index(o) for o, _ in pares],
                      target=[len(orig) + dest.index(d_) for _, d_ in pares],
                      value=[float(F.loc[o, d_]) for o, d_ in pares],
                      color=[f"rgba({cor_dest.get(d_, '154,164,177')},0.45)" for _, d_ in pares],
                      customdata=[_mi(float(F.loc[o, d_])) for o, d_ in pares],
                      hovertemplate="%{source.label} → %{target.label}<br>%{customdata}<extra></extra>")))
        fig.update_traces(textfont=dict(color="#1f2937", size=13), selector=dict(type="sankey"))
        fig.update_layout(height=520, margin=dict(l=10, r=10, t=30, b=10),
                          title="Cada faixa: eleitores de um grupo no 1º turno e o que fizeram no 2º")
        st.plotly_chart(fig, width="stretch")

        # --- de onde veio o voto de cada finalista (com intervalo)
        st.markdown("**De onde veio o voto de cada finalista no 2º turno** (estimativa, intervalo de 90%)")
        linhas = []
        for o in orig:
            lin = {"Grupo no 1º turno": nome_o[o]}
            for k in fin:
                x = float(F.loc[o, k])
                lin[f"{nome_d[k]}: votos"] = x
                lin[f"{nome_d[k]}: % do total"] = x / float(F[k].sum())
                lin[f"{nome_d[k]}: intervalo"] = f"{_mi(float(lo.loc[o, k]))} – {_mi(float(hi.loc[o, k]))}"
            linhas.append(lin)
        t_orig = pd.DataFrame(linhas)
        st.dataframe(t_orig, hide_index=True, width="stretch",
                     column_config={**{c: st.column_config.NumberColumn(format="%d") for c in t_orig if c.endswith(": votos")},
                                    **{c: st.column_config.NumberColumn(format="percent") for c in t_orig
                                       if c.endswith("% do total")}})

        # --- para onde foi cada grupo
        st.markdown("**Para onde foi cada grupo do 1º turno** (% de cada linha)")
        pct_ = F.div(F.sum(axis=1), axis=0)
        t_dest = pct_.rename(index=nome_o, columns=nome_d).reset_index(names="Grupo no 1º turno")
        t_dest.insert(1, "eleitores", F.sum(axis=1).to_numpy())
        st.dataframe(t_dest, hide_index=True, width="stretch",
                     column_config={"eleitores": st.column_config.NumberColumn("eleitores (1º turno)", format="%d"),
                                    **{c: st.column_config.NumberColumn(format="percent") for c in nome_d.values()}})

        # --- comparar UFs
        with st.expander("Comparar todas as UFs"):
            alvo_f = fin[0]
            nomes_uf = sorted(set(prep["uf"]))
            comp = []
            for u in nomes_uf:
                Fu = estimar_fluxos(prep, [u])["F"]
                pu = Fu.div(Fu.sum(axis=1), axis=0)
                lin = {"UF": u, f"{nome_d[alvo_f]}: votos ganhos": float(Fu[alvo_f].sum() - Fu.sum(axis=1)[alvo_f])}
                for o in orig:
                    if o != alvo_f:
                        lin[f"{nome_o[o]} → {nome_d[alvo_f]}"] = float(pu.loc[o, alvo_f])
                comp.append(lin)
            t_uf = pd.DataFrame(comp).sort_values(f"{nome_d[alvo_f]}: votos ganhos", ascending=False)
            st.caption(f"% dos eleitores de cada grupo do 1º turno que foram para {nome_d[alvo_f]}, por UF. "
                       "UFs pequenas variam mais por acaso.")
            st.dataframe(t_uf, hide_index=True, width="stretch",
                         column_config={**{c: st.column_config.NumberColumn(format="percent") for c in t_uf
                                           if "→" in c},
                                        f"{nome_d[alvo_f]}: votos ganhos": st.column_config.NumberColumn(format="%+d")})

        with st.expander("ℹ️ Como ler e o que esta estimativa NÃO mostra"):
            st.markdown(
                "- **Como é feito**: em cada seção, olha-se quantos eleitores cada grupo tinha no 1º turno "
                "(votou em cada candidato, branco/nulo, absteve-se) e quantos foram para cada destino no 2º. "
                "Uma regressão encontra os percentuais de fluxo que melhor explicam as diferenças entre as seções, "
                "sem permitir fluxo negativo. Depois os totais são ajustados para fechar exatamente.\n"
                "- **Troca de lado invisível**: se mil eleitores foram do Flávio para o Lula e mil do Lula para o "
                "Flávio, os dados agregados não mostram. O que aparece é só o fluxo líquido.\n"
                "- **Fluxos fracos**: os grupos andam juntos no mapa (regiões onde há mais brancos e nulos tendem a "
                "ter mais abstenção), então o método separa mal alguns deles. O intervalo cobre só o acaso das "
                "amostras de municípios, **não** erros do método.\n"
                "- **Falácia ecológica**: a estimativa descreve grupos de seções, não pessoas. É um bom guia de "
                "ordem de grandeza, nunca prova de como alguém votou.\n"
                "- **Seleção no mapa**: o filtro de UF vale; município e zona têm poucas seções para estimar.")
